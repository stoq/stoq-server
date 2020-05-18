# import requests
from unittest import mock

import pytest

from kiwi.currency import currency
# from stoqifood.domain import IfoodOrder
from stoqlib.domain.overrides import ProductBranchOverride
from stoqlib.domain.sale import Sale
from stoqlib.domain.person import Individual
from stoqlib.domain.till import Till
from storm.expr import Desc

from stoqserver.lib import restful


# We must import restful if we want to run some tests individually. Otherwise, only patches that
# mock stoqlib.lib.restful work when running pytest with -k
restful


@pytest.fixture
def sellable(example_creator):
    product = example_creator.create_product(price=10)
    product.manage_stock = False
    product.sellable.requires_kitchen_production = False
    return product.sellable


@pytest.fixture
def sale_payload(sellable):
    products = [{
        'id': sellable.id,
        'price': str(sellable.price),
        'quantity': 1,
    }]

    payments = [{
        'method': 'money',
        'mode': None,
        'provider': None,
        'installments': 1,
        'value': str(sellable.price),
    }]

    return {
        'products': products,
        'payments': payments,
        'order_number': 69,
        'discount_value': 0,
    }


@pytest.fixture
def sale_payload_new_client(sellable):
    products = [{
        'id': sellable.id,
        'price': str(sellable.price),
        'quantity': 1,
    }]

    payments = [{
        'method': 'money',
        'mode': None,
        'provider': None,
        'installments': 1,
        'value': str(sellable.price),
    }]
    address = {
        'street': 'Rua Aquidaban',
        'streetnumber': 1,
        'district': 'Centro',
        'postal_code': '13560-120',
        'is_main_address': True,
    }
    city_location = {
        'country': 'Brazil',
        'state': 'SP',
        'city': 'São Carlos',
    }

    return {
        'address': address,
        'city_location': city_location,
        'client_document': '111.111.111-11',
        'client_name': 'José Silva',
        'products': products,
        'payments': payments,
        'order_number': 69,
        'discount_value': 0,
    }


@pytest.fixture
def kps_station(current_station):
    current_station.has_kps_enabled = True
    return current_station


@pytest.fixture
def open_till(current_till, current_user):
    if current_till.status != Till.STATUS_OPEN:
        current_till.open_till(current_user)

    return current_till


@pytest.fixture
def close_till(open_till, current_user):
    open_till.close_till(current_user)

    return open_till


@pytest.fixture
def plugin_manager():
    plugin_manager = mock.Mock()
    plugin_manager.active_plugins_names = ["nfce", "passbook"]
    return plugin_manager


@pytest.fixture
def mock_new_store(monkeypatch, store):
    monkeypatch.setattr('stoqserver.lib.restful.api.new_store', mock.Mock(return_value=store))


@pytest.fixture
def mock_get_default_store(monkeypatch, store):
    monkeypatch.setattr('stoqserver.lib.restful.api.get_default_store',
                        mock.Mock(return_value=store))


@pytest.fixture
def mock_get_plugin_manager(monkeypatch, plugin_manager):
    monkeypatch.setattr('stoqserver.lib.restful.get_plugin_manager',
                        mock.Mock(return_value=plugin_manager))


@pytest.fixture
def passbook_client():
    return {
        'name': 'Test client',
        'doc': '123.123.123-12',
        'passbook_client_info': {
            'user': {
                'name': 'Test client',
                'uniqueId': '123.123.123-12',
            },
            'hasPinNumber': 'false',
            'type': 'stamps',
            'points': "10",
            'stamps_limit': 10
        }
    }


