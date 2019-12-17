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

from serial.serialutil import SerialException

from stoqdrivers.exceptions import InvalidReplyException
from stoqlib.database.runtime import get_current_station

from ..signals import CheckPinpadStatusEvent, CheckSatStatusEvent
from .lock import lock_pinpad, lock_printer, lock_sat


@lock_printer
def check_drawer():
    from .restful import DrawerResource
    try:
        return DrawerResource.ensure_printer(get_current_station(), retries=1)
    except (SerialException, InvalidReplyException):
        return None


@lock_pinpad(block=False)
def check_pinpad():
    event_reply = CheckPinpadStatusEvent.send()
    return event_reply and event_reply[0][1]


@lock_sat(block=False)
def check_sat():
    if len(CheckSatStatusEvent.receivers) == 0:
        # No SAT was found, what means there is no need to warn front-end there is a missing
        # or broken SAT
        return True

    event_reply = CheckSatStatusEvent.send()
    return event_reply and event_reply[0][1]
