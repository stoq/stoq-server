# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2015 Async Open Source <http://www.async.com.br>
## All rights reserved
##
## This program is free software; you can redistribute it and/or
## modify it under the terms of the GNU Lesser General Public License
## as published by the Free Software Foundation; either version 2
## of the License, or (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU Lesser General Public License for more details.
##
## You should have received a copy of the GNU Lesser General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., or visit: http://www.gnu.org/.
##
## Author(s): Stoq Team <stoq-devel@async.com.br>
##

import datetime
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from stoqlib.database.runtime import get_default_store, set_default_store
from stoqlib.lib.configparser import get_config
from twisted.internet import reactor, task
from twisted.web import resource
from twisted.web import server

from stoqserver import library
from stoqserver.common import APP_BACKUP_DIR, SERVER_XMLRPC_PORT
from stoqserver.lib import backup
from stoqserver.lib.decorators import reactor_handler
from stoqserver.lib.xmlrpcresource import ServerXMLRPCResource
from stoqserver.server import StoqServer

logger = logging.getLogger(__name__)


def _get_pg_args(config):
    args = []
    for pg_arg, config_key in [
            ('-U', 'dbusername'),
            ('-h', 'address'),
            ('-p', 'port')]:
        config_value = config.get('Database', config_key)
        if config_value is not None:
            args.extend([pg_arg, config_value])

    return args


def backup_database(full=False):
    config = get_config()

    if not os.path.exists(APP_BACKUP_DIR):
        os.makedirs(APP_BACKUP_DIR)

    filename = os.path.join(APP_BACKUP_DIR, 'stoq.dump')
    subprocess.check_call(
        ['pg_dump', '-Fp', '-f', filename] +
        _get_pg_args(config) +
        [config.get('Database', 'dbname')])

    backup.backup(APP_BACKUP_DIR, full=full)

    logger.info("Database backup finished sucessfully")


def restore_database(user_hash, time=None):
    assert user_hash
    tmp_path = tempfile.mkdtemp()
    try:
        # None will make the default store be closed, which we need
        # to sucessfully restore the database
        set_default_store(None)
        restore_path = os.path.join(tmp_path, 'stoq')

        config = get_config()
        dbname = config.get('Database', 'dbname')

        backup.restore(restore_path, user_hash, time=time)

        # Drop the database
        subprocess.check_call(
            ['dropdb'] + _get_pg_args(config) + [dbname])

        # Create the database
        subprocess.check_call(
            ['createdb'] + _get_pg_args(config) + [dbname])

        # Restore the backup
        subprocess.check_call(
            ['psql', '-d', dbname] +
            _get_pg_args(config) +
            ['-f', os.path.join(restore_path, 'stoq.dump')])

        logger.info("Backup restore finished sucessfully")
    finally:
        # get_default_store will recreate it (since we closed it above)
        get_default_store()
        shutil.rmtree(tmp_path, ignore_errors=True)


def backup_status(user_hash=None):
    backup.status(user_hash=user_hash)


@reactor_handler
def start_xmlrpc_server(pipe_conn):
    logger.info("Starting the xmlrpc server")

    config = get_config()
    port = int(config.get('General', 'serverport') or SERVER_XMLRPC_PORT)

    r = resource.Resource()
    r.putChild('XMLRPC', ServerXMLRPCResource(r, pipe_conn))
    site = server.Site(r)

    reactor.callWhenRunning(reactor.listenTCP, port, site)


@reactor_handler
def start_server():
    logger.info("Starting stoq server")

    stoq_server = StoqServer()
    reactor.callWhenRunning(stoq_server.start)
    reactor.addSystemEventTrigger('before', 'shutdown', stoq_server.stop)


def start_rtc():
    logger.info("Starting webRTC")

    cwd = library.get_resource_filename('stoqserver', 'webrtc')

    subprocess.call(["npm", "install"], cwd=cwd)
    popen = subprocess.Popen(["node", "rtc.js"], cwd=cwd)

    def _sigterm_handler(_signal, _stack_frame):
        if popen.poll():
            popen.terminate()

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, _sigterm_handler)
    popen.wait()


@reactor_handler
def start_backup_scheduler():
    logger.info("Starting backup scheduler")

    # TODO: For now we are running backups every midday and midnight.
    # Maybe we should make this configurable
    now = datetime.datetime.now()
    if now.hour < 12:
        midday = now.replace(hour=12, minute=0, second=0, microsecond=0)
        delta = midday - now
    else:
        tomorrow = now + datetime.timedelta(1)
        midnight = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        delta = midnight - now

    def _backup_task():
        for i in xrange(3):
            # FIXME: This is SO UGLY, we should be calling backup_database
            # task directly, but duplicity messes with multiprocessing in a
            # way that it will not work
            args = sys.argv[:]
            for i, arg in enumerate(args[:]):
                if arg == 'run':
                    args[i] = 'backup_database'
                    break

            p = subprocess.Popen(args)
            stdout, stderr = p.communicate()
            if p.returncode == 0:
                break
            else:
                logger.warning(
                    "Failed to backup database:\nstdout: %s\nstderr: %s",
                    stdout, stderr)
                # Retry again with a exponential backoff
                time.sleep((60 * 2) ** (i + 1))

    backup_task = task.LoopingCall(_backup_task)
    # Schedule the task to start at the first midday/midnight and then
    # run every 12 hours
    reactor.callWhenRunning(reactor.callLater, delta.seconds,
                            lambda: backup_task.start(12 * 60 * 60))
    reactor.addSystemEventTrigger(
        'before', 'shutdown',
        lambda: getattr(task, 'running', False) and task.stop())
