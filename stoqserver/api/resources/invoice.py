# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2021 Stoq Tecnologia <http://www.stoq.com.br>
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


import json
import logging

from flask import Response, abort
from lxml import etree
from stoqlib.domain.person import Branch
from stoqlib.lib.api.nfe import NFe

from stoqserver.api.decorators import login_required, store_provider
from stoqserver.lib.baseresource import BaseResource
from stoqserver.signals import GetImportedNFeByIdEvent

log = logging.getLogger(__name__)


class NfePurchaseResource(BaseResource):
    routes = ['/api/v1/invoice/import']
    method_decorators = [login_required, store_provider]

    def _get_imported_nfe_data(self, store, imported_nfe_id):
        responses = GetImportedNFeByIdEvent.send(store, id=imported_nfe_id)
        imported_nfe_data = responses[0][1]

        return imported_nfe_data

    def post(self, store):
        data = self.get_json()
        imported_nfe_id = data.get('imported_nfe_id')
        branch_id = data.get('branch_id')

        if not imported_nfe_id:
            message = 'No imported_nfe_id provided'
            log.error(message)
            abort(400, message)

        if not branch_id:
            message = 'No branch_id provided'
            log.error(message)
            abort(400, message)

        branch = store.get(Branch, branch_id)
        if not branch:
            message = 'Branch not found'
            log.error(message)
            abort(400, message)

        imported_nfe = self._get_imported_nfe_data(store, imported_nfe_id)
        if not imported_nfe:
            message = 'ImportedNfe not found'
            log.error(message)
            abort(400, message)

        xml_encoded = etree.tostring(imported_nfe.xml, encoding='unicode')
        nfe = NFe(xml_encoded, store)
        nfe_purchase = nfe.process(branch_id=branch_id)

        return Response(json.dumps({'id': nfe_purchase.id,
                                    'invoice_number': nfe_purchase.invoice_number,
                                    'invoice_series': nfe_purchase.invoice_series,
                                    'process_date': str(nfe_purchase.process_date)}),
                        201,
                        mimetype='application/json')
