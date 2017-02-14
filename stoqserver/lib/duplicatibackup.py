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
import sys
import urlparse

import requests
from stoqlib.api import api
from stoqlib.lib.configparser import get_config
from stoqlib.lib.webservice import WebService
from stoqlib.lib.process import Process

_executable = os.path.realpath(os.path.abspath(sys.executable))
_root = os.path.dirname(_executable)
_duplicati_exe = os.path.join(_root, 'duplicati', 'Duplicati.CommandLine.exe')
# Support both http and https
_webservice_url = re.sub('https?', 'stoq',
                         urlparse.urljoin(WebService.API_SERVER, 'api/backup'))


def _get_extra_args():
    passphrase = get_config().get('Backup', 'key')
    if not passphrase:
        raise Exception("No backup key set on configuration file")

    return [
        '--db-hash=' + api.sysparam.get_string('USER_HASH'),
        '--pw-hash=' + hashlib.sha256(passphrase).hexdigest(),
        '--passphrase=' + passphrase,
    ]


def backup(backup_dir, full=False):
    # Tell Stoq Link Admin that you're starting a backup
    user_hash = api.sysparam.get_string('USER_HASH')
    start_url = urlparse.urljoin(WebService.API_SERVER, 'api/backup/start')
    response = requests.get(start_url, params={'hash': user_hash})

    # If the server rejects the backup, don't even attempt to proceed. Log
    # which error caused the backup to fail
    if response.status_code != 200:
        raise Exception('ERROR: ' + response.content)

    cmd = [_duplicati_exe, 'backup', _webservice_url, '"{}"'.format(backup_dir),
           '--log-id=' + response.content] + _get_extra_args()
    p = Process(cmd)
    p.wait()

    if p.returncode != 0:
        raise Exception("Failed to backup the database")

    # Tell Stoq Link Admin that the backup has finished
    end_url = urlparse.urljoin(WebService.API_SERVER, 'api/backup/end')
    requests.get(end_url,
                 params={'log_id': response.content, 'hash': user_hash})


def restore(restore_dir, user_hash, time=None):
    cmd = [_duplicati_exe, 'restore', _webservice_url, '"*"',
           '--restore_path="{}"'.format(restore_dir),
           '--log-id=-1'] + _get_extra_args()
    p = Process(cmd)
    p.wait()

    if p.returncode != 0:
        raise Exception("Failed to restore the database")


def status(user_hash=None):
    raise NotImplementedError