@pytest.fixture
def order_details():
    return {
        "id": "bb2ec7fe-5276-4078-9d2e-b362da9f81ab",
        "reference": "1072170838351011",
        "shortReference": "6027",
        "createdAt": "2019-10-18T19:19:51.707Z",
        "scheduled": False,
        "merchant": {
            "id": "a940f92d-ba60-486d-b558-acbb1fedd175",
            "shortId": "314566",
            "name": "Restaurante Teste",
            "address": {
                "formattedAddress": "R. TESTE",
                "country": "BR",
                "state": "AC",
                "city": "BUJARI",
                "neighborhood": "Outros",
                "streetName": "R. TESTE",
                "streetNumber": "221",
                "postalCode": "69923000"}
        },
        "payments": [
            {
                "name": "DINHEIRO",
                "code": "DIN",
                "value": 3,
                "prepaid": False,
                "changeFor": 3}
        ],
        "customer": {
            "id": "114235279",
            "uuid": "6486f892-a849-4815-8de3-bc56e9fc236c",
            "name": "PEDIDO DE TESTE",
            "phone": "0800 + ID",
            "ordersCountOnRestaurant": 1,
            "taxPayerIdentificationNumber": "77788866655"},
        "items": [
            {
                "id": "13e82618-e6c7-454e-938d-cd0540846d69",
                "name": "Item 1",
                "quantity": 1,
                "price": 6.0,
                "subItemsPrice": 0,
                "totalPrice": 6.0,
                "discount": 0.0,
                "addition": 0.0,
                "externalId": "35620604",
                "index": 1},
        ],
        "subTotal": 16,
        "totalPrice": 18,
        "deliveryFee": 2,
        "deliveryAddress": {
            "formattedAddress": "PEDIDO DE TESTE - NÃO ENTREGAR - Ramal Bujari, 10",
            "country": "BR",
            "state": "AC",
            "city": "Bujari",
            "coordinates": {
                "latitude": -9.821256,
                "longitude": -67.948009
            },
            "neighborhood": "Bujari",
            "streetName": "PEDIDO DE TESTE - NÃO ENTREGAR - Ramal Bujari",
            "streetNumber": "10",
            "postalCode": "69923000"
        },
        "deliveryDateTime": "2019-10-18T20:19:51.707Z",
        "preparationStartDateTime": "2019-10-18T19:19:51.707Z",
        "localizer": {
            "id": "30943878"
        },
        "preparationTimeInSeconds": 1800,
        "isTest": True,
        "benefits": [
            {
                "value": 15,
                "sponsorshipValues": {
                    "IFOOD": 15,
                    "MERCHANT": 0},
                "target": "ITEM",
                "targetId": "12345"
            }
        ],
        "deliveryMethod": {
            "id": "DEFAULT",
            "value": 15.00,
            "minTime": 20,
            "maxTime": 30,
            "mode": "DELIVERY",
            "deliveredBy": "IFOOD"
        }
    }


# @pytest.fixture
# def ifood_order(store, order_details):
#     return IfoodOrder(store, status='PLACED', order_details=order_details)


@mock.patch('stoqserver.lib.restful.PrintKitchenCouponEvent.send')
@pytest.mark.parametrize('order_number', ('0', '', None))
@pytest.mark.usefixtures('kps_station', 'open_till', 'mock_new_store')
def test_kps_sale_with_invalid_order_number(
    mock_kps_event_send, client, order_number, sale_payload, sellable,
):
    sellable.requires_kitchen_production = True
    sale_payload['order_number'] = order_number

    response = client.post('/sale', json=sale_payload)

    assert mock_kps_event_send.call_count == 0
    assert response.status_code == 400


@mock.patch('stoqserver.lib.restful.PrintKitchenCouponEvent.send')
@pytest.mark.usefixtures('current_station', 'open_till', 'mock_new_store')
def test_kps_sale_with_kps_station_disabled(mock_kps_event_send, client, sale_payload):
    response = client.post('/sale', json=sale_payload)

    assert mock_kps_event_send.call_count == 0
    assert response.status_code == 201


@mock.patch('stoqserver.lib.restful.PrintKitchenCouponEvent.send')
@pytest.mark.usefixtures('open_till', 'kps_station', 'mock_new_store')
def test_kps_sale_without_kitchen_items(mock_kps_event_send, client, sale_payload):
    response = client.post('/sale', json=sale_payload)

    assert mock_kps_event_send.call_count == 0
    assert response.status_code == 201


