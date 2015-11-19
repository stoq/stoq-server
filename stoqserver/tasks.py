# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2015 Async Open Source <http://www.async.com.br>
## All rights reserved
##

import logging
import os
import shutil
import subprocess
import tempfile

from stoqlib.lib.configparser import get_config

from stoqserver.common import APP_BACKUP_DIR
from stoqserver.lib import backup

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
