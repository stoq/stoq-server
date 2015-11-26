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

import logging
import os
import shutil
import subprocess
import tempfile

from stoqlib.lib.configparser import get_config
from stoqlib.lib.daemonutils import DaemonManager
from twisted.internet import reactor

from stoqserver.common import APP_BACKUP_DIR, SERVER_DAEMON_PORT
from stoqserver.lib import backup
from stoqserver.lib.decorators import reactor_handler
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

    logging.info("Database backup finished sucessfully")


def restore_database(user_hash, time=None):
    assert user_hash
    tmp_path = tempfile.mkdtemp()
    try:
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

        logging.info("Backup restore finished sucessfully")
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def backup_status(user_hash=None):
    backup.status(user_hash=user_hash)


@reactor_handler
def start_daemon_manager():
    logging.info("Starting daemon manager")

    config = get_config()
    port = config.get('General', 'serverport') or SERVER_DAEMON_PORT
    dm = DaemonManager(port=port and int(port))
    reactor.callWhenRunning(dm.start)
    reactor.addSystemEventTrigger('before', 'shutdown', dm.stop)


@reactor_handler
def start_server():
    logging.info("Starting stoq server")

    stoq_server = StoqServer()
    reactor.callWhenRunning(stoq_server.start)
    reactor.addSystemEventTrigger('before', 'shutdown', stoq_server.stop)
