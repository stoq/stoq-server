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

import xmlrpc.server
import logging
import threading
import xmlrpc.client

import stoq
from stoqlib.lib.configparser import get_config

import stoqserver

logger = logging.getLogger(__name__)


class _RequestHandler(xmlrpc.server.SimpleXMLRPCRequestHandler):
    # Keep compatibility with old rpc path
    rpc_paths = ('/XMLRPC', )


class XMLRPCServer(object):

    def __init__(self, pipe_conn):
        self._pipe_conn = pipe_conn

    #
    #  Methods
    #

    def ping(self):
        logger.info("XMLRPC: ping")
        return "pong"

    def version(self):
        logger.info("XMLRPC: version")
        return stoqserver.version_str

    def stoq_version(self):
        logger.info("XMLRPC: stoq_version")
        return stoq.version

    def restart(self):
        logger.info("XMLRPC: restart")
        t = threading.Timer(1.0, self._run_action, args=('restart', ))
        t.start()
        return "Restart command sent..."

    def get_backup_key(self):
        config = get_config()
        return config.get('Backup', 'key')

    def set_backup_key(self, key):
        config = get_config()
        config.set('Backup', 'key', key)
        config.flush()
        # Restart stoqserver so the backup key will take effect immediately
        self.restart()
        return "Backup key set successfully"

    def pause_tasks(self):
        return self._run_action('pause_tasks')

    def resume_tasks(self):
        return self._run_action('resume_tasks')

    def htsql_query(self, query):
        return self._run_action('htsql_query', query)

    def backup_database(self):
        return self._run_action('backup_database')

    def backup_status(self, user_hash=None):
        return self._run_action('backup_status', user_hash)

    def backup_restore(self, user_hash, time=None):
        return self._run_action('backup_restore', user_hash, time)

    def plugin_action(self, plugin_name, task_name, action, *args):
        return self._run_action(
            'plugin_action', plugin_name, task_name, action, args)

    def register_link(self, pin):
        return self._run_action('register_link', pin)

    def install_plugin(self, plugin_name):
        return self._run_action('install_plugin', plugin_name)

    #
    #  Private
    #

    def _run_action(self, action, *args):
        logger.info("XMLRPC: action %s(%s)",
                    action, ', '.join('"%s"' % (a, ) for a in args))
        self._pipe_conn.send((action, ) + args)
        retval, msg = self._pipe_conn.recv()
        if not retval:
            raise xmlrpc.client.Fault(32000, msg)
        return msg


def run_xmlrpcserver(pipe_conn, port):
    server = xmlrpc.server.SimpleXMLRPCServer(
        ('', port), requestHandler=_RequestHandler, allow_none=True)
    server.register_introspection_functions()
    server.register_instance(XMLRPCServer(pipe_conn))
    server.serve_forever()
