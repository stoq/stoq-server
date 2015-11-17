# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2015 Async Open Source <http://www.async.com.br>
## All rights reserved
##

import os
import shutil
import subprocess
import tempfile

from stoqlib.lib.configparser import get_config

from stoqserver.common import APP_BACKUP_DIR


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


def backup_database():
    config = get_config()

    if not os.path.exists(APP_BACKUP_DIR):
        os.makedirs(APP_BACKUP_DIR)

    filename = os.path.join(APP_BACKUP_DIR, 'stoq.dump')
    subprocess.check_call(
        ['pg_dump', '-Fc', '-f', filename] +
        _get_pg_args(config) +
        [config.get('Database', 'dbname')])

    env = os.environ
    # FIXME: The user must define the passphrase
    env.setdefault('PASSPHRASE', 'foobarbaz')

    # FIXME: Change the destination to a s3 bucket
    subprocess.check_call(
        ['duplicity', APP_BACKUP_DIR, 'file:///tmp/stoq_backup'], env=env)


def restore_database():
    env = os.environ
    # FIXME: The user must define the passphrase
    env.setdefault('PASSPHRASE', 'foobarbaz')

    tmp_path = tempfile.mkdtemp()
    try:
        restore_path = os.path.join(tmp_path, 'stoq')

        config = get_config()
        dbname = config.get('Database', 'dbname')

        # FIXME: Change the destination to a s3 bucket
        subprocess.check_call(
            ['duplicity', 'restore',
             'file:///tmp/stoq_backup', restore_path], env=env)

        # Drop the database
        subprocess.check_call(
            ['dropdb'] + _get_pg_args(config) + [dbname])

        # Create the database
        subprocess.check_call(
            ['createdb'] + _get_pg_args(config) + [dbname])

        # Restore the backup
        subprocess.check_call(
            ['pg_restore', '-Fc', '-d', dbname] +
            _get_pg_args(config) +
            [os.path.join(restore_path, 'stoq.dump')])
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
