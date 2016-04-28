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

import stoq
from stoqlib.net.xmlrpcservice import XMLRPCResource
from twisted.internet import reactor
from twisted.web import xmlrpc

import stoqserver

logger = logging.getLogger(__name__)


class ServerXMLRPCResource(XMLRPCResource):

    def __init__(self, root, pipe_conn):
        self._pipe_conn = pipe_conn
        XMLRPCResource.__init__(self, root)

    def xmlrpc_ping(self):
        return "Server is alive and running..."

    def xmlrpc_version(self):
        return stoqserver.version_str

    def xmlrpc_stoq_version(self):
        return stoq.version

    def xmlrpc_restart(self):
        reactor.callLater(0.1, self._pipe_conn.send, ('restart', ))
        return "Restart command sent..."

    def xmlrpc_pause_tasks(self):
        self._pipe_conn.send(('pause_tasks', ))
        retval, msg = self._pipe_conn.recv()
        if not retval:
            raise xmlrpc.Fault(32000, msg)

        return msg

    def xmlrpc_resume_tasks(self):
        self._pipe_conn.send(('resume_tasks', ))
        retval, msg = self._pipe_conn.recv()
        if not retval:
            raise xmlrpc.Fault(32000, msg)

        return msg

    def xmlrpc_htsql_query(self, query):
        self._pipe_conn.send(('htsql_query', query))
        retval, msg = self._pipe_conn.recv()
        if not retval:
            raise xmlrpc.Fault(32000, msg)

        return msg

    def xmlrpc_backup_status(self, user_hash=None):
        self._pipe_conn.send(('backup_status', user_hash))
        retval, msg = self._pipe_conn.recv()
        if not retval:
            raise xmlrpc.Fault(32000, msg)

        return msg

    def xmlrpc_backup_restore(self, user_hash, time=None):
        self._pipe_conn.send(('backup_restore', user_hash, time))
        retval, msg = self._pipe_conn.recv()
        if not retval:
            raise xmlrpc.Fault(32000, msg)

        return msg

    def xmlrpc_plugin_action(self, plugin_name, task_name, action, *args):
        self._pipe_conn.send(('plugin_action',
                             plugin_name, task_name, action, args))
        retval, msg = self._pipe_conn.recv()
        if not retval:
            raise xmlrpc.Fault(32000, msg)

        return msg