@mock.patch('stoqserver.lib.restful.PrintKitchenCouponEvent.send')
@pytest.mark.usefixtures('kps_station', 'open_till', 'mock_new_store')
def test_kps_sale(mock_kps_event_send, client, sale_payload, sellable):
    sellable.requires_kitchen_production = True

    response = client.post('/sale', json=sale_payload)

    assert response.status_code == 201
    assert mock_kps_event_send.call_count == 1
    args, kwargs = mock_kps_event_send.call_args_list[0]
    assert len(args) == 1
    sale_items = list(args[0].get_items())
    assert sale_items[0].sellable == sellable
    assert kwargs == {'order_number': 69}


@pytest.mark.usefixtures('kps_station', 'open_till', 'mock_new_store')
def test_sale_with_discount(client, sale_payload, store):
    sale_payload['products'][0]['quantity'] = 10
    sale_payload['payments'][0]['value'] = 100
    sale_payload['discount_value'] = 25

    response = client.post('/sale', json=sale_payload)

    sale = store.find(Sale).order_by(Desc(Sale.open_date)).first()

    assert response.status_code == 201
    assert sale.get_total_sale_amount() == currency('75')
    assert sale.discount_value == currency('25')


@mock.patch('stoqserver.lib.restful.StartPassbookSaleEvent.send')
@pytest.mark.usefixtures('open_till', 'mock_new_store')
def test_remove_passbook_stamps(
    mock_passbook_send_event, client, sale_payload, passbook_client, current_station, current_user
):
    data = {
        'value': 10,
        'card_type': "credit",
        'provider': "",
        'user': current_user,
        'sale_ref': None,
        'client': {
            'name': 'Test client',
            'doc': '123.123.123-12',
            'passbook_client_info': passbook_client['passbook_client_info']
        },
    }

    sale_payload['passbook_client_info'] = passbook_client['passbook_client_info']
    sale_payload['discount_value'] = 9
    response = client.post('/sale', json=sale_payload)

    assert response.status_code == 201
    mock_passbook_send_event.assert_called_once_with(
        current_station, **data
    )


@mock.patch('stoqserver.lib.restful.StartPassbookSaleEvent.send')
@pytest.mark.usefixtures('open_till', 'mock_new_store')
def test_dont_remove_passbook_stamps(
    mock_passbook_send_event, client, sale_payload, passbook_client, current_station, current_user
):
    passbook_client['passbook_client_info']['points'] = '5'

    sale_payload['passbook_client_info'] = passbook_client['passbook_client_info']
    client.post('/sale', json=sale_payload)

    response = client.post('/sale', json=sale_payload)

    assert response.status_code == 201
    assert mock_passbook_send_event.send.call_count == 0


@mock.patch('stoqserver.lib.restful.StartPassbookSaleEvent.send')
@pytest.mark.usefixtures('open_till', 'mock_new_store')
def test_dont_remove_passbook_stamps_if_type_points(
    mock_passbook_send_event, client, sale_payload, passbook_client, current_station, current_user
):
    passbook_client['passbook_client_info']['type'] = 'points'

    sale_payload['passbook_client_info'] = passbook_client['passbook_client_info']
    client.post('/sale', json=sale_payload)

    response = client.post('/sale', json=sale_payload)

    assert response.status_code == 201
    assert mock_passbook_send_event.send.call_count == 0


