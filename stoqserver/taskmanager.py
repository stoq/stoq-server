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

import io
import logging
import multiprocessing
import os
import signal
import sys
import urllib

import stoq
from stoqlib.database.runtime import get_default_store, set_default_store
from stoqlib.database.settings import db_settings
from stoqlib.lib.pluginmanager import get_plugin_manager

from stoqserver.tasks import (backup_status, restore_database,
                              start_xmlrpc_server, start_server,
                              start_backup_scheduler,
                              start_rtc)

logger = logging.getLogger(__name__)


class _Task(multiprocessing.Process):

    def __init__(self, func, *args, **kwargs):
        super(_Task, self).__init__()

        self.func = func
        self._func_args = args
        self._func_kwargs = kwargs
        self.daemon = True

    #
    #  multiprocessing.Process
    #

    def run(self):
        os.setpgrp()
        # Workaround a python issue where multiprocessing/threading will not
        # use the modified sys.excepthook: https://bugs.python.org/issue1230540
        try:
            self.func(*self._func_args, **self._func_kwargs)
        except Exception:
            sys.excepthook(*sys.exc_info())


class TaskManager(object):

    PLUGIN_ACTION_TIMEOUT = 60

    def __init__(self):
        self._paused = False
        self._xmlrpc_conn1, self._xmlrpc_conn2 = multiprocessing.Pipe(True)
        self._plugins_pipes = {}

    #
    #  Public API
    #

    def run(self):
        self._start_tasks()
        while True:
            action = self._xmlrpc_conn1.recv()
            meth = getattr(self, 'action_' + action[0])
            assert meth, "Action handler for %s not found" % (action[0], )
            self._xmlrpc_conn1.send(meth(*action[1:]))

    def stop(self, close_xmlrpc=False):
        self._plugins_pipes.clear()

        for p in self._get_children():
            if not close_xmlrpc and p.func is start_xmlrpc_server:
                continue
            if not p.is_alive():
                continue

            pgid = os.getpgid(p.pid)
            os.kill(p.pid, signal.SIGTERM)
            # Give it 2 seconds to exit. If that doesn't happen, force
            # its termination
            p.join(2)
            if p.is_alive():
                p.terminate()

            # Try to kill any remaining child process that refused to
            # terminate (e.g. wrtc client)
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass

    #
    #  Actions
    #

    def action_restart(self):
        logger.info("Restarting the process as requested...")

        self.stop(close_xmlrpc=True)
        # execv will restart the process and finish this one
        os.execv(sys.argv[0], sys.argv)

    def action_pause_tasks(self):
        logger.info("Pausing the tasks as requested...")

        if not self._paused:
            self.stop()
            # None will make the default store be closed
            set_default_store(None)
            self._paused = True

        return True, "Tasks paused successfully"

    def action_resume_tasks(self):
        logger.info("Resuming the tasks as requested..")

        if self._paused:
            # get_default_store will recreate it (since we closed it above)
            get_default_store()
            self._start_tasks()
            self._paused = False

        return True, "Tasks resumed successfully"

    def action_htsql_query(self, query):
        """Executes a HTSQL Query"""
        try:
            from htsql.core.fmt.emit import emit
            from htsql.core.error import Error as HTSQL_Error
            from htsql import HTSQL
        except ImportError:
            return False, "HTSQL installation not found"

        # Resolve RDBMSs to their respective HTSQL engines
        engines = {
            'postgres': 'pgsql',
            'sqlite': 'sqlite',
            'mysql': 'mysql',
            'oracle': 'oracle',
            'mssql': 'mssql',
        }

        if db_settings.password:
            password = ":" + urllib.quote_plus(db_settings.password)
        else:
            password = ""
        authority = '%s%s@%s:%s' % (
            db_settings.username, password, db_settings.address,
            db_settings.port)

        uri = '%s://%s/%s' % (
            engines[db_settings.rdbms], authority, db_settings.dbname)

        exts = [{
            'tweak.override': {
                'globals': {
                    'between($date, $start, $end)': '($date >= $start & $date <= $end)',
                    'trunc_hour($d)': 'datetime(year($d), month($d), day($d), hour($d))',
                    'trunc_day($d)': 'datetime(year($d), month($d), day($d))',
                    'trunc_month($d)': 'datetime(year($d), month($d), 01)',
                }},
        }]

        # FIXME: This is to support old stoq versions, which didn't have
        # a UNIQUE constraint on product.sellable_id column
        if stoq.stoq_version < (1, 10, 90):
            exts[0]['tweak.override']['unique_keys'] = 'product(sellable_id)'

        store = HTSQL(uri, *exts)

        try:
            rows = store.produce(query)
        except HTSQL_Error as e:
            return False, str(e)

        with store:
            json = ''.join(emit('x-htsql/json', rows))

        return True, json

    def action_backup_status(self, user_hash=None):
        with io.StringIO() as f:
            duplicity_log = logging.getLogger("duplicity")
            handler = logging.StreamHandler(f)
            duplicity_log.addHandler(handler)

            try:
                backup_status(user_hash=user_hash)
            except Exception as e:
                retval = False
                msg = str(e)
            else:
                retval = True
                msg = f.getvalue()

            duplicity_log.removeHandler(handler)

        return retval, msg

    def action_backup_restore(self, user_hash, time=None):
        self.stop()

        try:
            restore_database(user_hash=user_hash, time=time)
        except Exception as e:
            retval = False
            msg = str(e)
        else:
            retval = True
            msg = "Restore finished"

        self._start_tasks()
        return retval, msg

    def action_plugin_action(self, plugin_name, task_name, action, args):
        # FIXME: It would be better if the xmlrpc process could communicate
        # directly with the pipe, but we are not able to share them using
        # a shared dict. Try to find a way in the future
        try:
            pipe = self._plugins_pipes[(plugin_name, task_name)]
        except KeyError:
            return False, "Plugin %s not found" % (plugin_name, )
        else:
            # This is garbage from the previous timeout
            if pipe.poll():
                pipe.recv()

            pipe.send((action, args))
            if not pipe.poll(self.PLUGIN_ACTION_TIMEOUT):
                logger.warning("Plugin %s task %s action %s timed out",
                               plugin_name, task_name, action)
                return False, "Plugin action timed out"

            return pipe.recv()

    #
    #  Private
    #

    def _get_children(self):
        for child in multiprocessing.active_children():
            if not isinstance(child, _Task):
                continue
            yield child

    def _start_tasks(self):
        tasks = [
            _Task(start_backup_scheduler),
            _Task(start_server),
            _Task(start_rtc),
        ]
        if start_xmlrpc_server not in [t.func for t in
                                       self._get_children()]:
            tasks.append(_Task(start_xmlrpc_server, self._xmlrpc_conn2))

        manager = get_plugin_manager()
        for plugin_name in manager.installed_plugins_names:
            plugin = manager.get_plugin(plugin_name)
            if not hasattr(plugin, 'get_server_tasks'):
                continue

            # FIXME: Check that the plugin implements IPluginTask when
            # we Stoq 1.11 is released
            for plugin_task in plugin.get_server_tasks():
                task_name = plugin_task.name
                kwargs = {}
                if plugin_task.handle_actions:
                    conn1, conn2 = multiprocessing.Pipe(True)
                    self._plugins_pipes[(plugin_name, task_name)] = conn1
                    kwargs['pipe_connection'] = conn2

                tasks.append(_Task(plugin_task.start, **kwargs))

        for t in tasks:
            t.start()
