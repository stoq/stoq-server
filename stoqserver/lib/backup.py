# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2015 Async Open Source <http://www.async.com.br>
## All rights reserved
##

import base64
import contextlib
import imp
import json
import os
import sys
import urlparse

from duplicity import backend
try:
    # This is only available on duplicity <= 0.6
    from duplicity.backend import _ensure_urlparser_initialized, urlparser
except ImportError:
    uses_netloc = backend.uses_netloc
else:
    _ensure_urlparser_initialized()
    uses_netloc = urlparser.uses_netloc
import requests
from stoqlib.api import api
from stoqlib.lib.configparser import get_config
from stoqlib.lib.webservice import WebService

_duplicity_bin = '/usr/bin/duplicity'
_duplicity_main = imp.load_source('main', _duplicity_bin)
_webservice_url = WebService.API_SERVER.replace('http', 'stoq')
# FIXME: Find a better way of passing the user hash to StoqBackend.
# We can't get it from database when restoring the database for example
_user_hash = None


class StoqBackend(backend.Backend):

    SCHEME = 'stoq'
    TIMEOUT = 60

    def __init__(self, url):
        backend.Backend.__init__(self, url)

        self._api_url = 'http://%s:%s' % (url.hostname, url.port or 80)

    #
    #  backend.Backend
    #

    def put(self, source_path, remote_filename=None):
        # If remote_filename is None, duplicity API says source_path
        # filename should be used instead
        remote_filename = remote_filename or source_path.get_filename()
        data = base64.b64encode(source_path.get_data())

        self._do_request(
            'post', method='POST', filename=remote_filename, content=data)

    def get(self, remote_filename, local_path):
        url = self._do_request(
            'get', filename=remote_filename)

        with open(local_path.name, 'w') as local_file:
            res = requests.get(url)
            local_file.write(base64.b64decode(res.text))

    def list(self):
        response = self._do_request('list')
        # FIXME: Some versions of the duplicity doesn't allow unicode
        return [f.encode('utf-8') if isinstance(f, unicode) else f for
                f in json.loads(response)]

    def delete(self, remote_filename):
        self._do_request('delete', filename=remote_filename)

    def close(self):
        pass

    #
    #  Private
    #

    def _do_request(self, endpoint, method='GET', **data):
        url = urlparse.urljoin(self._api_url, 'api/backup/' + endpoint)
        data['hash'] = _user_hash

        extra_args = {}
        if method == 'GET':
            extra_args['params'] = data
        elif method == 'POST':
            extra_args['data'] = data
        else:
            raise AssertionError

        res = requests.request(method, url, timeout=self.TIMEOUT, **extra_args)
        return res.text


# For some reason, duplicity 0.7+ changed its backend api to private members
# This is to support it, they should not causa any problems for 0.6
StoqBackend._put = StoqBackend.put
StoqBackend._get = StoqBackend.get
StoqBackend._list = StoqBackend.list
StoqBackend._delete = StoqBackend.delete
StoqBackend._close = StoqBackend.close

uses_netloc.append(StoqBackend.SCHEME)
backend.register_backend(StoqBackend.SCHEME, StoqBackend)


@contextlib.contextmanager
def _mock_environ():
    old_argv = sys.argv[:]
    while sys.argv:
        sys.argv.pop()
    old_environ = os.environ.copy()

    yield

    while sys.argv:
        sys.argv.pop()
    sys.argv.extend(old_argv)
    os.environ.clear()
    os.environ.update(old_environ)


def status(user_hash=None):
    global _user_hash
    _user_hash = user_hash or api.sysparam.get_string('USER_HASH')

    with _mock_environ():
        sys.argv.extend([_duplicity_bin, 'collection-status', _webservice_url])
        _duplicity_main.main()


def backup(backup_dir, full=False):
    global _user_hash
    _user_hash = api.sysparam.get_string('USER_HASH')

    with _mock_environ():
        config = get_config()

        os.environ.setdefault('PASSPHRASE', config.get('Backup', 'key'))
        sys.argv.append(_duplicity_bin)
        if full:
            sys.argv.append('full')
        sys.argv.extend([backup_dir, _webservice_url])

        _duplicity_main.main()


def restore(restore_dir, user_hash, time=None):
    global _user_hash
    _user_hash = user_hash

    with _mock_environ():
        config = get_config()

        os.environ.setdefault('PASSPHRASE', config.get('Backup', 'key'))
        # Close the main store so the database can be dropped after this
        api.get_default_store().rollback(close=True)
        sys.argv.extend([_duplicity_bin, 'restore',
                         _webservice_url, restore_dir])
        if time is not None:
            sys.argv.extend(['--time', time])

        _duplicity_main.main()
