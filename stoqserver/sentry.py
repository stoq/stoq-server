# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2015 Async Open Source <http://www.async.com.br>
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

import functools
import logging
import platform
import sys
import traceback
from urllib.error import URLError

import raven
from raven.transport.threaded import ThreadedHTTPTransport

import stoq
from stoqlib.api import api
from stoqlib.database.settings import get_database_version
from stoqlib.lib.configparser import StoqConfig, register_config
from stoqlib.lib.pluginmanager import InstalledPlugin
from stoqlib.lib.webservice import get_main_cnpj

import stoqserver
from .common import APP_CONF_FILE

logger = logging.getLogger(__name__)

SENTRY_URL = ('http://d971a2c535ab444ab18fa14b4b6495ea:'
              'dc3a89e2701e4336ab0c6df781d1855d@sentry.stoq.com.br/11')

raven_client = None


class SilentTransport(ThreadedHTTPTransport):
    @staticmethod
    def _handle_fail(failure_cb, url, exc):
        if isinstance(exc, URLError):
            logger.warning('Sentry responded with an error: %s (url: %s)', type(exc), url)
            return
        return failure_cb(exc)

    def send_sync(self, url, data, headers, success_cb, failure_cb):
        handle_fail = functools.partial(self._handle_fail, failure_cb, url)
        return super().send_sync(url, data, headers, success_cb, handle_fail)


def sentry_report(exctype, value, tb, **tags):
    developer_mode = stoqserver.library.uninstalled
    if raven_client is None or developer_mode:
        # Disable send sentry log if we are on developer mode.
        return

    tags.update({
        'version': stoqserver.version_str,
        'stoq_version': stoq.version,
        'architecture': platform.architecture(),
        'distribution': platform.dist(),
        'python_version': tuple(sys.version_info),
        'system': platform.system(),
        'uname': platform.uname(),
    })
    # Those are inside a try/except because thy require database access.
    # If the database access is not working, we won't be able to get them
    try:
        default_store = api.get_default_store()
        tags['user_hash'] = api.sysparam.get_string('USER_HASH')
        tags['demo'] = api.sysparam.get_bool('DEMO_MODE')
        tags['postgresql_version'] = get_database_version(default_store)
        tags['plugins'] = InstalledPlugin.get_plugin_names(default_store)
        tags['cnpj'] = get_main_cnpj(default_store)
    except Exception:
        pass

    if hasattr(raven_client, 'user_context'):
        raven_client.user_context({'id': tags.get('hash', None),
                                   'username': tags.get('cnpj', None)})
    raven_client.captureException((exctype, value, tb), tags=tags)


def setup_excepthook():
    def _excepthook(exctype, value, tb):
        sentry_report(exctype, value, tb)
        traceback.print_exception(exctype, value, tb)

    sys.excepthook = _excepthook


def setup_sentry(options):
    config = StoqConfig()
    filename = (options.filename
                if options.load_config and options.filename else
                APP_CONF_FILE)
    config.load(filename)
    # FIXME: This is called only when register_station=True. Without
    # this, db_settings would not be updated. We should fix it on Stoq
    config.get_settings()
    register_config(config)
    global SENTRY_URL, raven_client
    SENTRY_URL = config.get('Sentry', 'url') or SENTRY_URL
    raven_client = raven.Client(SENTRY_URL, release=stoqserver.version_str,
                                transport=SilentTransport)
    setup_excepthook()
