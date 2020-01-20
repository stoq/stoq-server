# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2020 Async Open Source <http://www.async.com.br>
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
# Author(s): Stoq Team <stoq-devel@async.com.br>
#

import logging

from gevent.lock import Semaphore

from stoqserver.app import is_multiclient

log = logging.getLogger(__name__)

printer_lock = Semaphore()


class LockFailedException(Exception):
    pass


class base_lock_decorator:
    """Decorator to handle pinpad access locking.

    This will make sure that only one callsite is using the sat at a time.
    """
    lock = None

    def __init__(self, block):
        assert self.lock is not None
        self._block = block

    def __call__(self, func):

        def new_func(*args, **kwargs):
            if not is_multiclient:
                # Only acquire the lock if running in single client mode. Multi client mode cannot
                # have any locks in the requests
                acquired = self.lock.acquire(blocking=self._block)
                if not acquired:
                    log.info('Failed %s in func %s', type(self).__name__, func)
                    raise LockFailedException()

            try:
                return func(*args, **kwargs)
            finally:
                self.lock.release()

        return new_func


class lock_pinpad(base_lock_decorator):
    lock = Semaphore()


class lock_sat(base_lock_decorator):
    lock = Semaphore()


def lock_printer(func):
    """Decorator to handle printer access locking.

    This will make sure that only one callsite is using the printer at a time.
    """
    def new_func(*args, **kwargs):

        if not is_multiclient:
            if printer_lock.locked():
                log.info('Waiting printer lock release in func %s', func)
            # Only acquire the lock if running in single client mode. Multi client mode cannot
            # have any locks in the requests
            printer_lock.acquire()

        try:
            return func(*args, **kwargs)
        finally:
            printer_lock.release()

    return new_func
