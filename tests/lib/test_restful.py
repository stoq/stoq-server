import json
import os
import tempfile
from unittest import mock

import pytest
from flask.testing import FlaskClient

from stoqserver.lib.restful import bootstrap_app
from stoqlib.lib.decorators import cached_property


class StoqTestClient(FlaskClient):
    @cached_property(ttl=0)
    def auth_token(self):
        rv = super().post(
            '/login',
            data={
                'user': self.user.username,
                'pw_hash': self.user.pw_hash,
                'station_name': self.station.name
            })
        ans = json.loads(rv.data.decode())
        return ans['token'].replace('JWT', 'Bearer')

    def post(self, *args, **kwargs):
        if 'json' in kwargs:
            kwargs['data'] = json.dumps(kwargs.pop('json'))

        return super().post(
            *args,
            **kwargs,
            headers={'Authorization': self.auth_token},
            content_type='application/json',
        )


# This is flask test client according to boilerplate:
# https://flask.palletsprojects.com/en/1.0.x/testing/
@pytest.fixture(scope='session')
def client(current_user, current_station):
    app = bootstrap_app()
    db_fd, app.config['DATABASE'] = tempfile.mkstemp()
    app.config['TESTING'] = True
    app.test_client_class = StoqTestClient
    client = app.test_client()
    client.user = current_user
    client.station = current_station

    yield client

    os.close(db_fd)
    os.unlink(app.config['DATABASE'])


@pytest.fixture
def new_store(store):
    store.commit = mock.Mock()
    store.close = mock.Mock()
    store.rollback = mock.Mock()
    return store


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
    }


@pytest.fixture
def kps_station(current_station):
    current_station.has_kps_enabled = True
    return current_station


@pytest.fixture()
def open_till(current_till, current_user):
    from stoqlib.domain.till import Till

    if current_till.status != Till.STATUS_OPEN:
        current_till.open_till(current_user)

    return current_till


@mock.patch('stoqserver.lib.restful.PrintKitchenCouponEvent.send')
@mock.patch('stoqserver.lib.restful.api.new_store')
@pytest.mark.parametrize('order_number', ('0', '', None))
@pytest.mark.usefixtures('kps_station', 'open_till')
def test_kps_sale_with_invalid_order_number(
        mock_new_store, mock_kps_event_send, client,
        new_store, order_number, sale_payload, sellable):

    mock_new_store.return_value = new_store
    sellable.requires_kitchen_production = True
    sale_payload['order_number'] = order_number

    rv = client.post('/sale', json=sale_payload)

    assert mock_kps_event_send.call_count == 0
    assert rv.status_code == 400


@mock.patch('stoqserver.lib.restful.PrintKitchenCouponEvent.send')
@mock.patch('stoqserver.lib.restful.api.new_store')
@pytest.mark.usefixtures('current_station')
def test_kps_sale_with_kps_station_disabled(
        mock_new_store, mock_kps_event_send, client,
        new_store, sale_payload):

    mock_new_store.return_value = new_store

    rv = client.post('/sale', json=sale_payload)

    assert mock_kps_event_send.call_count == 0
    assert rv.status_code == 200


@mock.patch('stoqserver.lib.restful.PrintKitchenCouponEvent.send')
@mock.patch('stoqserver.lib.restful.api.new_store')
@pytest.mark.usefixtures('open_till', 'kps_station')
def test_kps_sale_without_kitchen_items(
        mock_new_store, mock_kps_event_send, client,
        new_store, sale_payload):

    mock_new_store.return_value = new_store

    rv = client.post('/sale', json=sale_payload)

    assert mock_kps_event_send.call_count == 0
    assert rv.status_code == 200


@mock.patch('stoqserver.lib.restful.PrintKitchenCouponEvent.send')
@mock.patch('stoqserver.lib.restful.api.new_store')
@pytest.mark.usefixtures("kps_station")
def test_kps_sale(mock_new_store, mock_kps_event_send, client, new_store, sale_payload, sellable):
    mock_new_store.return_value = new_store
    sellable.requires_kitchen_production = True

    rv = client.post('/sale', json=sale_payload)

    assert rv.status_code == 200
    assert mock_kps_event_send.call_count == 1
    args, kwargs = mock_kps_event_send.call_args_list[0]
    assert len(args) == 1
    sale_items = list(args[0].get_items())
    assert sale_items[0].sellable == sellable
    assert kwargs == {'order_number': 69}