@pytest.mark.usefixtures('open_till', 'mock_new_store')
def test_sale_with_package(client, sale_payload, example_creator, store):
    child1 = example_creator.create_product(price=88, description='child1', stock=5, code='98')
    child2 = example_creator.create_product(price=8, description='child2', stock=5, code='99')

    # But in a package, they have special prices
    package = example_creator.create_product(price=15, description=u'package', is_package=True)
    example_creator.create_product_component(product=package, component=child1, price=10)
    example_creator.create_product_component(product=package, component=child2, price=5)

    sale_payload['products'] = [{
        'id': package.id,
        'price': str(package.sellable.price),
        'quantity': 1,
    }]

    response = client.post('/sale', json=sale_payload)
    sale = store.find(Sale).order_by(Desc(Sale.open_date)).first()

    assert response.status_code == 201
    assert sale.get_total_sale_amount() == 15

    items = list(sale.get_items())
    assert len(items) == 3  # 3, since the parent is also in the sale

    sellables = set(i.sellable for i in items)
    assert sellables == {package.sellable, child1.sellable, child2.sellable}


@pytest.mark.usefixtures('open_till', 'mock_new_store')
def test_sale_new_client(client, sale_payload_new_client, example_creator, store):
    response = client.post('/sale', json=sale_payload_new_client)
    sale = store.find(Sale).order_by(Desc(Sale.open_date)).first()
    individual = store.find(Individual, cpf=sale_payload_new_client['client_document']).one()

    assert response.status_code == 201
    assert sale.id == response.json.get('sale_id')
    assert sale.client_id == response.json.get('client_id')
    assert sale.client.person == individual.person


def test_data_resource(client):
    response = client.get('/data')

    assert response.json['hotjar_id'] is None
    assert response.json['parameters']['NFCE_CAN_SEND_DIGITAL_INVOICE'] is False
    assert response.json['parameters']['NFE_SEFAZ_TIMEOUT'] == 10
    assert response.json['parameters']['PASSBOOK_FIDELITY'] is None
    assert response.json['parameters']['INCLUDE_CASH_FUND_ON_TILL_CLOSING'] is False
    assert response.json['parameters']['AUTOMATIC_LOGOUT'] == 0


# TODO: find a better way to test configs without using mock
@mock.patch('stoqserver.lib.restful.get_config')
def test_data_resource_with_hotjar_config(get_config_mock, client):
    get_config_mock.return_value.get.return_value = 'hotjar-id'

    response = client.get('/data')

    assert response.json['hotjar_id'] == 'hotjar-id'
    get_config_mock.assert_called_once_with()
    get_config_mock.return_value.get.assert_any_call('Hotjar', 'id')
    assert get_config_mock.return_value.get.call_count == 4


@mock.patch('stoqserver.lib.restful.api')
@pytest.mark.usefixtures('mock_get_plugin_manager')
def test_data_resource_with_send_digital_invoice_parameter_as_true(api_mock, client):
    api_mock.sysparam.get.return_value = True
    response = client.get('/data')
    assert response.json['parameters']['NFCE_CAN_SEND_DIGITAL_INVOICE'] is True


@mock.patch('stoqserver.lib.restful.api')
@pytest.mark.usefixtures('mock_get_plugin_manager')
def test_data_resource_with_send_digital_invoice_parameter_as_false(api_mock, client):
    api_mock.sysparam.get.return_value = False
    response = client.get('/data')
    assert response.json['parameters']['NFCE_CAN_SEND_DIGITAL_INVOICE'] is False


@mock.patch('stoqserver.lib.restful.api')
@pytest.mark.usefixtures('mock_get_plugin_manager')
def test_data_resource_with_default_nfe_sefaz_timeout(api_mock, client):
    api_mock.sysparam.get.return_value = 10
    response = client.get('/data')
    assert response.json['parameters']['NFE_SEFAZ_TIMEOUT'] == 10


@mock.patch('stoqserver.lib.restful.api')
@pytest.mark.usefixtures('mock_get_plugin_manager')
def test_data_resource_without_default_nfe_sefaz_timeout(api_mock, client):
    api_mock.sysparam.get.return_value = 666
    response = client.get('/data')
    assert response.json['parameters']['NFE_SEFAZ_TIMEOUT'] == 666


