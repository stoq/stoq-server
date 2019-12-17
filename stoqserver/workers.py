# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2020 Async Open Source <http://www.async.com.br>
# All rights reserved
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., or visit: http://www.gnu.org/.
#
# Author(s): Stoq Team <stoq-devel@async.com.br>
#

import datetime
import json
import logging
import os
import platform
import re
import subprocess
from hashlib import md5

import gevent
import psutil
import requests
import tzlocal

from stoq import version as stoq_version
from stoqdrivers import __version__ as stoqdrivers_version
from stoqlib.api import api
from stoqlib.database.settings import get_database_version
from stoqlib.lib.configparser import get_config
from stoqlib.lib.environment import is_developer_mode
from stoqlib.lib.pluginmanager import get_plugin_manager

from . import __version__ as stoqserver_version
from .lib.checks import check_drawer, check_pinpad, check_sat
from .lib.lock import LockFailedException
from .lib.restful import EventStream
from .signals import CheckSatStatusEvent

logger = logging.getLogger(__name__)

WORKERS = []


def worker(f):
    """A marker for a function that should be threaded when the server executes.

    Usefull for regular checks that should be made on the server that will require warning the
    client
    """
    WORKERS.append(f)
    return f


@worker
def check_drawer_loop(station):
    # default value of is_open
    is_open = ''

    # Check every second if it is opened.
    # Alert only if changes.
    while True:
        new_is_open = check_drawer()

        if is_open != new_is_open:
            message = {
                True: 'DRAWER_ALERT_OPEN',
                False: 'DRAWER_ALERT_CLOSE',
                None: 'DRAWER_ALERT_ERROR',
            }
            EventStream.put(station, {
                'type': message[new_is_open],
            })
            status_printer = None if new_is_open is None else True
            EventStream.put(station, {
                'type': 'DEVICE_STATUS_CHANGED',
                'device': 'printer',
                'status': status_printer,
            })
            is_open = new_is_open

        gevent.sleep(1)


@worker
def check_sat_loop(station):
    if len(CheckSatStatusEvent.receivers) == 0:
        return

    sat_ok = -1

    while True:
        try:
            new_sat_ok = check_sat()
        except LockFailedException:
            # Keep previous state.
            new_sat_ok = sat_ok

        if sat_ok != new_sat_ok:
            EventStream.put(station, {
                'type': 'DEVICE_STATUS_CHANGED',
                'device': 'sat',
                'status': new_sat_ok,
            })
            sat_ok = new_sat_ok

        gevent.sleep(60 * 5)


@worker
def check_pinpad_loop(station):
    pinpad_ok = -1

    while True:
        try:
            new_pinpad_ok = check_pinpad()
        except LockFailedException:
            # Keep previous state.
            new_pinpad_ok = pinpad_ok

        if pinpad_ok != new_pinpad_ok:
            EventStream.put(station, {
                'type': 'DEVICE_STATUS_CHANGED',
                'device': 'pinpad',
                'status': new_pinpad_ok,
            })
            pinpad_ok = new_pinpad_ok

        gevent.sleep(60)


@worker
def post_ping_request(station):
    if is_developer_mode():
        return

    from .lib.restful import PDV_VERSION
    target = 'https://app.stoq.link:9000/api/ping'
    time_format = '%d-%m-%Y %H:%M:%S%Z'
    store = api.get_default_store()
    plugin_manager = get_plugin_manager()
    boot_time = datetime.datetime.fromtimestamp(psutil.boot_time()).strftime(time_format)

    def get_stoq_conf():
        with open(get_config().get_filename(), 'r') as fh:
            return fh.read().encode()

    def get_clisitef_ini():
        try:
            with open('CliSiTef.ini', 'r') as fh:
                return fh.read().encode()
        except FileNotFoundError:
            return ''.encode()

    while True:
        try:
            dpkg_list = subprocess.check_output('dpkg -l \\*stoq\\*', shell=True).decode()
        except subprocess.CalledProcessError:
            dpkg_list = ""
        stoq_packages = re.findall(r'ii\s*(\S*)\s*(\S*)', dpkg_list)
        if PDV_VERSION:
            logger.info('Running stoq_pdv {}'.format(PDV_VERSION))
        logger.info('Running stoq {}'.format(stoq_version))
        logger.info('Running stoq-server {}'.format(stoqserver_version))
        logger.info('Running stoqdrivers {}'.format(stoqdrivers_version))
        local_time = tzlocal.get_localzone().localize(datetime.datetime.now())

        response = requests.post(
            target,
            headers={'Stoq-Backend': '{}-portal'.format(api.sysparam.get_string('USER_HASH'))},
            data={
                'station_id': station.id,
                'data': json.dumps({
                    'platform': {
                        'architecture': platform.architecture(),
                        'distribution': platform.dist(),
                        'system': platform.system(),
                        'uname': platform.uname(),
                        'python_version': platform.python_version_tuple(),
                        'postgresql_version': get_database_version(store)
                    },
                    'system': {
                        'boot_time': boot_time,
                        'cpu_times': psutil.cpu_times(),
                        'load_average': os.getloadavg(),
                        'disk_usage': psutil.disk_usage('/'),
                        'virtual_memory': psutil.virtual_memory(),
                        'swap_memory': psutil.swap_memory()
                    },
                    'plugins': {
                        'available': plugin_manager.available_plugins_names,
                        'installed': plugin_manager.installed_plugins_names,
                        'active': plugin_manager.active_plugins_names,
                        'versions': getattr(plugin_manager, 'available_plugins_versions', None)
                    },
                    'running_versions': {
                        'pdv': PDV_VERSION,
                        'stoq': stoq_version,
                        'stoqserver': stoqserver_version,
                        'stoqdrivers': stoqdrivers_version
                    },
                    'stoq_packages': dict(stoq_packages),
                    'local_time': local_time.strftime(time_format),
                    'stoq_conf_md5': md5(get_stoq_conf()).hexdigest(),
                    'clisitef_ini_md5': md5(get_clisitef_ini()).hexdigest()
                })
            }
        )

        logger.info("POST {} {} {}".format(
            target,
            response.status_code,
            response.elapsed.total_seconds()))
        gevent.sleep(3600)
