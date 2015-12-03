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

import functools
import os
import signal

from twisted.internet import reactor


def reactor_handler(f):
    def _sigterm_handler(_signo, _stack_frame):
        if reactor.running:
            reactor.stop()
        os._exit(0)

    @functools.wraps(f)
    def wrapper(*args, **kwds):
        # Ignore SIGINT to avoid it being captured in the child process
        # when pressing ctrl+c on the terminal to close the server
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, _sigterm_handler)
        f(*args, **kwds)
        reactor.run(False)

    return wrapper
