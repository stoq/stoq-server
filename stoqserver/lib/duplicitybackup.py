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

import pkg_resources

from stoqlib.lib.process import Process, PIPE
from stoqlib.lib.threadutils import threadit


def _watch_fd(fd):
    for l in iter(fd.readline, ''):
        print(l)


def _run(cmd, *args):
    script = pkg_resources.resource_filename('stoqserver', 'scripts/duplicitybackup.py')
    p = Process(['python2', script, cmd] + list(args), stdout=PIPE, stderr=PIPE)
    threadit(_watch_fd, p.stdout)
    threadit(_watch_fd, p.stderr)
    p.wait()
    return p.returncode == 0


def restore(restore_dir, user_hash, time=None):
    return _run('restore', restore_dir, user_hash, time or '')


def backup(backup_dir, full=False):
    return _run('backup', backup_dir, '1' if full else '0')


def status(user_hash=None):
    return _run('status', user_hash or '')
