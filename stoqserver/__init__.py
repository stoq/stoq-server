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

import gettext
import importlib
import locale
import os
import platform

import pkg_resources


__version__ = (1, 6, 0)
version_str = '.'.join(str(i) for i in __version__)


def enable_translation(domain, root='..', enable_global=None):
    installed = importlib.util.find_spec(domain)
    if installed and pkg_resources.resource_exists(domain, 'locale'):
        localedir = pkg_resources.resource_filename(domain, 'locale')
    elif installed:
        localedir = None
    else:
        localedir = os.path.join(root, 'locale')

    gettext.bindtextdomain(domain, localedir)
    # For libglade, but only on non-win32 systems
    if hasattr(locale, 'bindtextdomain'):
        locale.bindtextdomain(domain, localedir)

    gettext.bind_textdomain_codeset(domain, 'utf-8')

    if enable_global:
        gettext.textdomain(domain)
        # For libglade, but only on non-win32 systems
        if hasattr(locale, 'textdomain'):
            locale.textdomain(domain)

    if platform.system() == 'Windows':
        from ctypes import cdll
        libintl = cdll.LoadLibrary("libintl-8.dll")
        libintl.bindtextdomain(domain, localedir)
        libintl.bind_textdomain_codeset(domain, 'UTF-8')
        if enable_global:
            libintl.textdomain(domain)
        del libintl


enable_translation('stoqserver', enable_global=True)
