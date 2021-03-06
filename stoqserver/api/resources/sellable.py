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

from decimal import Decimal, DecimalException
from flask import abort, make_response, jsonify

from stoqlib.domain.image import Image
from stoqlib.domain.overrides import SellableBranchOverride
from stoqlib.domain.person import Branch
from stoqlib.domain.product import Product, Storable
from stoqlib.domain.sellable import Sellable

from stoqserver.lib.baseresource import BaseResource

from stoqserver.api.decorators import login_required, store_provider

log = logging.getLogger(__name__)


class SellableResource(BaseResource):
    method_decorators = [login_required, store_provider]
    routes = [
        '/sellable',
        '/sellable/<uuid:sellable_id>',
        '/sellable/<uuid:sellable_id>/override/<uuid:branch_id>'
    ]

    def _price_validation(self, data):
        try:
            base_price = Decimal(data.get('base_price', "0.01") or '0.01')
        except (ValueError, DecimalException):
            message = 'Price with incorrect format'
            log.error(message)
            abort(400, message)

        if base_price and base_price < 0:
            message = 'Price must be greater than 0'
            log.error(message)
            abort(400, message)

        return base_price

    def _create_sellable_dict(self, sellable, image):
        return {
            'id': sellable.id,
            'barcode': sellable.barcode,
            'description': sellable.description,
            'notes': sellable.notes,
            'image_id': image.id if image else None
        }

    def post(self, store):
        data = self.get_json()

        log.debug("POST /sellable station: %s payload: %s",
                  self.get_current_station(store), data)

        if 'product' not in data:
            abort(400, 'There is no product data on payload')

        sellable_id = data.get('sellable_id')
        barcode = data.get('barcode')
        description = data.get('description')
        base_price = self._price_validation(data)
        sellable = store.get(Sellable, sellable_id)
        sellable_created_via_sale = sellable and Sellable.NOTES_CREATED_VIA_SALE in sellable.notes

        if sellable and not sellable_created_via_sale:
            message = 'Product with id {} already exists'.format(sellable_id)
            log.warning(message)
            return make_response(jsonify({
                'message': message,
            }), 200)

        if barcode and store.find(Sellable, barcode=barcode):
            message = 'Product with barcode {} already exists'.format(barcode)
            log.warning(message)
            return make_response(jsonify({
                'message': message,
            }), 200)

        if not sellable:
            sellable = Sellable(store=store)
            if sellable_id:
                sellable.id = sellable_id
        sellable.code = barcode
        sellable.barcode = barcode
        sellable.description = description
        # FIXME The sellable is created with STATUS_CLOSED because we need the taxes info
        # to start selling so this is just a temporary sellable just to save it on the
        # database so the override can be created
        sellable.status = Sellable.STATUS_CLOSED
        sellable.base_price = base_price
        # If the sellable was pre-created on a sale it has a notes informing it and to
        # proceed this note is removed
        sellable.notes = sellable.notes.replace(Sellable.NOTES_CREATED_VIA_SALE, "")

        product = sellable.product if sellable_created_via_sale else (
            Product(store=store, sellable=sellable))

        product_data = data.get('product')
        product.manage_stock = product_data.get('manage_stock', False)

        # For clients that will control their inventory, we have to create a Storable
        if product.manage_stock and not store.get(Storable, product.id):
            storable = Storable(store=store, product=product)
            storable.maximum_quantity = 1000

        return make_response(jsonify({
            'message': 'Product created',
            'data': {
                'id': sellable.id,
                'barcode': sellable.barcode,
                'description': sellable.description,
                'status': sellable.status,
            }
        }), 201)

    def put(self, store, sellable_id, branch_id):
        data = self.get_json()
        status = data.get('status')
        base_price = self._price_validation(data)

        log.debug("PUT /sellable/%s/override/%s station: %s payload: %s",
                  sellable_id, branch_id, self.get_current_station(store), data)

        if status and status not in [Sellable.STATUS_AVAILABLE, Sellable.STATUS_CLOSED]:
            message = 'Status must be: {} or {}'.format(Sellable.STATUS_AVAILABLE,
                                                        Sellable.STATUS_CLOSED)
            log.error(message)
            abort(400, message)

        sellable = store.get(Sellable, sellable_id)
        if not sellable:
            message = 'Sellable with ID = {} not found'.format(sellable_id)
            log.error(message)
            abort(404, message)

        branch = store.get(Branch, branch_id)
        if not branch:
            message = 'Branch with ID = {} not found'.format(branch_id)
            log.error(message)
            abort(404, message)

        sbo = SellableBranchOverride.find_by_sellable(branch=branch, sellable=sellable)
        if not sbo:
            sbo = SellableBranchOverride(store=store,
                                         branch=branch,
                                         sellable=sellable)
        if status:
            sbo.status = status
        sbo.base_price = base_price or sbo.base_price

        return make_response(jsonify({
            'message': 'Product updated',
            'data': {
                'sellable_id': sellable_id,
                'base_price': str(sbo.base_price),
                'status': sbo.status,
                'branch_id': branch_id
            }
        }), 200)

    def get(self, store, sellable_id=None):
        if sellable_id:
            sellable = store.get(Sellable, sellable_id)
            if not sellable:
                message = 'Sellable with ID = {} not found'.format(sellable_id)
                log.error(message)
                abort(404, message)

            image = store.find(Image, sellable_id=sellable.id).any()

            return make_response(jsonify({
                "data": self._create_sellable_dict(sellable, image)
            }), 200)

        sellables = []
        for sellable in store.find(Sellable):
            image = store.find(Image, sellable_id=sellable.id).one()
            sellables.append(self._create_sellable_dict(sellable, image))

        # TODO: Maybe add pagination
        return make_response(jsonify({'data': sellables}), 200)
