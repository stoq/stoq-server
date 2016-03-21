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

import dbus
import logging
import os
import tempfile

import avahi
from stoqlib.api import api
from stoqlib.domain.person import LoginUser
from stoqlib.exceptions import LoginError
from stoqlib.lib.fileutils import md5sum_for_filename
from twisted.cred import portal, checkers, credentials, error as cred_error
from twisted.internet import reactor, defer
from twisted.web import static, server, resource
from twisted.web.guard import BasicCredentialFactory
from twisted.web.guard import HTTPAuthSessionWrapper
from twisted.web.http import HTTPChannel
from twisted.web.resource import IResource
from zope.interface import implements

from stoqserver import library
from stoqserver.common import (AVAHI_DOMAIN, AVAHI_HOST, AVAHI_STYPE,
                               SERVER_NAME, SERVER_AVAHI_PORT,
                               SERVER_EGGS, APP_CONF_FILE)

_ = lambda s: s
logger = logging.getLogger(__name__)


class _PasswordChecker(object):
    implements(checkers.ICredentialsChecker)
    credentialInterfaces = (credentials.IUsernamePassword, )

    #
    #  ICredentialsChecker
    #

    def requestAvatarId(self, credentials):
        with api.new_store() as store:
            try:
                login_ok = LoginUser.authenticate(
                    store,
                    unicode(credentials.username),
                    unicode(credentials.password),
                    None)
            except LoginError as err:
                return defer.fail(cred_error.UnauthorizedLogin(str(err)))

        assert login_ok
        return defer.succeed(credentials.username)


class _HttpPasswordRealm(object):
    implements(portal.IRealm)

    def __init__(self, resource):
        self._resource = resource

    #
    #  IRealm
    #

    def requestAvatar(self, user, mind, *interfaces):
        if IResource in interfaces:
            # self._resource is passed on regardless of user
            return (IResource, self._resource, lambda: None)

        raise NotImplementedError()


class StoqServer(object):

    def __init__(self):
        self.group = None
        self.listener = None

    #
    #  Public API
    #

    def start(self):
        self._setup_twisted()
        try:
            self._setup_avahi()
        except dbus.exceptions.DBusException as e:
            logger.warning("Failed to setup avahi: %s", str(e))

    def stop(self):
        if self.listener is not None:
            self.listener.stopListening()
        if self.group is not None:
            self.group.Reset()

    #
    #  Private
    #

    def _get_resource_wrapper(self, resource, checker, credentials_factory):
        realm = _HttpPasswordRealm(resource)
        p = portal.Portal(realm, [checker])
        return HTTPAuthSessionWrapper(p, [credentials_factory])

    def _setup_twisted(self):
        root = resource.Resource()
        checker = _PasswordChecker()
        cf = BasicCredentialFactory(SERVER_NAME)

        # eggs
        eggs_path = library.get_resource_filename('stoqserver', 'eggs')
        root.putChild(
            'eggs',
            self._get_resource_wrapper(static.File(eggs_path), checker, cf))

        # conf
        root.putChild(
            'login',
            self._get_resource_wrapper(static.File(APP_CONF_FILE), checker, cf))

        # md5sum
        with tempfile.NamedTemporaryFile(delete=False) as f:
            for egg in SERVER_EGGS:
                egg_path = os.path.join(eggs_path, egg)
                if not os.path.exists(eggs_path):
                    continue

                f.write('%s:%s\n' % (egg, md5sum_for_filename(egg_path)))

        root.putChild('md5sum', static.File(f.name))

        site = server.Site(root)
        site.protocol = HTTPChannel

        self.listener = reactor.listenTCP(SERVER_AVAHI_PORT, site)

    def _setup_avahi(self):
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
            dbus.UInt16(SERVER_AVAHI_PORT),
            avahi.string_array_to_txt_array(['foo=bar']))

        self.group.Commit()
