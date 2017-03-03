# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2017 Async Open Source <http://www.async.com.br>
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

import hashlib
import os
import re
import shutil
import sys
import urlparse

import requests
from stoqlib.api import api
from stoqlib.lib.configparser import get_config
from stoqlib.lib.webservice import WebService
from stoqlib.lib.process import Process
from stoqlib.lib.threadutils import threadit

_executable = os.path.realpath(os.path.abspath(sys.executable))
_root = os.path.dirname(_executable)
_duplicati_exe = os.path.join(_root, 'duplicati', 'Duplicati.CommandLine.exe')
# Support both http and https
_webservice_url = re.sub('https?', 'stoq',
                         urlparse.urljoin(WebService.API_SERVER, 'api/backup'))


def _get_extra_args(user_hash=None):
    passphrase = get_config().get('Backup', 'key')
    if not passphrase:
        raise Exception("No backup key set on configuration file")

    if user_hash is None:
        user_hash = api.sysparam.get_string('USER_HASH')

    return [
        '--db-hash=' + user_hash,
        '--pw-hash=' + hashlib.sha256(passphrase).hexdigest(),
        '--passphrase=' + passphrase,
    ]


def _watch_fd(fd):
    for l in iter(fd.readline, ''):
        print l


def backup(backup_dir, full=False, retry=1):
    # Tell Stoq Link Admin that you're starting a backup
    user_hash = api.sysparam.get_string('USER_HASH')
    start_url = urlparse.urljoin(WebService.API_SERVER, 'api/backup/start')
    response = requests.get(start_url, params={'hash': user_hash})

    # If the server rejects the backup, don't even attempt to proceed. Log
    # which error caused the backup to fail
    if response.status_code != 200:
        raise Exception('ERROR: ' + response.content)

    cmd = [_duplicati_exe, 'backup', _webservice_url, backup_dir,
           '--log-id=' + response.content] + _get_extra_args()
    p = Process(cmd)
    threadit(_watch_fd, p.stdout)
    threadit(_watch_fd, p.stderr)
    p.wait()

    if p.returncode == 100 and retry > 0:
        # If the password has changed, duplicati will refuse to do the
        # backup, even tough we support that on our backend. Force remove
        # the cache so it will work
        duplicati_config = os.path.join(os.getenv('APPDATA'), 'Duplicati')
        shutil.rmtree(duplicati_config, ignore_errors=True)
        return backup(backup_dir, full=full, retry=retry - 1)

    if p.returncode != 0:
        raise Exception("Failed to backup the database: {}".format(p.returncode))

    # Tell Stoq Link Admin that the backup has finished
    end_url = urlparse.urljoin(WebService.API_SERVER, 'api/backup/end')
    requests.get(end_url,
                 params={'log_id': response.content, 'hash': user_hash})


def restore(restore_dir, user_hash, time=None):
    cmd = [_duplicati_exe, 'restore', _webservice_url, '*',
           '--restore-path="{}"'.format(restore_dir),
           '--log-id=-1'] + _get_extra_args(user_hash=user_hash)
    p = Process(cmd)
    threadit(_watch_fd, p.stdout)
    threadit(_watch_fd, p.stderr)
    p.wait()

    if p.returncode != 0:
        raise Exception("Failed to restore the database: {}".format(p.returncode))


def status(user_hash=None):
    raise NotImplementedError