@mock.patch('stoqserver.lib.restful.api')
@pytest.mark.usefixtures('mock_get_plugin_manager')
def test_data_resource_without_passbook_slogan(api_mock, client):
    api_mock.sysparam.get.return_value = None
    response = client.get('/data')
    assert response.json['parameters']['PASSBOOK_FIDELITY'] is None


@mock.patch('stoqserver.lib.restful.api')
@pytest.mark.usefixtures('mock_get_plugin_manager')
def test_data_resource_with_passbook_slogan(api_mock, client):
    api_mock.sysparam.get.return_value = 'Main Pyke Loyalty Program'
    response = client.get('/data')
    assert response.json['parameters']['PASSBOOK_FIDELITY'] == 'Main Pyke Loyalty Program'


@mock.patch('stoqserver.lib.restful.api')
@pytest.mark.usefixtures('mock_get_plugin_manager')
def test_data_resource_without_cash_fund_on_till_closing(api_mock, client):
    api_mock.sysparam.get.return_value = False
    response = client.get('/data')
    assert response.json['parameters']['INCLUDE_CASH_FUND_ON_TILL_CLOSING'] is False


@mock.patch('stoqserver.lib.restful.api')
@pytest.mark.usefixtures('mock_get_plugin_manager')
def test_data_resource_with_cash_fund_on_till_closing(api_mock, client):
    api_mock.sysparam.get.return_value = True
    response = client.get('/data')
    assert response.json['parameters']['INCLUDE_CASH_FUND_ON_TILL_CLOSING'] is True


@mock.patch('stoqserver.lib.restful.api')
@pytest.mark.usefixtures('mock_get_plugin_manager')
def test_data_resource_without_automatic_logout(api_mock, client):
    api_mock.sysparam.get.return_value = 0
    response = client.get('/data')
    assert response.json['parameters']['AUTOMATIC_LOGOUT'] == 0


@mock.patch('stoqserver.lib.restful.api')
@pytest.mark.usefixtures('mock_get_plugin_manager')
def test_data_resource_with_automatic_logout(api_mock, client):
    api_mock.sysparam.get.return_value = 10
    response = client.get('/data')
    assert response.json['parameters']['AUTOMATIC_LOGOUT'] == 10


@mock.patch('stoqserver.lib.restful.api')
@pytest.mark.usefixtures('mock_new_store')
def test_data_resource_branch_override(api_mock, client, sellable, example_creator,
                                       current_station):
    # Mock necessary in order to execute the _get_parameters_ correctly
    api_mock.sysparam.get.return_value = False

    # Insert a category with high priority so that it appears first in our list
    category = example_creator.create_sellable_category()
    category.sort_order = 1000
    sellable.category = category

    # Sellable should be in the response when not forcing override
    api_mock.sysparam.get_bool.return_value = False
    response = client.get('/data')
    assert len(response.json['categories'][0]['products']) == 1
    assert response.json['categories'][0]['products'][0]['id'] == sellable.id

    # Now force branch override. Since this sellable does not have one, it should not be in the list
    api_mock.sysparam.get_bool.return_value = True
    response = client.get('/data')
    assert response.json['categories'][0]['products'] == []

    # Creating an override is not enought to make the sellable appear...
    override = ProductBranchOverride(store=sellable.store, product=sellable.product,
                                     branch=current_station.branch)
    response = client.get('/data')
    assert response.json['categories'][0]['products'] == []

    # .. it should also have an icms template to show up again
    override.icms_template = example_creator.create_product_icms_template()
    response = client.get('/data')
    assert len(response.json['categories'][0]['products']) == 1
    assert response.json['categories'][0]['products'][0]['id'] == sellable.id


