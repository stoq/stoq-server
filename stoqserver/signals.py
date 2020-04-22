# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2019 Async Open Source <http://www.async.com.br>
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

from blinker import signal

# Device status events
CheckSatStatusEvent = signal('CheckSatStatusEvent')
CheckPinpadStatusEvent = signal('CheckPinpadStatusEvent')

# Tef events
TefPrintReceiptsEvent = signal('TefPrintReceiptsEvent')
TefCheckPendingEvent = signal('TefCheckPendingEvent')

GrantLoyaltyPointsEvent = signal('GrantLoyaltyPointsEvent')  # XXX: not sure about this names
PrintAdvancePaymentReceiptEvent = signal('PrintAdvancePaymentReceiptEvent')
GetAdvancePaymentCategoryEvent = signal('GetAdvancePaymentCategoryEvent')
GenerateAdvancePaymentReceiptPictureEvent = signal('GenerateAdvancePaymentReceiptPictureEvent')
GenerateInvoicePictureEvent = signal('GenerateInvoicePictureEvent')
GenerateTillClosingReceiptImageEvent = signal('GenerateTillClosingReceiptImageEvent')

FinishExternalOrderEvent = signal('FinishExternalOrderEvent')
StartExternalOrderEvent = signal('StartExternalOrderEvent')
CancelExternalOrderEvent = signal('CancelExternalOrderEvent')
PrintExternalOrderEvent = signal('PrintExternalOrderEvent')

PrintKitchenCouponEvent = signal('PrintKitchenCouponEvent')

StartPassbookSaleEvent = signal('StartPassbookSaleEvent')
SearchForPassbookUsersByDocumentEvent = signal('SearchForPassbookUsersByDocumentEvent')

EventStreamEstablishedEvent = signal('EventStreamEstablishedEvent')

GenerateExternalOrderReceiptImageEvent = signal('GenerateExternalOrderReceiptImageEvent')
