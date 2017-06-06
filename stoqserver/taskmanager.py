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
import platform
import signal
import sys
import threading
import time
import urllib.request
import urllib.parse
import urllib.error

import requests
from stoqlib.api import api
from stoqlib.database.runtime import get_default_store, set_default_store
from stoqlib.lib.pluginmanager import PluginError, get_plugin_manager
from stoqlib.lib.webservice import WebService
from stoqlib.net.socketutils import get_random_port

from stoqserver.tasks import (backup_status, restore_database, backup_database,
                              start_plugins_update_scheduler,
                              start_xmlrpc_server, start_server,
                              start_backup_scheduler,
                              start_rtc, start_htsql)

logger = logging.getLogger(__name__)
_executable = os.path.realpath(os.path.abspath(sys.executable))
_root = os.path.dirname(_executable)
_is_windows = platform.system() == 'Windows'


def _get_plugin_task_name(plugin_name, task_name):
    # Since all native tasks start with '_', do a lstrip to avoid
    # someone from "exploting" it and overwriting the task
    # with a possible "_foo" plugin.
    return '%s_%s' % (plugin_name.lstrip('_'), task_name)


class Task(multiprocessing.Process):
    """A task that will run on a separated process"""

    (STATUS_RUNNING,
     STATUS_STOPPED,
     STATUS_ERROR) = range(3)

    CHECK_PARENT_TIMEOUT = 10

    def __init__(self, name, func, *args, **kwargs):
        super(Task, self).__init__()

        self.name = name
        self.func = func
        self.errors = 0
        self._func_args = args
        self._func_kwargs = kwargs
        self._error_queue = None
        self.daemon = True

        # register_after_fork receives an object and a func,
        # passing self._after_fork would make us have to receive self
        # twice, which is the reason we use it this way.
        # Other python modules (e.g. Queue) does the same
        multiprocessing.util.register_after_fork(
            self, self.__class__._after_fork)

    #
    #  Public API
    #

    @property
    def status(self):
        """The task status."""
        if self.is_alive():
            return self.STATUS_RUNNING

        return self.STATUS_STOPPED if self.errors == 0 else self.STATUS_ERROR

    def clone(self):
        """Clone this task.

        Useful to restart this task when it dies/crashes, since
        `multiprocessing.Process` will not allow the same process
        to start twice.
        """
        obj = self.__class__(self.name, self.func,
                             *self._func_args, **self._func_kwargs)
        obj.errors = self.errors
        return obj

    def stop(self):
        """Stop the task.

        This will try to stop the task by sending a `signal.SIGTERM`
        to it. The tasks should intercept this signal if they need
        to do some cleanup before exiting.

        Note that, if the process takes more than 2 seconds to exit,
        the termination will be foced.
        """
        logger.info("Stopping task %s...", self.name)

        if not _is_windows:
            pgid = os.getpgid(self.pid)
        else:
            pgid = None

        os.kill(self.pid, signal.SIGTERM)
        # Give it 2 seconds to exit. If that doesn't happen, force
        # its termination
        self.join(2)
        if self.is_alive():
            logger.info("Task %s did not terminate with SIGTERM. Forcing "
                        "its termination now...", self.name)
            self.terminate()

        # Try to kill any remaining child process that refused to
        # terminate (e.g. wrtc client), but only on unix.
        # FIXME: how to do this on Windows?
        if not _is_windows:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass

    #
    #  multiprocessing.Process
    #

    def start(self, error_queue):
        self._error_queue = error_queue
        return super(Task, self).start()

    def run(self):
        # FIXME: parent pid is not supported on windows. Maybe we should
        # find a way for the task to check if the parent is alive in another
        # way in this case?
        if not _is_windows:
            os.setpgrp()
            self._ppid = os.getppid()
            t = threading.Thread(target=self._check_parent_running)
            t.daemon = True
            t.start()
        else:
            from stoqserver.main import (setup_stoq, setup_logging,
                                         setup_excepthook)
            # Do this as soon as possible so we can log any early traceback
            setup_excepthook()

            # Allow .pyd files to be imported from egg files
            import zipextimporter
            zipextimporter.install()

            import requests
            cacerts_path = os.path.join(_root, 'cacert.pem')
            requests.utils.DEFAULT_CA_BUNDLE_PATH = cacerts_path
            requests.adapters.DEFAULT_CA_BUNDLE_PATH = cacerts_path

            setup_stoq()
            setup_logging()

        if isinstance(self.func, tuple):
            # Windows
            plugin_name, task_name = self.func

            manager = get_plugin_manager()
            plugin = manager.get_plugin(plugin_name)
            for task in plugin.get_server_tasks():
                if task.name == task_name:
                    break
            else:
                raise AssertionError

            func = task.start
        else:
            func = self.func

        # Workaround a python issue where multiprocessing/threading will not
        # use the modified sys.excepthook: https://bugs.python.org/issue1230540
        try:
            func(*self._func_args, **self._func_kwargs)
        except Exception:
            sys.excepthook(*sys.exc_info())
            self._error_queue.put(self.name)

    #
    #  Private
    #

    def _after_fork(self):
        # Close the default store so any call to get_default_store
        # will create a new one directly in the forked process
        set_default_store(None)

    def _check_parent_running(self):
        while self.is_alive():
            # If the parent dies, ppid will change. In this case,
            # finalize this process. It shouldn't be running anymore.
            if os.getppid() != self._ppid:
                os.killpg(os.getpgid(self.pid), signal.SIGKILL)
                break
            time.sleep(self.CHECK_PARENT_TIMEOUT)


