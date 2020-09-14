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

from decimal import Decimal
import logging

from flask import abort, jsonify, make_response

from stoqlib.domain.inventory import Inventory
from stoqlib.domain.person import Branch
from stoqlib.domain.product import Sellable

from stoqserver.lib.baseresource import BaseResource
from stoqserver.api.decorators import login_required, store_provider

log = logging.getLogger(__name__)


class InventoryResource(BaseResource):
    method_decorators = [login_required, store_provider]
    routes = ['/inventory', '/inventory/<uuid:inventory_id>']

    def _apply_count_to_inventory(self, store, count, inventory):
        stock_not_managed = []
        unmanaged_barcodes = []

        for sellable, quantity in count.items():
            inventory_item = inventory.get_items().find(product_id=sellable.id).one()

            if inventory_item:
                inventory_item.counted_quantity = quantity
                continue

            stock_not_managed_item = {
                'counted_quantity': str(quantity),
                'product': {
                    'sellable': {
                        'barcode': sellable.barcode,
                        'code': sellable.code,
                        'description': sellable.description
                    }
                }
            }
            stock_not_managed.append(stock_not_managed_item)
            unmanaged_barcodes.append(sellable.barcode or sellable.code)

        if unmanaged_barcodes:
            log.warning('Some sellables have not their stock being managed: %s',
                        unmanaged_barcodes)

        return stock_not_managed

    def _convert_count_keys(self, store, count):
        """Convert the count dict keys from string barcodes or codes to its referring sellables.

        In case of barcodes or codes referring to no existing sellable, return them on a list.

        :param count: a dict with string barcodes or codes as keys and its numeric quantities as
        values"""
        data = {}
        not_found = set()

        for barcode, quantity in count.items():
            if not barcode or not isinstance(barcode, str):
                message = ('Invalid barcode provided: {}. '
                           'It should be a not empty string.').format(barcode)
                log.error(message)
                abort(400, message)

            if not isinstance(quantity, (int, Decimal)) or quantity < 0:
                message = ('Invalid quantity provided: {}. '
                           'It should be a not negative number.').format(quantity)
                log.error(message)
                abort(400, message)

            sellable = store.find(Sellable, barcode=str(barcode)).one() or \
                store.find(Sellable, code=str(barcode)).one()

            if not sellable:
                not_found.add(barcode)
                continue

            data[sellable] = quantity

        if not_found:
            log.warning('Some barcodes were not found: %s', not_found)

        return data, not_found

    def post(self, store):
        branch_id = self.get_arg('branch_id')
        count = self.get_arg('count')

        if not branch_id:
            message = 'No branch_id provided'
            log.error(message)
            abort(400, message)
        if not count:
            message = 'No count provided'
            log.error(message)
            abort(400, message)
        if not isinstance(count, dict):
            message = ('count should be a JSON with barcodes or codes as keys '
                       'and counted quantities as values')
            log.error(message)
            abort(400, message)

        branch = store.get(Branch, branch_id)
        if not branch:
            message = 'Branch {} not found'.format(branch_id)
            log.error(message)
            abort(404, message)

        login_user = self.get_current_user(store)
        station = self.get_current_station(store)

        sellable_count, not_found = self._convert_count_keys(store, count)
        query = Sellable in sellable_count.keys()

        inventory = Inventory.create_inventory(store, branch, station, login_user, query)
        stock_not_managed = self._apply_count_to_inventory(store, sellable_count, inventory)

        items_for_adjustment = inventory.get_items_for_adjustment()

        items_for_adjustment_list = []
        for item_for_adjustment in items_for_adjustment:
            items_for_adjustment_list.append({
                'recorded_quantity': str(item_for_adjustment.recorded_quantity.normalize()),
                'counted_quantity': str(item_for_adjustment.counted_quantity.normalize()),
                'difference': str(item_for_adjustment.difference.normalize()),
                'product': {
                    'sellable': {
                        'barcode': item_for_adjustment.product.sellable.barcode,
                        'code': item_for_adjustment.get_code(),
                        'description': item_for_adjustment.get_description()
                    }
                }
            })

        if not items_for_adjustment_list:
            inventory.cancel()

        return make_response(jsonify({
            'id': inventory.id,
            'identifier': inventory.identifier,
            'status': inventory.status,
            'not_found': list(not_found),
            'stock_not_managed': stock_not_managed,
            'items': items_for_adjustment_list
        }), 201)

    def put(self, store, inventory_id):
        new_status = self.get_arg('status')
        if not new_status:
            message = 'No status provided'
            log.error(message)
            abort(400, message)

        if new_status not in [Inventory.STATUS_CLOSED, Inventory.STATUS_CANCELLED]:
            message = 'Status should be {} or {}'.format(
                Inventory.STATUS_CLOSED, Inventory.STATUS_CANCELLED)
            log.error(message)
            abort(400, message)

        inventory = store.get(Inventory, inventory_id)
        if not inventory:
            message = 'Inventory with ID = {} not found'.format(inventory_id)
            log.error(message)
            abort(404, message)

        if new_status == Inventory.STATUS_CANCELLED:
            try:
                inventory.cancel()
            except AssertionError as err:
                log.error(str(err))
                abort(400, str(err))

        elif new_status == Inventory.STATUS_CLOSED:
            login_user = self.get_current_user(store)

            try:
                # FIXME: Move this message to InventoryItem.adjust() from stoqlib
                assert inventory.is_open(
                ), 'It isn\'t possible to close an inventory which is not opened'

                for item in inventory.get_items_for_adjustment():
                    item.actual_quantity = item.counted_quantity
                    item.reason = 'Automatic adjustment'
                    item.adjust(login_user, invoice_number=None)
                inventory.close()
            except AssertionError as err:
                log.error(str(err))
                abort(400, str(err))

        return make_response(jsonify({
            'id': inventory.id,
            'identifier': inventory.identifier,
            'status': inventory.status,
        }), 200)
