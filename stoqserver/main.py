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

import atexit
import logging
from logging.handlers import SysLogHandler
import multiprocessing
import optparse
import os
import platform
import signal
import socket
import sys
import time
import xmlrpc.client

import stoq
from kiwi.component import provide_utility
from stoq.lib.options import get_option_parser
from stoq.lib.startup import setup
from stoqlib.api import api
from stoqlib.database.interfaces import ICurrentBranch
from stoqlib.database.settings import db_settings
from stoqlib.lib.appinfo import AppInfo
from stoqlib.lib.configparser import get_config
from stoqlib.lib.interfaces import IAppInfo
from stoqlib.lib.osutils import get_application_dir

import stoqserver
from .common import SERVER_XMLRPC_PORT
from .taskmanager import Worker
from .tasks import backup_database, restore_database, backup_status, start_flask_server
from .sentry import setup_sentry

logger = logging.getLogger(__name__)

_LOGGING_FORMAT = '%(asctime)-15s %(name)-35s %(levelname)-8s %(message)s'
_LOGGING_DATE_FORMAT = '%y-%m-%d %H:%M:%S'


class _Tee(object):

    def __init__(self, *files):
        self._files = files

    def write(self, string):
        for f in self._files:
            f.write(string)
            f.flush()

    def flush(self):
        for f in self._files:
            f.flush()


def _windows_fixes():
    executable = os.path.realpath(os.path.abspath(sys.executable))
    root = os.path.dirname(executable)

    # Indicate the cert.pem location so requests can use it on verify
    # From: http://stackoverflow.com/a/33334042
    import requests
    requests.utils.DEFAULT_CA_BUNDLE_PATH = os.path.join(root, 'cacert.pem')


def setup_stoq(register_station=False, name='stoqserver',
               version=stoqserver.version_str, options=None):
    info = AppInfo()
    info.set('name', name)
    info.set('version', version)
    info.set('ver', version)
    provide_utility(IAppInfo, info, replace=True)

    setup(config=get_config(), options=options, register_station=register_station,
          check_schema=True, load_plugins=True)

    # This is needed for api calls that requires the current branch set,
    # e.g. Sale.confirm
    main_company = api.sysparam.get_object(
        api.get_default_store(), 'MAIN_COMPANY')
    provide_utility(ICurrentBranch, main_company, replace=True)