@pytest.mark.usefixtures('mock_get_default_store', 'mock_new_store')
def test_data_resource_with_branch_price_table(client, sellable, example_creator, current_station):
    sellable.category = example_creator.create_sellable_category()
    response = client.get('/data')
    cat = None
    for cat in response.json['categories']:
        if cat['id'] == sellable.category.id:
            # 10 is the sellable default price
            assert cat['products'][0]['price'] == '10'
            break
    else:
        assert False, 'Sellable category is not present in the response'

    # Now lets add a price table for the current branch and set a special price for this sellable in
    # this table
    client_category = example_creator.create_client_category()
    branch = current_station.branch
    branch.default_client_category = client_category
    example_creator.create_client_category_price(category=client_category, sellable=sellable,
                                                 price=20)
    response = client.get('/data')
    for cat in response.json['categories']:
        if cat['id'] == sellable.category.id:
            assert cat['products'][0]['price'] == '20'
            break
    else:
        assert False, 'Sellable category is not present in the response'


@pytest.mark.parametrize('query_string', ({}, {'partial_document': None}, {'partial_document': ''}))
def test_passbook_users_get_missing_parameter(client, query_string):
    response = client.get('/passbook/users', query_string=query_string)

    assert response.status_code == 400
    assert 'Missing partial document' in response.json['message']


@pytest.mark.parametrize('partial_doc', ('1', '12', '1' * 12))
@mock.patch('stoqserver.lib.restful.PassbookUsersResource.get_current_branch')
@mock.patch('stoqserver.lib.restful.SearchForPassbookUsersByDocumentEvent.send')
def test_passbook_users_get_invalid_partial_document(
    mock_event_send, mock_get_branch, client, partial_doc, current_branch,
):
    mock_get_branch.return_value = current_branch
    mock_event_send.side_effect = ValueError('invalid partial document')

    response = client.get('/passbook/users', query_string={'partial_document': partial_doc})

    assert response.status_code == 400
    assert 'Invalid partial document' in response.json['message']
    mock_event_send.assert_called_once_with(current_branch, partial_document=partial_doc)


@mock.patch('stoqserver.lib.restful.PassbookUsersResource.get_current_branch')
@mock.patch('stoqserver.lib.restful.SearchForPassbookUsersByDocumentEvent.send')
def test_passbook_users_get(mock_event_send, mock_get_branch, client, current_branch):
    mock_get_branch.return_value = current_branch

    partial_doc = '666'
    users = [
        {'document': '66612345612', 'name': 'Cuca Beludo da Silva'},
        {'document': '66601234512', 'name': 'Dalva Gina de Carvalho'},
    ]
    mock_event_send.return_value = [(None, users)]

    response = client.get('/passbook/users', query_string={'partial_document': partial_doc})

    assert response.status_code == 200
    assert response.json == users
    mock_event_send.assert_called_once_with(current_branch, partial_document=partial_doc)


@pytest.mark.usefixtures('mock_get_default_store', 'mock_new_store')
def test_till_get_without_id(client, open_till):
    response = client.get('/till')

    assert response.status_code == 200
    assert response.json['id'] == open_till.id


@pytest.mark.usefixtures('mock_get_default_store', 'mock_new_store')
def test_till_get_with_open_till(client, open_till):
    response = client.get('/till/{}'.format(open_till.id))

    assert response.status_code == 200
    assert response.json['id'] == open_till.id
    assert response.json['status'] == Till.STATUS_OPEN


@pytest.mark.usefixtures('mock_get_default_store', 'mock_new_store')
def test_till_get_with_close_till(client, close_till):
    response = client.get('/till/{}'.format(close_till.id))

    assert response.status_code == 200
    assert response.json['id'] == close_till.id
    assert response.json['status'] == Till.STATUS_CLOSED


@pytest.mark.usefixtures('mock_get_default_store', 'mock_new_store')
def test_till_get_closing_receipt_with_open_till(client, open_till):
    response = client.get('/till/{}/closing_receipt'.format(open_till.id))

    assert response.status_code == 200
    assert not response.json


