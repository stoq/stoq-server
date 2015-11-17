# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2014 Async Open Source <http://www.async.com.br>
## All rights reserved
##

from stoq.lib.options import get_option_parser
from stoq.lib.startup import setup
from stoqlib.lib.configparser import StoqConfig, get_config, register_config
from stoqlib.lib.daemonutils import DaemonManager
from twisted.internet import reactor

from stoqserver.common import SERVER_DAEMON_PORT, APP_CONF_FILE
from stoqserver.server import StoqServer
from stoqserver.tasks import backup_database, restore_database


class StoqServerCmdHandler(object):

    #
    #  Public API
    #

    def run_cmd(self, cmd):
        meth = getattr(self, 'cmd_' + cmd, None)
        if not meth:
            self.cmd_help()
            return 1
        return meth()

    #
    #  Commands
    #

    def cmd_help(self):
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

    def cmd_run(self):
        """Run the server daemon"""
        config = get_config()

        stoq_server = StoqServer()
        reactor.callWhenRunning(stoq_server.start)
        reactor.addSystemEventTrigger('before', 'shutdown', stoq_server.stop)

        port = config.get('General', 'serverport') or SERVER_DAEMON_PORT
        dm = DaemonManager(port=port and int(port))
        reactor.callWhenRunning(dm.start)
        reactor.addSystemEventTrigger('before', 'shutdown', dm.stop)

        try:
            reactor.run()
        except KeyboardInterrupt:
            reactor.stop()

    def cmd_database_backup(self):
        """Backup the Stoq database"""
        return backup_database()

    def cmd_database_restore(self):
        """Restore the Stoq database"""
        return restore_database()


def main(args):
    handler = StoqServerCmdHandler()
    if not args:
        handler.cmd_help()
        return 1

    cmd = args[0]
    args = args[1:]

    parser = get_option_parser()
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

    # FIXME: Maybe we should check_schema and load plugins here?
    setup(config=config, options=options, register_station=False,
          check_schema=False, load_plugins=False)

    handler.run_cmd(cmd)
