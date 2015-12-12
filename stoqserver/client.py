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

import ConfigParser
import hashlib
import io
import os
import socket
import sys
import tempfile
import urllib2
import urlparse

import gtk
import netifaces
from zeroconf import ServiceBrowser, Zeroconf

from stoqserver.common import (APP_EGGS_DIR, SERVER_EGGS,
                               SERVER_EXECUTABLE_EGG, AVAHI_STYPE,
                               SERVER_XMLRPC_PORT)

_ = lambda s: s


class _StoqClient(gtk.Window):
    def __init__(self, *args, **kwargs):
        gtk.Window.__init__(self, *args, **kwargs)

        if not os.path.exists(APP_EGGS_DIR):
            os.makedirs(APP_EGGS_DIR)

        self._iters = {}

        self.executable_path = None
        self.conf_path = None
        self.python_paths = []

        self._setup_widgets()

    #
    #  Zeroconf Listener
    #

    def remove_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        # FIXME: How to remove the service when info is None?
        if info is None:
            return

        key = (info.address, info.port)
        if key in self._iters:
            self.store.remove(self._iters[key].pop())

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)

        server_address = 'http://%s:%s' % (
            socket.inet_ntoa(info.address), info.port)
        args = info.properties

        itr = self.store.append([server_address, args])
        self._iters[(info.address, info.port)] = itr

        if not self.selection.get_selected()[1]:
            self.selection.select_iter(itr)

    #
    #  Private
    #

    def _setup_widgets(self):
        vbox = gtk.VBox(spacing=6)

        self.store = gtk.ListStore(str, object)
        self.treeview = gtk.TreeView(self.store)

        self.server_column = gtk.TreeViewColumn(_("Server"))
        self.cell = gtk.CellRendererText()
        self.server_column.pack_start(self.cell, True)
        self.server_column.add_attribute(self.cell, 'text', 0)

        self.treeview.append_column(self.server_column)
        self.selection = self.treeview.get_selection()
        self.selection.connect('changed', self._on_treeview_selection__changed)
        vbox.pack_start(self.treeview, expand=True)

        self.username = gtk.Entry()
        username_hbox = gtk.HBox(spacing=6)
        username_hbox.pack_start(gtk.Label(_("Username:")), expand=False)
        self.username.connect('activate', self._on_username__activate)
        self.username.connect('changed', self._on_username__changed)
        username_hbox.pack_start(self.username, expand=True)
        vbox.pack_start(username_hbox, expand=False)

        self.password = gtk.Entry()
        self.password.set_property('visibility', False)
        password_hbox = gtk.HBox(spacing=6)
        password_hbox.pack_start(gtk.Label(_("Password:")), expand=False)
        self.password.connect('activate', self._on_password__activate)
        password_hbox.pack_start(self.password, expand=True)
        vbox.pack_start(password_hbox, expand=False)

        self.login_btn = gtk.Button(_("Start"))
        self.login_btn.connect('activate', self._on_login_btn__activate)
        vbox.pack_start(self.login_btn, expand=False)
        self.login_btn.set_sensitive(False)

        alignment = gtk.Alignment(0.5, 0.5, 1.0, 1.0)
        alignment.set_padding(6, 6, 6, 6)
        alignment.add(vbox)

        self.resize(400, 300)
        self.add(alignment)

        self.username.grab_focus()

    def _update_widgets(self):
        model, titer = self.selection.get_selected()
        self.login_btn.set_sensitive(
            bool(titer and self.username.get_text()))

    def _download_eggs(self, server_address, options):
        opener = self._get_opener(server_address)

        with io.BytesIO() as f:
            tmp = opener.open('%s/login' % (server_address, ))
            f.write(tmp.read())
            f.seek(0)
            config = ConfigParser.ConfigParser()
            config.readfp(f)

        parsed = urlparse.urlparse(server_address)
        address = parsed.netloc.split(':')[0]
        config.set('General', 'serveraddress', address)
        config.set('General', 'serverport', parsed.port or SERVER_XMLRPC_PORT)

        if not config.get('Database', 'address'):
            # If there's no database address, it means the server is running on
            # the same computer as the database. Set it on the config file, but
            # only if the client is not running on the same computer as the server
            for iface in netifaces.interfaces():
                addresses = [
                    i['addr'] for i in
                    netifaces.ifaddresses(iface).setdefault(
                        netifaces.AF_INET, [{'addr': None}])]
                if address in addresses:
                    break
            else:
                config.set('Database', 'address', address)

        with tempfile.NamedTemporaryFile(delete=False) as f:
            config.write(f)
            self.conf_path = f.name

        md5sums = {}
        tmp = opener.open('%s/md5sum' % (server_address, ))
        for line in tmp.read().split('\n'):
            if not line:
                continue
            egg, md5sum = line.split(':')
            md5sums[egg] = md5sum

        tmp.close()

        for egg in SERVER_EGGS:
            egg_path = os.path.join(APP_EGGS_DIR, egg)
            if not self._check_egg(egg_path, md5sums[egg]):
                with open(egg_path, 'wb') as f:
                    tmp = opener.open('%s/eggs/%s' % (server_address, egg))
                    f.write(tmp.read())
                    tmp.close()

            assert self._check_egg(egg_path, md5sums[egg])

            self.python_paths.append(egg_path)
            if egg == SERVER_EXECUTABLE_EGG:
                self.executable_path = egg_path

        return True

    def _get_opener(self, server_address):
        passman = urllib2.HTTPPasswordMgrWithDefaultRealm()
        passman.add_password(None, server_address,
                             self.username.get_text(),
                             hashlib.md5(self.password.get_text()).hexdigest())
        authhandler = urllib2.HTTPBasicAuthHandler(passman)
        return urllib2.build_opener(authhandler)

    def _check_egg(self, egg_path, md5sum):
        if not os.path.exists(egg_path):
            return False

        md5 = hashlib.md5()
        with open(egg_path, 'rb') as f:
            for chunk in iter(lambda: f.read(md5.block_size), b''):
                md5.update(chunk)

        return md5.hexdigest() == md5sum

    def _start(self):
        model, titer = self.treeview.get_selection().get_selected()
        if not titer:
            return

        if not self._download_eggs(
                model.get_value(titer, 0), model.get_value(titer, 1)):
            return

        self.hide()
        gtk.main_quit()

    #
    #  Callbacks
    #

    def _on_treeview_selection__changed(self, selection):
        self._update_widgets()

    def _on_username__changed(self, entry):
        self._update_widgets()

    def _on_username__activate(self, entry):
        self.password.grab_focus()

    def _on_password__activate(self, entry):
        self._start()

    def _on_login_btn__activate(self, button):
        self._start()


def main(args):
    try:
        # FIXME: Maybe we should not use zeroconf and instead implement
        # our own avahi browser.
        zeroconf = Zeroconf()
        client = _StoqClient()
        client.show_all()
        ServiceBrowser(zeroconf, '%s.local.' % (AVAHI_STYPE, ), client)
        gtk.gdk.threads_init()
        gtk.main()
    finally:
        zeroconf.close()

    env = os.environ.copy()
    env['PYTHONPATH'] = ':'.join(
        client.python_paths + [env.get('PYTHONPATH', '')])

    args = [sys.executable, client.executable_path, '-f', client.conf_path]
    os.execve(args[0], args, env)
