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

import json
import pytest

from stoqlib.domain.inventory import Inventory


@pytest.fixture
def branch(example_creator):
    branch = example_creator.create_branch()
    return branch


@pytest.fixture
def inventory(example_creator):
    inventory = example_creator.create_inventory()
    return inventory


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_post(client, store, example_creator, branch):
    product = example_creator.create_product(branch=branch, description='Product 1',
                                             stock=1, storable=True)
    product.sellable.barcode = '7891910000197'

    count = {
        product.sellable.barcode: 12,
    }

    payload = {
        'branch_id': branch.id,
        'count': count
    }

    response = client.post('/inventory', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 201

    inventory = store.get(Inventory, res['id'])
    assert inventory.station == client.station
    assert inventory.is_open()

    item = inventory.get_items_for_adjustment().one()
    assert item.counted_quantity == count[item.product.sellable.barcode]

    assert res['identifier'] == inventory.identifier
    assert res['status'] == 'open'
    assert res['not_found'] == []
    assert res['stock_not_managed'] == []
    assert res['items'] == [
        {
            'recorded_quantity': '1',
            'counted_quantity': str(count[product.sellable.barcode]),
            'difference': str(count[product.sellable.barcode] - 1),
            'product': {
                'sellable': {
                    'barcode': product.sellable.barcode,
                    'code': product.sellable.code,
                    'description': product.sellable.description
                }
            }
        }
    ]


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_post_with_code(client, store, example_creator, branch):
    product = example_creator.create_product(branch=branch, description='Product 1',
                                             stock=2, storable=True)
    product.sellable.code = '7894900531008'

    count = {
        product.sellable.code: 13
    }

    payload = {
        'branch_id': branch.id,
        'count': count
    }

    response = client.post('/inventory', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 201

    inventory = store.get(Inventory, res['id'])
    assert inventory.station == client.station
    assert inventory.is_open()

    item = inventory.get_items_for_adjustment().one()
    assert item.counted_quantity == count[item.product.sellable.code]

    assert res['identifier'] == inventory.identifier
    assert res['status'] == 'open'
    assert res['not_found'] == []
    assert res['stock_not_managed'] == []
    assert res['items'] == [
        {
            'recorded_quantity': '2',
            'counted_quantity': str(count[product.sellable.code]),
            'difference': str(count[product.sellable.code] - 2),
            'product': {
                'sellable': {
                    'barcode': product.sellable.barcode,
                    'code': product.sellable.code,
                    'description': product.sellable.description
                }
            }
        },
    ]


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_post_empty_barcode(client, store, branch):
    empty_barcode = ''
    count = {
        empty_barcode: 14
    }
    payload = {
        'branch_id': branch.id,
        'count': count
    }

    response = client.post('/inventory', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 400
    assert res['message'] == ('Invalid barcode provided: {}. '
                              'It should be a not empty string.').format(empty_barcode)


@pytest.mark.usefixtures('mock_new_store')
@pytest.mark.parametrize('invalid_quantity', (-3, 'dois', '2', '1.2', '1,2', [2], {}, '', None))
def test_inventory_post_invalid_quantity(client, store, example_creator, branch, invalid_quantity):
    count = {
        '7894900531008': invalid_quantity
    }
    payload = {
        'branch_id': branch.id,
        'count': count
    }

    response = client.post('/inventory', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 400
    assert res['message'] == ('Invalid quantity provided: {}. '
                              'It should be a not negative number.').format(invalid_quantity)


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_post_no_count(client, store, example_creator, branch):
    payload = {
        'branch_id': branch.id
    }
    response = client.post('/inventory', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 400
    assert res['message'] == 'No count provided'


@pytest.mark.usefixtures('mock_new_store')
@pytest.mark.parametrize('invalid_count', (('7894900531008', 7), ['7894900531008', 7],
                         '7894900531008:7'))
def test_inventory_post_invalid_count(client, store, example_creator, branch, invalid_count):
    payload = {
        'branch_id': branch.id,
        'count': invalid_count
    }
    response = client.post('/inventory', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 400
    assert res['message'] == ('count should be a JSON with barcodes or codes as keys '
                              'and counted quantities as values')


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_post_no_branch_id(client, store):
    payload = {
        'count': {
            '7891910000197': 14
        }
    }
    response = client.post('/inventory', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 400
    assert res['message'] == 'No branch_id provided'


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_post_branch_not_found(client, store):
    branch_id = 'b218ad4a-cebd-44ca-838e-ead9c62cd895'
    count = {
        '7891910000197': 14
    }
    payload = {
        'branch_id': branch_id,
        'count': count
    }

    response = client.post('/inventory', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 404
    assert res['message'] == (
        'Branch {} not found. You have requested this URI [/inventory] but '
        'did you mean /inventory or /inventory/<uuid:inventory_id> ?'
    ).format(branch_id)


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_post_sellable_not_found(client, store, branch):
    count = {
        '123': 12,
        '456': 13
    }

    payload = {
        'branch_id': branch.id,
        'count': count
    }

    response = client.post('/inventory', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 201

    inventory = store.get(Inventory, res['id'])
    assert inventory.station == client.station
    assert inventory.status == Inventory.STATUS_CANCELLED

    assert len(list(inventory.get_items_for_adjustment())) == 0

    assert res['identifier'] == inventory.identifier
    assert res['status'] == 'cancelled'
    assert set(res['not_found']) == set(('123', '456'))
    assert res['stock_not_managed'] == []
    assert res['items'] == []


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_post_stock_not_managed(client, store, example_creator, branch):
    product = example_creator.create_product(branch=branch, description='Product')
    product.sellable.barcode = '7891910000197'

    count = {
        product.sellable.barcode: 12,
    }

    payload = {
        'branch_id': branch.id,
        'count': count
    }

    response = client.post('/inventory', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 201

    inventory = store.get(Inventory, res['id'])
    assert inventory.station == client.station
    assert inventory.status == inventory.STATUS_CANCELLED

    assert len(list(inventory.get_items_for_adjustment())) == 0

    assert res['identifier'] == inventory.identifier
    assert res['status'] == 'cancelled'
    assert res['not_found'] == []
    assert res['stock_not_managed'] == [
        {
            'counted_quantity': str(count[product.sellable.barcode]),
            'product': {
                'sellable': {
                    'barcode': product.sellable.barcode,
                    'code': product.sellable.code,
                    'description': product.sellable.description
                }
            }
        }
    ]
    assert res['items'] == []


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_put_cancelled(client, inventory):
    assert inventory.status == Inventory.STATUS_OPEN

    payload = {'status': 'cancelled'}
    response = client.put('/inventory/{}'.format(inventory.id), json=payload)

    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200
    assert res['id'] == inventory.id
    assert res['identifier'] == inventory.identifier
    assert res['status'] == inventory.status == Inventory.STATUS_CANCELLED


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_put_closed(client, inventory):
    assert inventory.status == Inventory.STATUS_OPEN

    payload = {'status': 'closed'}
    response = client.put('/inventory/{}'.format(inventory.id), json=payload)

    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200
    assert res['id'] == inventory.id
    assert res['identifier'] == inventory.identifier
    assert res['status'] == inventory.status == Inventory.STATUS_CLOSED


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_put_closed_with_adjustment(client, example_creator, inventory):
    inventory_item = example_creator.create_inventory_item(inventory=inventory)
    inventory_item.counted_quantity = 6

    assert inventory.status == Inventory.STATUS_OPEN
    assert inventory.get_items_for_adjustment().count() == 1

    payload = {'status': 'closed'}
    response = client.put('/inventory/{}'.format(inventory.id), json=payload)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert res['id'] == inventory.id
    assert res['identifier'] == inventory.identifier
    assert res['status'] == inventory.status == Inventory.STATUS_CLOSED
    assert inventory.get_items_for_adjustment().count() == 0


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_put_no_status(client, inventory):
    response = client.put('/inventory/{}'.format(inventory.id))
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 400
    assert res['message'] == 'No status provided'


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_put_invalid_status(client, inventory):
    payload = {'status': 'invalid_status'}
    response = client.put('/inventory/{}'.format(inventory.id), json=payload)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 400
    assert res['message'] == 'Status should be {} or {}'.format(
        Inventory.STATUS_CLOSED, Inventory.STATUS_CANCELLED)


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_put_not_found(client):
    payload = {'status': 'closed'}
    inventory_id = 'b218ad4a-cebd-44ca-838e-ead9c62cd895'

    response = client.put('/inventory/{}'.format(inventory_id), json=payload)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 404
    assert res['message'] == 'Inventory with ID = {} not found'.format(inventory_id)


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_put_already_cancelled(client, inventory):
    inventory.status = Inventory.STATUS_CANCELLED

    payload = {'status': 'cancelled'}
    response = client.put('/inventory/{}'.format(inventory.id), json=payload)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 400
    assert res['message'] == 'You can\'t cancel an inventory that is not opened!'


@pytest.mark.usefixtures('mock_new_store')
def test_inventory_put_already_closed(client, inventory):
    inventory.status = Inventory.STATUS_CANCELLED

    payload = {'status': 'closed'}
    response = client.put('/inventory/{}'.format(inventory.id), json=payload)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 400
    assert res['message'] == 'It isn\'t possible to close an inventory which is not opened'
