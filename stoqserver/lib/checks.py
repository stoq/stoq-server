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

import logging
from serial.serialutil import SerialException
import socket

from stoqdrivers.exceptions import InvalidReplyException, PrinterError
from stoqlib.database.runtime import get_current_station

from ..signals import CheckPinpadStatusEvent, CheckSatStatusEvent
from .lock import lock_pinpad, lock_printer, lock_sat

logger = logging.getLogger(__name__)


@lock_printer
def check_drawer(store=None):
    from .restful import DrawerResource
    try:
        return DrawerResource.ensure_printer(get_current_station(store), retries=1)
    except (SerialException, InvalidReplyException, PrinterError):
        return None
    except socket.timeout as error:
        logger.warning(error)
        return None


@lock_pinpad(block=False)
def check_pinpad():
    responses = CheckPinpadStatusEvent.send()
    if len(responses) > 0:
        return responses[0][1]
    return True


@lock_sat(block=False)
def check_sat():
    if len(CheckSatStatusEvent.receivers) == 0:
        # No SAT was found, what means there is no need to warn front-end there is a missing
        # or broken SAT
        return True

    event_reply = CheckSatStatusEvent.send()
    return event_reply and event_reply[0][1]