def setup_logging(app_name='stoq-server'):
    # Note that kiwi creates another StreamHandler. If there is any indirect import from kiwi.log,
    # some lines will be duplicated.
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s %(name)s [%(processName)s(%(process)s)]: %(levelname)s - %(message)s')
    ch.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(ch)

    handler = SysLogHandler(address='/dev/log')
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(app_name + '[%(process)d]: %(processName)s - %(message)s'))
    root.addHandler(handler)

    if platform.system() == 'Windows':
        # FIXME: We need some kind of log rotation here
        log_dir = os.path.join(get_application_dir(), 'stoqserver-logs')
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        log_filename = os.path.join(log_dir, multiprocessing.current_process().name)
        stdout_file = open(log_filename + '-stdout.txt', 'a')
        # On windows, since it is not supervisor that is handling the logs,
        # and some places/plugins will do logging by printing info to stdout
        # (e.g. conector), we need to log them somewhere
        sys.stdout = _Tee(sys.stdout, stdout_file)
        sys.stderr = _Tee(sys.stderr, stdout_file)

        hdlr = logging.FileHandler(log_filename + '.txt')
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        hdlr.setFormatter(formatter)
        root.addHandler(hdlr)


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

        print('Usage: stoqserver <command> [<args>]')
        print()
        print('Available commands:')

        for name, doc in cmds:
            print('  %s  %s' % (name.ljust(max_len), doc))

    def cmd_run(self, options, *args):
        """Run the server daemon"""
        setup_logging()

        while True:
            # If the server was initialized before a stoq database exists,
            # don't let the process die. Instead, wait until the configuration
            # is valid so we can really start.
            try:
                setup_stoq()
            # FIXME: We should not be excepting BaseException, but there are
            # some issues (e.g. postgresql not installed) that will raise an
            # exception that inherit from BaseException directly. We need this
            # to make sure we will wait until the database is
            # installed, configured and ready.
            except BaseException as e:
                logging.warning("Unable to initialize Stoq: %s\n"
                                "Trying again in 10 minutes...", str(e))
                time.sleep(600)
            else:
                break

        with api.new_store() as store:
            query = ("SELECT client_addr FROM pg_stat_activity "
                     "WHERE application_name LIKE ? AND "
                     "      application_name NOT LIKE ? AND "
                     "      datname = ? "
                     "LIMIT 1")
            params = ['stoqserver%', '%%%d' % (os.getpid()),
                      str(db_settings.dbname)]
            res = store.execute(query, params=params).get_one()
            if res is not None:
                print(("There's already a Stoq Server running in this "
                       "database on address %s" % (res[0], )))
                return 1

        if not api.sysparam.get_string('USER_HASH'):
            print("No USER_HASH found for this installation")
            return 1

        worker = Worker()
        atexit.register(lambda: worker.stop())

        def _exit(*args):
            worker.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _exit)
        signal.signal(signal.SIGINT, _exit)
        if platform.system() != 'Windows':
            signal.signal(signal.SIGQUIT, _exit)

        worker.run()

    def cmd_flask(self, options, *args):
        """Run the server daemon"""
        setup_stoq(register_station=True, name='stoqflask', version=stoq.version, options=options)
        setup_logging('stoq-flask')

        def _exit(*args):
            sys.exit(0)

        signal.signal(signal.SIGTERM, _exit)
        signal.signal(signal.SIGINT, _exit)
        if platform.system() != 'Windows':
            signal.signal(signal.SIGQUIT, _exit)

        start_flask_server(options.debug, options.multiclient)

    def opt_flask(self, parser, group):
        """Options for command flask"""
        group.add_option('', '--multiclient',
                         action='store_true',
                         dest='multiclient',
                         help="Make flask API prepared to serve multiple clients")

    def cmd_backup_database(self, options, *args):
        """Backup the Stoq database"""
        setup_stoq()
        setup_logging()
        return backup_database(full=options.full)

    def opt_backup_database(self, parser, group):
        group.add_option('', '--full',
                         action='store_true',
                         default=False,
                         dest='full')

    def cmd_restore_backup(self, options, *args):
        """Restore the Stoq database"""
        setup_logging()
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
        setup_stoq()
        setup_logging()
        return backup_status(user_hash=options.user_hash)

    def opt_backup_status(self, parser, group):
        group.add_option('', '--user-hash',
                         action='store',
                         dest='user_hash')

    def cmd_exec_action(self, options, *args):
        """Run an action on an already running server instance"""
        setup_logging()

        cmd = args[0]
        cmd_args = args[1:]
        config = get_config()
        port = (options.server_port or
                config.get('General', 'serverport') or
                SERVER_XMLRPC_PORT)
        address = (options.server_address or
                   config.get('General', 'serveraddress') or
                   '127.0.0.1')

        remote = xmlrpc.client.ServerProxy(
            'http://%s:%s/XMLRPC' % (address, port), allow_none=True)
        # Backup commands can take a while to execute. Wait at least 10 minutes
        # before timing out so we can give a better feedback to the user
        if cmd.startswith('backup'):
            socket.setdefaulttimeout(60 * 10)

        print("Executing '%s' on server. This might take a while..." % (cmd, ))
        try:
            print(getattr(remote, cmd)(*cmd_args))
        except socket.timeout:
            print("Connection timed out. The action may still be executing...")
            return 1
        except xmlrpc.client.Fault as e:
            print("Server fault (%s): %s" % (e.faultCode, e.faultString))
            return 1
        except Exception as e:
            print("Could not send action to server: %s" % (str(e), ))
            return 1

    def opt_exec_action(self, parser, group):
        group.add_option('', '--server-address',
                         action='store',
                         dest='server_address')
        group.add_option('', '--server-port',
                         action='store',
                         dest='server_port')


def main(args):
    if platform.system() == 'Windows':
        _windows_fixes()

    handler = StoqServerCmdHandler()
    if not args:
        handler.cmd_help()
        return 1

    cmd = args[0]
    args = args[1:]

    parser = get_option_parser()
    handler.add_options(cmd, parser)
    options, args = parser.parse_args(args)
    setup_sentry(options)

    return handler.run_cmd(cmd, options, *args)
