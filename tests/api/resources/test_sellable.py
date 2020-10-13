import json
import pytest
from decimal import Decimal

from stoqlib.domain.product import Product
from stoqlib.domain.sellable import Sellable

from stoqserver.api.resources.sellable import SellableResource


@pytest.fixture
def sellable(example_creator):
    product = example_creator.create_product(price=10)
    product.manage_stock = False
    product.sellable.requires_kitchen_production = False
    return product.sellable


@pytest.mark.parametrize('status, expected_status',
                         [(Sellable.STATUS_AVAILABLE, Sellable.STATUS_AVAILABLE),
                          (Sellable.STATUS_CLOSED, Sellable.STATUS_CLOSED)])
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


@pytest.mark.usefixtures('mock_new_store')
def test_sellable_post(client, store):
    payload = {
        'sellable_id': '8397d64b-5024-4142-af00-a0e3df3ff4ad',
        'barcode': '7896045504831',
        'description': 'Cerveja Amstel Lager Lata',
        'base_price': 3.7,
        'product': {
            'manage_stock': True
        }
    }

    assert store.get(Sellable, payload['sellable_id']) is None
    assert store.get(Product, payload['sellable_id']) is None

    response = client.post('/sellable', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    sellable = store.get(Sellable, payload['sellable_id'])
    product = store.get(Product, payload['sellable_id'])

    assert response.status_code == 201
    assert res['message'] == 'Product created'
    assert store.get(Sellable, payload['sellable_id']) is not None
    assert store.get(Product, payload['sellable_id']) is not None
    assert sellable.id == payload['sellable_id']
    assert sellable.description == payload['description']
    assert sellable.barcode == payload['barcode']
    assert product.id == payload['sellable_id']
    assert product.manage_stock is True


@pytest.mark.usefixtures('mock_new_store')
def test_sellable_post_without_product(client, store):
    payload = {
        'sellable_id': '8397d64b-5024-4142-af00-a0e3df3ff4ad',
        'barcode': '7896045504831',
        'description': 'Cerveja Amstel Lager Lata',
        'base_price': 3.7,
    }
    response = client.post('/sellable', json=payload)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 400
    assert res['message'] == 'There is no product data on payload'


@pytest.mark.parametrize('base_price', ('4,5', 'R$2.3'))
@pytest.mark.usefixtures('mock_new_store')
def test_sellable_post_with_invalid_price(client, base_price):
    payload = {
        'sellable_id': '8397d64b-5024-4142-af00-a0e3df3ff4ad',
        'barcode': '7896045504831',
        'description': 'Cerveja Amstel Lager Lata',
        'base_price': base_price,
        'product': {},
    }
    response = client.post('/sellable', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 400
    assert res['message'] == 'Price with incorrect format'


@pytest.mark.usefixtures('mock_new_store')
def test_sellable_post_with_existing_sellable(client, example_creator):
    sellable = example_creator.create_sellable(price=10)
    payload = {
        'sellable_id': sellable.id,
        'barcode': '7896045504831',
        'description': 'Cerveja Amstel Lager Lata',
        'base_price': 3.5,
        'product': {},
    }
    response = client.post('/sellable', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200
    assert res['message'] == 'Product with id {} already exists'.format(sellable.id)


@pytest.mark.usefixtures('mock_new_store')
def test_sellable_post_with_existing_barcode(client, example_creator):
    sellable = example_creator.create_sellable(price=10)
    sellable.barcode = '7896045504831'
    payload = {
        'sellable_id': '8397d64b-5024-4142-af00-a0e3df3ff4ad',
        'barcode': sellable.barcode,
        'description': 'Cerveja Amstel Lager Lata',
        'base_price': 3.5,
        'product': {},
    }
    response = client.post('/sellable', json=payload)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200
    assert res['message'] == 'Product with barcode {} already exists'.format(sellable.barcode)


@pytest.mark.usefixtures('mock_new_store')
def test_sellable_get_by_id(client, example_creator):
    sellable = example_creator.create_sellable(description='Sellable Test')
    sellable.barcode = '7896045504831'
    sellable.notes = 'this is a sellable test'
    img = example_creator.create_image()
    img.image = "foobar".encode('ascii')
    img.sellable_id = sellable.id

    response = client.get('/sellable/' + sellable.id)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200
    assert res['data'] == {
        'id': sellable.id,
        'description': sellable.description,
        'barcode': sellable.barcode,
        'notes': sellable.notes,
        'image_id': img.id
    }


@pytest.mark.usefixtures('mock_new_store')
def test_sellable_get_by_id_not_found(client, example_creator):
    response = client.get('/sellable/4265221a-d8de-11ea-b34e-40b89ae8d341')
    assert response.status_code == 404


@pytest.mark.usefixtures('mock_new_store')
def test_sellable_get_all(client, example_creator):
    example_creator.create_sellable(description="S1")
    example_creator.create_sellable(description="S2")
    example_creator.create_sellable(description="S3")

    response = client.get('/sellable')
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200
    assert len(res['data']) >= 3
    assert set(("description", "id", "image_id", "barcode", "notes")) == res['data'][0].keys()


def test_price_validation():
    res = SellableResource()._price_validation({
        'base_price': 10.00
    })
    assert res == Decimal("10.00")

    res = SellableResource()._price_validation({})
    assert res == Decimal("0.01")

    res = SellableResource()._price_validation({
        'base_price': 0
    })
    assert res == Decimal("0.01")