class TaskManager(threading.Thread):
    """Manager responsible for watching over the running tasks.

    This is responsible for starting/stopping the tasks, and also
    for restarting them if something unexpected happens to them.
    """

    BACKOFF_FACTOR = 2

    def __init__(self):
        super(TaskManager, self).__init__()

        self._tasks = {}
        self._timers = {}
        self._lock = threading.Lock()
        self._error_queue = multiprocessing.Queue()
        self.daemon = True

    #
    #  Public API
    #

    def run_task(self, task):
        """Run given task.

        Run the given task and watch for any error that might happen to it.
        """
        assert isinstance(task, Task)

        with self._lock:
            old_task = self._tasks.pop(task.name, None)
            if old_task and old_task.status == Task.STATUS_RUNNING:
                raise Exception("Task %s already running" % (task.name, ))

            # Stop any timer that was trying to restart a previously
            # added task with the same name
            timer = self._timers.pop(task.name, None)
            if timer is not None:
                timer.cancel()

            self._tasks[task.name] = task
            task.start(self._error_queue)

    def is_running(self, task_name):
        """Check if the task named *task_name* is running."""
        with self._lock:
            task = self._tasks.get(task_name, None)
            if task is None:
                return False

            return task.status == Task.STATUS_RUNNING

    def stop_tasks(self, exclude=None):
        """Stop the currently running tasks.

        :param exclude: an iterable of task names that shouldn't be stopped
        """
        exclude = exclude or []

        # Cancel any timer before the "for" bellow to avoid them restarting
        # a task that shouldn't be running anymore inside it
        for name, timer in self._timers.items():
            if name not in exclude:
                timer.cancel()

        with self._lock:
            for name, task in self._tasks.items():
                if name in exclude:
                    continue

                if task.status == Task.STATUS_RUNNING:
                    task.stop()

    #
    #  threading.Thread
    #

    def run(self):
        while True:
            name = self._error_queue.get()
            task = self._tasks[name]

            with self._lock:
                # With a backoff factor of 2, 12 errors would make the task
                # have to wait for 68 min before being restarted. This is
                # a good max value for a problematic task
                backoff_value = self.BACKOFF_FACTOR ** min(task.errors, 12)
                task.errors += 1
                logger.warning("Task %s crashed. Restarting again in %s seconds...",
                               name, backoff_value)
                timer = threading.Timer(backoff_value,
                                        self._restart_task, args=(name, ))
                self._timers[name] = timer
                timer.start()

    #
    #  Private
    #

    def _restart_task(self, task_name):
        with self._lock:
            task = self._tasks[task_name]
            # We can only restart the tasks on ERROR state. RUNNING were
            # probably restarted by the manager and STOPPED should not be
            # running anymore.
            if task.status != Task.STATUS_ERROR:
                return

            logger.info("Restarting task %s", task_name)
            new_task = task.clone()
            self._tasks[task_name] = new_task
            new_task.start(self._error_queue)

            # Remove the timer that executed this method from the timers dict
            try:
                del self._timers[task_name]
            except KeyError:
                pass