@mock.patch('stoqserver.lib.restful.GenerateTillClosingReceiptImageEvent.send')
@pytest.mark.usefixtures('mock_get_default_store', 'mock_new_store')
def test_till_get_closing_receipt_with_close_till(mock_get_receipt, client, close_till):
    fake_image = "eyJ1IjogInRlc3QifQ=="
    mock_get_receipt.return_value = [(None, fake_image)]

    response = client.get('/till/{}/closing_receipt'.format(close_till.id))

    assert response.status_code == 200
    assert response.json["id"] == close_till.id
    assert response.json["image"] == fake_image


# @mock.patch('stoqifood.ifoodui.IfoodClient.login')
# @mock.patch('stoqifood.ifoodui.IfoodClient.dispatch')
# @pytest.mark.usefixtures('open_till', 'mock_new_store')
# def test_post_sale_with_ifood_order(
#         mock_ifood_client_dispatch, mock_ifood_client_login, sale_payload,
#         ifood_order, client
# ):
#     mock_ifood_client_login.return_value = {'access_token': 'test'}
#     mock_ifood_client_dispatch.return_value = requests.codes.accepted
#     sale_payload['external_order_id'] = ifood_order.id
#
#     response = client.post('/sale', json=sale_payload)
#
#     assert mock_ifood_client_login.call_count == 1
#     assert mock_ifood_client_dispatch.call_count == 1
#     assert ifood_order.status == 'DISPATCHED'
#     assert response.status_code == 201


# @pytest.mark.usefixtures('open_till', 'mock_new_store')
# def test_post_sale_ifood_order_without_order_id(client, sale_payload, ifood_order):
#
#     response = client.post('/sale', json=sale_payload)
#
#     assert ifood_order.status == 'PLACED'
#     assert response.status_code == 201


@mock.patch('stoqserver.lib.restful.get_config')
@pytest.mark.usefixtures('open_till', 'mock_new_store')
def test_get_credit_providers_from_conf(get_config_mock, client, sale_payload):
    get_config_mock.return_value.get.return_value = 'PICPAY, PASSBOOK, ITI, UBER EATS'

    response = client.get('/data')
    credit_providers = ['PICPAY', 'PASSBOOK', 'ITI', 'UBER EATS']

    assert response.status_code == 200
    assert response.json['scrollable_list'] == credit_providers


@mock.patch('stoqserver.lib.restful.get_config')
@pytest.mark.usefixtures('open_till', 'mock_new_store')
def test_sale_hack_money_as_ifood(get_config_mock, client, sale_payload):
    # Mocks the get method from config to mark the station as a hacked station
    get_config_mock().get.side_effect = lambda section, name: \
        {'money_as_ifood': client.station.name}.get(name, None)

    # Money as payment method is ok
    response = client.post('/sale', json=sale_payload)
    assert response.status_code == 201
    assert 'sale_id' in response.json
    assert 'client_id' in response.json

    # Card as payment method is invalid
    sale_payload['payments'][0]['method'] = 'card'
    sale_payload['payments'][0]['card_type'] = 'credit'
    sale_payload['payments'][0]['provider'] = 'VISA'
    response = client.post('/sale', json=sale_payload)
    assert response.status_code == 422
    assert response.json['message'] == 'Payment method not allowed for this station'

    # There's no payment method restriction for a not hacked station
    get_config_mock().get.side_effect = lambda section, name: \
        {'money_as_ifood': 'not_a_hacked_station'}.get(name)

    sale_payload['payments'][0]['method'] = 'money'
    sale_payload['payments'][0]['card_type'] = None
    sale_payload['payments'][0]['provider'] = None
    response = client.post('/sale', json=sale_payload)
    assert response.status_code == 201
    assert 'sale_id' in response.json
    assert 'client_id' in response.json

    sale_payload['payments'][0]['method'] = 'card'
    sale_payload['payments'][0]['card_type'] = 'credit'
    sale_payload['payments'][0]['provider'] = 'VISA'
    response = client.post('/sale', json=sale_payload)
    assert response.status_code == 201
    assert 'sale_id' in response.json
    assert 'client_id' in response.json
