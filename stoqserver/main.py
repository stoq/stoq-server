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

import logging
import optparse
import signal
import sys
import xmlrpclib

from stoq.lib.options import get_option_parser
from stoq.lib.startup import setup
from stoqlib.lib.configparser import StoqConfig, register_config
from stoqlib.lib.configparser import get_config

from stoqserver.common import APP_CONF_FILE, SERVER_XMLRPC_PORT
from stoqserver.taskmanager import TaskManager
from stoqserver.tasks import backup_database, restore_database, backup_status


class StoqServerCmdHandler(object):

    #
    #  Public API
    #

    def run_cmd(self, cmd, options, *args):
        meth = getattr(self, 'cmd_' + cmd, None)
        if not meth:
            self.cmd_help(options, *args)
            return 1
        return meth(options, *args)

    def add_options(self, cmd, parser):
        meth = getattr(self, 'opt_' + cmd, None)
        if not meth:
            return

        group = optparse.OptionGroup(parser, '%s options' % cmd)
        meth(parser, group)
        parser.add_option_group(group)

    #
    #  Private
    #

    def _setup_stoq(self):
        # FIXME: Maybe we should check_schema and load plugins here?
        setup(config=get_config(), options=None, register_station=False,
              check_schema=False, load_plugins=True)

    def _setup_logging(self):
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)

        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(ch)

    #
    #  Commands
    #

    def cmd_help(self, *args):
        """Show available commands help"""
        cmds = []
        max_len = 0

        for attr in dir(self):
            if not attr.startswith('cmd_'):
                continue

            name = attr[4:]
            doc = getattr(self, attr).__doc__ or ''
            max_len = max(max_len, len(name))
            cmds.append((name, doc.split(r'\n')[0]))

        print 'Usage: stoqserver <command> [<args>]'
        print
        print 'Available commands:'

        for name, doc in cmds:
            print '  %s  %s' % (name.ljust(max_len), doc)

    def cmd_run(self, options, *args):
        """Run the server daemon"""
        self._setup_stoq()
        self._setup_logging()
        manager = TaskManager()

        def _exit(*args):
            manager.stop(close_xmlrpc=True)
            sys.exit(0)

        signal.signal(signal.SIGTERM, _exit)
        signal.signal(signal.SIGINT, _exit)
        manager.run()

    def cmd_backup_database(self, options, *args):
        """Backup the Stoq database"""
        self._setup_stoq()
        self._setup_logging()
        return backup_database(full=options.full)

    def opt_backup_database(self, parser, group):
        group.add_option('', '--full',
                         action='store_true',
                         default=False,
                         dest='full')

    def cmd_restore_backup(self, options, *args):
        """Restore the Stoq database"""
        self._setup_logging()
        return restore_database(user_hash=options.user_hash,
                                time=options.time)

    def opt_restore_backup(self, parser, group):
        group.add_option('', '--user-hash',
                         action='store',
                         dest='user_hash')
        group.add_option('', '--time',
                         action='store',
                         dest='time')

    def cmd_backup_status(self, options, *args):
        """Get the status of the current backups"""
        self._setup_stoq()
        self._setup_logging()
        return backup_status(user_hash=options.user_hash)

    def opt_backup_status(self, parser, group):
        group.add_option('', '--user-hash',
                         action='store',
                         dest='user_hash')

    def cmd_exec_action(self, options, *args):
        """Run an action on an already running server instance"""
        self._setup_logging()

        cmd = args[0]
        cmd_args = args[1:]
        config = get_config()
        port = (options.server_port or
                config.get('General', 'serverport') or
                SERVER_XMLRPC_PORT)
        address = (options.server_address or
                   config.get('General', 'serveraddress') or
                   '127.0.0.1')

        remote = xmlrpclib.ServerProxy(
            'http://%s:%s/XMLRPC' % (address, port), allow_none=True)
        try:
            print getattr(remote, cmd)(*cmd_args)
        except xmlrpclib.Fault as e:
            print "Server fault (%s): %s" % (e.faultCode, e.faultString)
            return 1
        except Exception as e:
            print "Could not send action to server: %s" % (str(e), )
            return 1

    def opt_exec_action(self, parser, group):
        group.add_option('', '--server-address',
                         action='store',
                         dest='server_address')
        group.add_option('', '--server-port',
                         action='store',
                         dest='server_port')


def main(args):
    handler = StoqServerCmdHandler()
    if not args:
        handler.cmd_help()
        return 1

    cmd = args[0]
    args = args[1:]

    parser = get_option_parser()
    handler.add_options(cmd, parser)
    options, args = parser.parse_args(args)

    config = StoqConfig()
    filename = (options.filename
                if options.load_config and options.filename else
                APP_CONF_FILE)
    config.load(filename)
    # FIXME: This is called only when register_station=True. Without
    # this, db_settings would not be updated. We should fix it on Stoq
    config.get_settings()
    register_config(config)

    return handler.run_cmd(cmd, options, *args)
