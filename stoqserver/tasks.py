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
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from stoqlib.api import api
from stoqlib.exceptions import DatabaseError
from stoqlib.database.runtime import get_default_store, set_default_store
from stoqlib.database.settings import db_settings
from stoqlib.lib.configparser import get_config
from twisted.internet import reactor, task
from twisted.web import resource, server

from stoqserver import library
from stoqserver.common import APP_BACKUP_DIR, SERVER_XMLRPC_PORT
from stoqserver.lib import backup
from stoqserver.lib.decorators import reactor_handler
from stoqserver.lib.xmlrpcresource import ServerXMLRPCResource
from stoqserver.server import StoqServer

logger = logging.getLogger(__name__)


class TaskException(Exception):
    """Default tasks exception"""


def backup_database(full=False):
    if not os.path.exists(APP_BACKUP_DIR):
        os.makedirs(APP_BACKUP_DIR)

    filename = os.path.join(APP_BACKUP_DIR, 'stoq.dump')
    if not db_settings.dump_database(filename, format='plain'):
        raise TaskException("Failed to dump the database")

    backup.backup(APP_BACKUP_DIR, full=full)
    logger.info("Database backup finished sucessfully")


def restore_database(user_hash, time=None):
    assert user_hash

    # If the database doesn't exist, get_default_store will fail
    try:
        default_store = get_default_store()
    except Exception:
        default_store = None

    if default_store is not None and db_settings.has_database():
        try:
            default_store.lock_database()
        except DatabaseError:
            raise TaskException(
                "Could not lock database. This means that there are other "
                "clients connected. Make sure to close every Stoq client "
                "before updating the database")
        except Exception:
            raise TaskException(
                "Database is empty or in a corrupted state. Fix or drop it "
                "before trying to proceed with the restore")
        else:
            default_store.unlock_database()

        with tempfile.NamedTemporaryFile() as f:
            if not db_settings.dump_database(f.name):
                raise TaskException("Failed to dump the database")
            backup_name = db_settings.restore_database(f.name)
            logger.info("Created a backup of the current database state on %s",
                        backup_name)

    tmp_path = tempfile.mkdtemp()
    try:
        # None will make the default store be closed, which we need
        # to sucessfully restore the database
        set_default_store(None)
        restore_path = os.path.join(tmp_path, 'stoq')

        backup.restore(restore_path, user_hash, time=time)

        db_settings.clean_database(db_settings.dbname, force=True)
        db_settings.execute_sql(os.path.join(restore_path, 'stoq.dump'),
                                lock_database=True)

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
    if not api.sysparam.get_bool('ONLINE_SERVICES'):
        logger.info("ONLINE_SERVICES not enabled. Not starting rtc...")
        return

    logger.info("Starting webRTC")

    cwd = library.get_resource_filename('stoqserver', 'webrtc')
    retry = True

    config = get_config()
    extra_args = []
    urls = config.get('Camera', 'url') or None
    if urls:
        extra_args.append('-c=' + ' '.join(set(urls.split(' '))))

    while retry:
        retry = False
        popen = subprocess.Popen(
            ['bash', 'start.sh'] + extra_args, cwd=cwd)

        def _sigterm_handler(_signal, _stack_frame):
            popen.poll()
            if popen.returncode is None:
                popen.terminate()
            os._exit(0)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, _sigterm_handler)

        popen.wait()
        if popen.returncode == 11:
            logger.warning("libstdc++ too old, not running webRTC client. "
                           "A system upgrade may be required!")
            retry = False
        elif popen.returncode == 10:
            logger.warning("Something failed when trying to start webrtc. "
                           "Retrying again in 10 minutes...")
            time.sleep(10 * 60)
            retry = True
        elif popen.returncode == 12:
            logger.warning("webrtc installation corrupted. Restarting it...")
            time.sleep(1)
            retry = True
        elif popen.returncode == 139:
            logger.warning("Segmentation fault caught on wrtc. Restarting...")
            time.sleep(1)
            retry = True


@reactor_handler
def start_backup_scheduler():
    if not api.sysparam.get_bool('ONLINE_SERVICES'):
        logger.info("ONLINE_SERVICES not enabled. Not scheduling backups...")
        return

    logger.info("Starting backup scheduler")

    config = get_config()
    backup_schedule = config.get('Backup', 'schedule')
    if backup_schedule is None:
        # By defualt, we will do 2 backups. One in a random time between
        # 9-11 or 14-17 and another one 12 hours after that.
        # We are using 2, 3 and 4 because they will be summed with 12 bellow
        hour = random.choice([2, 3, 4, 9, 10])
        minute = random.randint(0, 59)
        backup_schedule = '%d:%d,%s:%d' % (hour, minute, hour + 12, minute)
        config.set('Backup', 'schedule', backup_schedule)
        config.flush()

    backup_hours = [map(int, i.strip().split(':'))
                    for i in backup_schedule.split(',')]

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

    for backup_hour in backup_hours:
        now = datetime.datetime.now()
        backup_date = now.replace(hour=backup_hour[0], minute=backup_hour[1],
                                  second=0, microsecond=0)
        if backup_date < now:
            backup_date = backup_date + datetime.timedelta(1)

        delta = backup_date - now

        backup_task = task.LoopingCall(_backup_task)
        # Schedule the task to start at the backup hour and repeat
        # every 24 hours
        reactor.callWhenRunning(reactor.callLater, delta.seconds,
                                backup_task.start, 24 * 60 * 60)
        reactor.addSystemEventTrigger(
            'before', 'shutdown',
            lambda: getattr(task, 'running', False) and task.stop())