class Worker(object):
    """Worker responsible to run tasks and execute actions.

    The main object of this module, responsible for starting the native
    tasks, communicating with the xmlrpc server to execute actions and etc.
    """

    PLUGIN_ACTION_TIMEOUT = 3 * 60

    def __init__(self):
        # Indicates if we are doing a backup. This uses a piece of shared memory
        # so forked processes will all see the same value when updated
        self._doing_backup = multiprocessing.Value('i', 0)
        self._htsql_port = str(get_random_port())
        self._paused = False
        self._xmlrpc_conn1, self._xmlrpc_conn2 = multiprocessing.Pipe(True)
        self._updater_event = multiprocessing.Event()
        self._plugins_pipes = {}
        self._manager = TaskManager()

    #
    #  Public API
    #

    def run(self):
        """Start the worker.

        This will start the native tasks and start listening for
        any actions sent to the xmlrpc server.

        Note that this will block the code execution.
        """
        self._manager.start()
        self._start_tasks()

        while True:
            if self._updater_event.is_set():
                self.action_restart()

            # Poll for 10 seconds so we can do other things (e.g. see if the
            # updater event has been set) while there's nothing to read
            # on the pipe
            if self._xmlrpc_conn1.poll(10):
                # EOFError will be raised when the the other side of the
                # pipe closes the connection.
                try:
                    action = self._xmlrpc_conn1.recv()
                except EOFError:
                    break
                meth = getattr(self, 'action_' + action[0])
                assert meth, "Action handler for %s not found" % (action[0], )
                self._xmlrpc_conn1.send(meth(*action[1:]))

    def stop(self):
        """Stop the worker.

        This will stop all the tasks and also cause :meth:`.run` to
        stop running.
        """
        self._stop_tasks(stop_xmlrpc=True)

    #
    #  Actions
    #

    def action_restart(self):
        logger.info("Restarting the process as requested...")

        self.stop()
        if _is_windows:
            # On windows, the service is expecting an exit value of 10 to
            # restart us
            sys.exit(10)
        else:
            # execv will restart the process and finish this one
            os.execv(sys.argv[0], sys.argv)

    def action_pause_tasks(self):
        logger.info("Pausing the tasks as requested...")

        if not self._paused:
            self._stop_tasks()
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
            r = requests.get('http://127.0.0.1:{}/{}/:json'.format(
                self._htsql_port, query.strip('/')))
        except Exception as e:
            return False, str(e)

        if r.status_code != 200:
            return False, "htsql request failed with code " + str(r.status_code)

        return True, r.text

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

    def action_backup_database(self):
        try:
            backup_database()
        except Exception as e:
            return False, str(e)

        return True, "Backup finished"

    def action_backup_restore(self, user_hash, time=None):
        self._stop_tasks()

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

    def action_register_link(self, pin):
        url = urllib.parse.urljoin(WebService.API_SERVER,
                                   'api/lite/associate_instance')
        dbhash = api.sysparam.get_string('USER_HASH')

        rv = requests.post(url, data=dict(pin_code=pin, hash=dbhash))
        if rv.status_code != 200:
            return False, "Failed to associate the instance"

        data = rv.json()
        if data['status'] not in ['associated', 'already_associated']:
            return False, "Unexpected status returned: %s" % (data['status'], )

        # We should automatically enable online services registered users
        with api.new_store() as store:
            api.sysparam.set_bool(store, 'ONLINE_SERVICES', True)

        # If it is not premium, we are already done here
        if not data['is_premium']:
            return True, "Link registration successful"

        manager = get_plugin_manager()
        # Install conector plugin if it is not already installed
        if 'conector' not in manager.available_plugins_names:
            manager.download_plugin('conector')
        if 'conector' not in manager.installed_plugins_names:
            try:
                with api.new_store() as store:
                    manager.install_plugin(store, 'conector')
                manager.activate_plugin('conector')
            except PluginError as e:
                msg = "Failed to install conector plugin: %s" % (str(e), )
                return False, msg
            else:
                # Restart the tasks so it will get the ones from conector
                self._restart_tasks()

        return self.action_plugin_action(
            'conector', 'sync', 'get_credentials', [pin])

    def action_install_plugin(self, plugin_name):
        manager = get_plugin_manager()
        if (plugin_name not in manager.available_plugins_names or
                plugin_name in manager.egg_plugins_names):
            rv, msg = manager.download_plugin(plugin_name)
            if not rv:
                return False, msg

        if plugin_name not in manager.installed_plugins_names:
            with api.new_store() as store:
                try:
                    manager.install_plugin(store, plugin_name)
                except PluginError as err:
                    return False, str(err)

        return True, "Plugin installed/updated sucessfully"

    def action_plugin_action(self, plugin_name, task_name, action, args):
        name = _get_plugin_task_name(plugin_name, task_name)
        if not self._manager.is_running(name):
            return False, "Task %s from plugin %s not found" % (
                task_name, plugin_name)

        # FIXME: It would be better if the xmlrpc process could communicate
        # directly with the pipe, but we are not able to share them using
        # a shared dict. Try to find a way in the future
        try:
            pipe = self._plugins_pipes[name]
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

    def _restart_tasks(self):
        self._stop_tasks()
        self._start_tasks()

    def _stop_tasks(self, stop_xmlrpc=False):
        exclude = []
        if not stop_xmlrpc:
            exclude.append('_xmlrpc')
        self._manager.stop_tasks(exclude=exclude)

    def _start_tasks(self):
        tasks = [
            Task('_xmlrpc', start_xmlrpc_server, self._xmlrpc_conn2),
            Task('_updater', start_plugins_update_scheduler,
                 self._updater_event, self._doing_backup),
            Task('_backup', start_backup_scheduler, self._doing_backup),
        ]
        # TODO: Make those work on windows
        if not _is_windows:
            tasks.extend([
                Task('_htsql', start_htsql, self._htsql_port),
                Task('_server', start_server),
                Task('_rtc', start_rtc),
            ])

        manager = get_plugin_manager()
        for plugin_name in manager.installed_plugins_names:
            plugin = manager.get_plugin(plugin_name)
            if not hasattr(plugin, 'get_server_tasks'):
                continue

            # FIXME: Check that the plugin implements IPluginTask when
            # we Stoq 1.11 is released
            for plugin_task in plugin.get_server_tasks():
                task_name = plugin_task.name
                name = _get_plugin_task_name(plugin_name, task_name)
                if self._manager.is_running(name):
                    continue

                kwargs = {}
                if plugin_task.handle_actions:
                    conn1, conn2 = multiprocessing.Pipe(True)
                    self._plugins_pipes[name] = conn1
                    kwargs['pipe_connection'] = conn2

                # Since Windows has no os.fork, multiprocessing will actually
                # run the process again and pass the required objects by
                # pickling them. For some reason, passing a plugin task will
                # break some places, since the it will make some objects
                # like PluginManager be pickled/unpicled, and when unlicking
                # it will run its contructor again, but it should wait
                # to do that until we have configured the database.
                func = (plugin_name, task_name)

                tasks.append(Task(name, func, **kwargs))

        for task in tasks:
            if not self._manager.is_running(task.name):
                self._manager.run_task(task)

        # Close the default store because it not functioning anymore since the
        # forked processes closed its "clone", but open a new one later
        # or else Stoq will not be able to find this instance
        set_default_store(None)
        get_default_store()
