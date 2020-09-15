# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2020 Stoq Tecnologia <http://www.stoq.com.br>
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
# Author(s): Stoq Team <dev@stoq.com.br>
#

import atexit
import base64
import http.server
try:
    import dbus
    import avahi
except ImportError:
    # FIXME: Windows
    dbus = None
    avahi = None

import logging
import os
import tempfile

import pkg_resources

from stoqlib.api import api
from stoqlib.domain.person import LoginUser
from stoqlib.exceptions import LoginError
from stoqlib.lib.configparser import get_config
from stoqlib.lib.fileutils import md5sum_for_filename

from stoqserver.common import (AVAHI_DOMAIN, AVAHI_HOST, AVAHI_STYPE,
                               SERVER_NAME, SERVER_AVAHI_PORT,
                               SERVER_EGGS, APP_CONF_FILE)

try:
    _eggs_path = pkg_resources.resource_filename('stoqserver', 'eggs')
except KeyError:
    # FIXME: Windows
    _eggs_path = ''

_md5sum_path = None
logger = logging.getLogger(__name__)


# TODO: This is experimental and not used anywhere in production,
# which means that we can tweak it a lot without having to worry
# to break something.
class _RequestHandler(http.server.SimpleHTTPRequestHandler):

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        auth = self.headers.getheader('Authorization')
        if not auth or not auth.startswith('Basic '):
            self.do_AUTHHEAD()
            self.wfile.write('Missing authentication')
            return

        encoded_auth = auth.replace('Basic ', '')
        username, password = base64.b64decode(encoded_auth).split(':')
        with api.new_store() as store:
            try:
                login_ok = LoginUser.authenticate(
                    store, str(username), str(password), None)
            except LoginError:
                login_ok = False

        if not login_ok:
            self.send_error(403, "User not found")
            return

        return http.server.SimpleHTTPRequestHandler.do_GET(self)

    def do_AUTHHEAD(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm=\"Stoq Login\"')
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def translate_path(self, path):
        # FIXME: Improve this when we really use it
        if path == '/login':
            return APP_CONF_FILE
        elif path.startswith('/eggs'):
            # SimpleHTTPRequestHandler calls this to translate the url path
            # into a filesystem path. It will always start with os.getcwd(),
            # which means we just need to replace it with the _static path
            translated = http.server.SimpleHTTPRequestHandler.translate_path(
                # /eggs is just the endpoing name, the real path doesn't have it
                self, path.replace('/eggs', ''))
            return translated.replace(os.getcwd(), _eggs_path)
        else:
            return path


class StoqServer(object):

    def __init__(self):
        config = get_config()
        self._port = int(config.get('General', 'serveravahiport') or SERVER_AVAHI_PORT)

    #
    #  Public API
    #

    def run(self):
        if dbus is not None:
            try:
                self._setup_avahi()
            except dbus.exceptions.DBusException as e:
                logger.warning("Failed to setup avahi: %s", str(e))

        # md5sum
        with tempfile.NamedTemporaryFile(delete=False) as f:
            for egg in SERVER_EGGS:
                egg_path = os.path.join(_eggs_path, egg)
                if not os.path.exists(_eggs_path):
                    continue

                f.write('%s:%s\n' % (egg, md5sum_for_filename(egg_path)))

        global _md5sum_path
        _md5sum_path = f.name
        server = http.server.HTTPServer(('localhost', self._port), _RequestHandler)
        server.serve_forever()

    #
    #  Private
    #

    def _setup_avahi(self):
        if avahi is None:
            return

        bus = dbus.SystemBus()
        dbus_server = dbus.Interface(
            bus.get_object(avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER),
            avahi.DBUS_INTERFACE_SERVER)

        self.group = dbus.Interface(
            bus.get_object(avahi.DBUS_NAME, dbus_server.EntryGroupNew()),
            avahi.DBUS_INTERFACE_ENTRY_GROUP)
        self.group.AddService(
            avahi.IF_UNSPEC, avahi.PROTO_UNSPEC, dbus.UInt32(0), SERVER_NAME,
            AVAHI_STYPE, AVAHI_DOMAIN, AVAHI_HOST,
            dbus.UInt16(self._port),
            avahi.string_array_to_txt_array(['foo=bar']))

        self.group.Commit()
        atexit.register(lambda: self.group.Reset())
