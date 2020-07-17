import json
import pytest

from stoqlib.domain.sellable import Sellable


@pytest.fixture
def sellable(example_creator):
    product = example_creator.create_product(price=10)
    product.manage_stock = False
    product.sellable.requires_kitchen_production = False
    return product.sellable


@pytest.mark.parametrize('status, expected_status',
                         [(Sellable.STATUS_AVAILABLE, Sellable.STATUS_AVAILABLE),
                          (Sellable.STATUS_CLOSED, Sellable.STATUS_CLOSED),
                          (None, Sellable.STATUS_AVAILABLE)])
@pytest.mark.parametrize('base_price', (5.3, 9.4))
@pytest.mark.usefixtures('mock_new_store')
def test_sellable_put(client, sellable, current_station,
                      status, expected_status, base_price):
    payload = {
        'status': status,
        'base_price': base_price
    }

    endpoint = '/sellable/{}/override/{}'.format(sellable.id, current_station.branch_id)
    response = client.put(endpoint, json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200
    assert res['data']['status'] == expected_status
    assert res['data']['base_price'] == str(base_price)


@pytest.mark.parametrize('status', ('status', '42'))
@pytest.mark.usefixtures('mock_new_store')
def test_sellable_put_with_invalid_status(client, sellable, current_station, status):
    payload = {
        'status': status,
    }

    endpoint = '/sellable/{}/override/{}'.format(sellable.id, current_station.branch_id)
    response = client.put(endpoint, json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 400
    assert res['message'] == 'Status must be: {} or {}'.format(Sellable.STATUS_AVAILABLE,
                                                               Sellable.STATUS_CLOSED)


@pytest.mark.parametrize('base_price', ('4,5', 'R$2.3'))
@pytest.mark.usefixtures('mock_new_store')
def test_sellable_put_with_invalid_price(client, sellable, current_station, base_price):
    payload = {
        'status': Sellable.STATUS_AVAILABLE,
        'base_price': base_price
    }
    endpoint = '/sellable/{}/override/{}'.format(sellable.id, current_station.branch_id)
    response = client.put(endpoint, json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 400
    assert res['message'] == 'Price with incorrect format'


@pytest.mark.parametrize('base_price', (-1, -13))
@pytest.mark.usefixtures('mock_new_store')
def test_sellable_put_with_negative_price(client, sellable, current_station, base_price):
    payload = {
        'status': Sellable.STATUS_AVAILABLE,
        'base_price': base_price
    }
    endpoint = '/sellable/{}/override/{}'.format(sellable.id, current_station.branch_id)
    response = client.put(endpoint, json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 400
    assert res['message'] == 'Price must be greater than 0'


@pytest.mark.usefixtures('mock_new_store')
def test_sellable_put_with_invalid_sellable_id(client, current_station):
    payload = {
        'status': Sellable.STATUS_AVAILABLE,
        'base_price': 10
    }
    endpoint = '/sellable/{}/override/{}'.format('888dbd47-f8b3-11e8-8ca5-000bca142853',
                                                 current_station.branch_id)
    response = client.put(endpoint, json=payload)
    assert response.status_code == 404


@pytest.mark.usefixtures('mock_new_store')
def test_sellable_put_with_invalid_branch_id(client, sellable):
    payload = {
        'status': Sellable.STATUS_AVAILABLE,
        'base_price': 10
    }
    endpoint = '/sellable/{}/override/{}'.format(sellable.id,
                                                 '888dbd47-f8b3-11e8-8ca5-000bca142853')
    response = client.put(endpoint, json=payload)
    assert response.status_code == 404
