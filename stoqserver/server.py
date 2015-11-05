# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2014 Async Open Source <http://www.async.com.br>
## All rights reserved
##

import dbus
import os
import pkg_resources
import tempfile

import avahi
from stoq.lib.startup import setup
from stoqlib.api import api
from stoqlib.domain.person import LoginUser
from stoqlib.exceptions import LoginError
from stoqlib.lib.fileutils import md5sum_for_filename
from stoqlib.lib.configparser import StoqConfig
from stoqlib.lib.daemonutils import DaemonManager
from twisted.cred import portal, checkers, credentials, error as cred_error
from twisted.internet import reactor, defer
from twisted.web import static, server, resource
from twisted.web.guard import BasicCredentialFactory
from twisted.web.guard import HTTPAuthSessionWrapper
from twisted.web.http import HTTPChannel
from twisted.web.resource import IResource
from zope.interface import implements

from stoqserver.common import (AVAHI_DOMAIN, AVAHI_HOST, AVAHI_STYPE,
                               SERVER_NAME, SERVER_PORT, SERVER_EGGS,
                               APP_CONF_FILE)

_ = lambda s: s


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


class _StoqServer(object):

    #
    #  Public API
    #

    def start(self):
        self._setup_twisted()
        self._setup_avahi()

    def stop(self):
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
        eggs_path = pkg_resources.resource_filename(
            'stoqserver', 'data/eggs')
        root.putChild(
            'eggs',
            self._get_resource_wrapper(static.File(eggs_path), checker, cf))

        # conf
        root.putChild(
            'login',
            self._get_resource_wrapper(static.File(APP_CONF_FILE), checker, cf))

        # md5sum
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.writelines(
                '%s:%s\n' % (
                    egg, md5sum_for_filename(os.path.join(eggs_path, egg)))
                for egg in SERVER_EGGS)

        root.putChild('md5sum', static.File(f.name))

        site = server.Site(root)
        site.protocol = HTTPChannel

        reactor.listenTCP(SERVER_PORT, site)

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
            AVAHI_STYPE, AVAHI_DOMAIN, AVAHI_HOST, dbus.UInt16(SERVER_PORT),
            avahi.string_array_to_txt_array(['foo=bar']))

        self.group.Commit()


def main(args):
    config = StoqConfig()
    config.load(APP_CONF_FILE)
    # FIXME: This is called only when register_station=True. Without
    # this, db_settings would not be updated. We should fix it on Stoq
    config.get_settings()

    # FIXME: Maybe we should check_schema and load plugins here?
    setup(config=config, options=None, register_station=False,
          check_schema=False, load_plugins=False)

    stoq_server = _StoqServer()
    reactor.callWhenRunning(stoq_server.start)
    reactor.addSystemEventTrigger('before', 'shutdown', stoq_server.stop)

    port = config.get('General', 'serverport')
    dm = DaemonManager(port=port and int(port))
    dm.start()

    try:
        reactor.run()
    except KeyboardInterrupt:
        reactor.stop()
