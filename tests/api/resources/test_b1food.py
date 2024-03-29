import json
import pytest

from unittest import mock
from datetime import datetime
from storm.expr import Ne, Select

from stoqlib.domain.overrides import ProductBranchOverride
from stoqlib.domain.payment.card import CreditCardData, CreditProvider
from stoqlib.domain.payment.method import PaymentMethod
from stoqlib.domain.payment.payment import Payment
from stoqlib.domain.person import LoginUser
from stoqlib.domain.sale import Sale
from stoqlib.domain.sellable import Sellable
from stoqlib.domain.station import BranchStation
from stoqlib.domain.till import Till
from stoqlib.lib.formatters import raw_document
from stoqlib.lib.parameters import sysparam

from stoqserver.api.resources.b1food import (_check_if_uuid,
                                             _get_card_name,
                                             _get_card_description,
                                             _get_category_info,
                                             _get_payment_method_with_provider_code,
                                             _get_credit_provider_description,
                                             _get_payment_method_description,
                                             _get_payment_method_name,
                                             _get_person_names,
                                             generate_b1food_token)


@pytest.fixture
def sale(example_creator, current_user, current_station):
    test_sale = example_creator.create_sale()
    test_sale.branch = current_station.branch
    test_sale.open_date = datetime.strptime('2020-01-02', '%Y-%m-%d')
    test_sale.confirm_date = datetime.strptime('2020-01-02', '%Y-%m-%d')
    test_sale.invoice.key = '33200423335270000159650830000000181790066862'
    sale_item = example_creator.create_sale_item(test_sale)
    sale_item.price = 10
    sale_item.base_price = 15
    sellable_category = example_creator.create_sellable_category(description='Category 1')
    sale_item.sellable.category = sellable_category
    sale_item.sellable.code = '1111111111111'
    client = example_creator.create_client()
    client.person.individual.cpf = '737.948.760-40'
    test_sale.client = client
    person = example_creator.create_person()
    person.login_user = current_user
    test_sale.salesperson.person = person
    payment = example_creator.create_payment(group=test_sale.group, payment_type=Payment.TYPE_IN)
    payment.paid_value = 10
    card_payment = example_creator.create_card_payment(payment_type=Payment.TYPE_IN,
                                                       payment_value=5)
    card_payment.group = test_sale.group
    card_payment.paid_value = 5
    sale_item.icms_info.v_icms = 1
    sale_item.icms_info.p_icms = 18

    return test_sale


@pytest.fixture
def sale_with_cnpj(example_creator, current_user, current_station):
    test_sale = example_creator.create_sale()
    test_sale.branch = current_station.branch
    test_sale.open_date = datetime.strptime('2020-01-02', '%Y-%m-%d')
    test_sale.confirm_date = datetime.strptime('2020-01-02', '%Y-%m-%d')
    sale_item = example_creator.create_sale_item(test_sale)
    sale_item.price = 10
    sale_item.base_price = 15
    sellable_category = example_creator.create_sellable_category(description='Category 1')
    sale_item.sellable.category = sellable_category
    sale_item.sellable.code = '1111111111111'
    client = example_creator.create_client()
    company = example_creator.create_company()
    company.cnpj = '35.600.423/0001-27'
    client.person.individual = None
    test_sale.client = client
    test_sale.client.person.company = company
    person = example_creator.create_person()
    person.login_user = current_user
    test_sale.salesperson.person = person
    payment = example_creator.create_payment(group=test_sale.group)
    payment.payment_type = Payment.TYPE_IN
    payment.paid_value = 10
    sale_item.icms_info.v_icms = 1
    sale_item.icms_info.p_icms = 18

    return test_sale


@pytest.fixture
def sale_type_out(example_creator, current_user, current_station):
    test_sale = example_creator.create_sale()
    test_sale.branch = current_station.branch
    test_sale.open_date = datetime.strptime('2020-01-02', '%Y-%m-%d')
    test_sale.confirm_date = datetime.strptime('2020-01-02', '%Y-%m-%d')
    sale_item = example_creator.create_sale_item(test_sale)
    sale_item.price = 10
    sale_item.base_price = 15
    sellable_category = example_creator.create_sellable_category(description='Category 1')
    sale_item.sellable.category = sellable_category
    sale_item.sellable.code = '1111111111111'
    client = example_creator.create_client()
    client.person.individual.cpf = '737.948.760-40'
    test_sale.client = client
    person = example_creator.create_person()
    person.login_user = current_user
    test_sale.salesperson.person = person
    payment = example_creator.create_payment(group=test_sale.group)
    payment.payment_type = Payment.TYPE_OUT
    payment.paid_value = 10
    sale_item.icms_info.v_icms = 1
    sale_item.icms_info.p_icms = 18

    return test_sale


@pytest.fixture
def cancelled_sale(example_creator, current_user, current_station):
    sale = example_creator.create_sale()
    sale.status = Sale.STATUS_CANCELLED
    sale.branch = current_station.branch
    sale.open_date = datetime.strptime('2020-01-02', '%Y-%m-%d')
    sale.confirm_date = datetime.strptime('2020-01-02', '%Y-%m-%d')
    sale.invoice.key = '33200423335270000159650830000000181790066862'
    sale_item = example_creator.create_sale_item(sale)
    sale_item.price = 10
    sale_item.base_price = 15
    sellable_category = example_creator.create_sellable_category(description='Category 1')
    sale_item.sellable.category = sellable_category
    sale_item.sellable.code = '22222'
    client = example_creator.create_client()
    client.person.individual.cpf = '737.948.760-40'
    sale.client = client
    person = example_creator.create_person()
    person.login_user = current_user
    sale.salesperson.person = person
    payment = example_creator.create_payment(group=sale.group)
    payment.payment_type = Payment.TYPE_IN
    payment.paid_value = 10
    sale_item.icms_info.v_icms = 1
    sale_item.icms_info.p_icms = 18

    return sale


@pytest.fixture
def sellable(example_creator):
    sellable = example_creator.create_sellable()

    return sellable


@pytest.fixture
def open_till(current_till, current_user):
    if current_till.status != Till.STATUS_OPEN:
        current_till.open_till(current_user)

    return current_till


@pytest.fixture
def close_till(open_till, current_user):
    open_till.close_till(current_user)
    open_till.opening_date = datetime.strptime('2020-01-02 08:00', '%Y-%m-%d %H:%M')
    open_till.closing_date = datetime.strptime('2020-01-02 18:00', '%Y-%m-%d %H:%M')
    return open_till


@pytest.fixture
def network():
    return {
        'id': '35868887-3fae-11eb-9f78-40b89ae8d341',
        'name': 'Company name'
    }


@pytest.fixture
def client_category(example_creator):
    return example_creator.create_client_category()


@pytest.fixture
def branch_with_active_station(example_creator):
    return example_creator.create_branch()


@pytest.fixture
def branch_with_inactive_station(example_creator):
    return example_creator.create_branch()


@pytest.fixture
def active_station(example_creator, branch_with_active_station):
    return example_creator.create_station(branch=branch_with_active_station,
                                          is_active=True, name='active station')


@pytest.fixture
def inactive_station(example_creator, branch_with_inactive_station):
    return example_creator.create_station(branch=branch_with_inactive_station,
                                          is_active=False, name='inactive station')


@pytest.fixture
def inactive_station2(example_creator, branch_with_active_station):
    return example_creator.create_station(branch=branch_with_active_station,
                                          is_active=False, name='inactive station 2')


@mock.patch('stoqserver.api.resources.b1food.UUID')
def test_check_if_uuid_valid(abort):
    _check_if_uuid(['123'])
    assert abort.call_args_list[0][0][0] == '123'


@mock.patch('stoqserver.api.resources.b1food.abort')
def test_check_if_uuid_invalid(abort):
    _check_if_uuid(['123'])
    assert abort.call_args_list[0][0] == (400, 'os IDs das lojas devem ser do tipo UUID')


def test_get_credit_provider_description(example_creator):
    credit_provider = example_creator.create_credit_provider(short_name='Test')
    assert _get_credit_provider_description(credit_provider) == 'Test'


@pytest.mark.parametrize('size', (1, 10, 30, 128))
def test_generate_b1food_token(size):
    assert len(generate_b1food_token(size)) == size


@mock.patch('stoqserver.api.resources.b1food.get_config')
def test_b1food_success_login(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    query_string = {
        'response_type': 'token',
        'client_id': 'B1FoodClientId'
    }

    response = b1food_client.get('/b1food/oauth/authenticate',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert 'access_token' in res
    assert res['token_type'] == 'Bearer'
    assert res['expires_in'] == -1


@mock.patch('stoqserver.api.resources.b1food.get_config')
def test_b1food_login_without_client_id(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'response_type': 'token',
    }

    response = b1food_client.get('/b1food/oauth/authenticate',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 400
    assert res['message'] == 'Missing client_id'


@mock.patch('stoqserver.api.resources.b1food.get_config')
def test_login_with_invalid_client_id(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'response_type': 'token',
        'client_id': 'B1FoodInvalidClientId'
    }
    response = b1food_client.get('/b1food/oauth/authenticate',
                                 query_string=query_string)

    assert response.status_code == 403


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_income_center(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
    }
    response = b1food_client.get('b1food/terceiros/restful/centrosrenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_income_center_with_wrong_authorization(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "dasdadasded"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
    }
    response = b1food_client.get('b1food/terceiros/restful/centrosrenda',
                                 query_string=query_string)

    assert response.status_code == 401


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_sale_item_without_initial_date_arg(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtfim': '2020-01-01'
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 400
    assert res['message'] == "Missing parameter 'dtinicio'"


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_sale_item_without_end_date_arg(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01'
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 400
    assert res['message'] == "Missing parameter 'dtfim'"


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_sale_item_with_no_sales(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01'
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sale_item_with_usarDtMov_arg(get_config_mock, b1food_client, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    sale.confirm_date = datetime.strptime('2020-01-04', '%Y-%m-%d')
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'usarDtMov': 0
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res1 = json.loads(response.data.decode('utf-8'))

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'usarDtMov': 1
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res2 = json.loads(response.data.decode('utf-8'))

    assert len(res1) == 1
    assert len(res2) == 0


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sale_item_with_lojas_arg(get_config_mock, b1food_client, current_station, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'lojas': current_station.branch.id
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert len(res) == 1


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sale_item_with_lojas_filter(get_config_mock, b1food_client,
                                         current_station, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'lojas': [current_station.branch.id]
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert len(res) == 1


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_sale_item_with_consumidores_filter(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'consumidores': [97050782033, 70639759000102]
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_sale_item_with_operacaocupom_filter(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'operacaocupom': ['33200423335270000159650830000000181790066862']
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sale_item_successfully(get_config_mock, get_network_info,
                                    b1food_client, store, sale, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03'
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    item = sale.get_items()[0]
    sellable = item.sellable
    station = store.get(BranchStation, sale.station_id)
    salesperson = sale.salesperson
    document = raw_document(sale.get_client_document())

    assert response.status_code == 200
    assert res == [{
        'acrescimo': 0,
        'atendenteCod': salesperson.person.login_user.username,
        'atendenteId': salesperson.person.login_user.id,
        'atendenteNome': salesperson.person.name,
        'cancelado': False,
        'codMaterial': sellable.code,
        'codOrigem': None,
        'consumidores': [{'documento': document, 'tipo': 'CPF'}],
        'desconto': 5.0,
        'descricao': sellable.description,
        'dtLancamento': '2020-01-02',
        'grupo': {
            'ativo': True,
            'codigo': sellable.category.id,
            'dataAlteracao': sellable.category.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
            'descricao': sellable.category.description,
            'idGrupo': sellable.category.id,
            'idGrupoPai': sellable.category.category_id
        },
        'horaLancamento': '00:00',
        'idItemVenda': item.id,
        'idMaterial': sellable.id,
        'idOrigem': None,
        'isEntrega': False,
        'isGorjeta': False,
        'isRepique': False,
        'isTaxa': False,
        'lojaId': sale.branch.id,
        'maquinaCod': station.id,
        'maquinaId': station.id,
        'nomeMaquina': station.name,
        'operacaoId': sale.id,
        'quantidade': 1.0,
        'redeId': network['id'],
        'valorBruto': 15.0,
        'valorLiquido': 10.0,
        'valorUnitario': 15.0,
        'valorUnitarioLiquido': 10.0,
        'tipoDescontoId': None,
        'tipoDescontoCod': None,
        'tipoDescontoNome': None
    }]


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sale_item_with_cnpj_client_successfully(get_config_mock, b1food_client,
                                                     store, example_creator, sale_with_cnpj):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03'
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert res[0]['consumidores'] == [{'documento': '35600423000127', 'tipo': 'CNPJ'}]


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sale_item_with_empty_document(get_config_mock, b1food_client, store, sale):
    sale.client.person.individual.cpf = ''
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03'
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert res[0]['consumidores'] == [{'documento': '', 'tipo': ''}]


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sale_item_cancelled_false(get_config_mock, b1food_client, store, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    sale.status = Sale.STATUS_CANCELLED
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'cancelados': 0
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sale_item_cancelled_true(get_config_mock, b1food_client, store, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    sale.status = Sale.STATUS_CANCELLED
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'cancelados': 1
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert len(res) == 1
    assert res[0]['cancelado'] is True


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sellables(get_config_mock, get_network_info, b1food_client,
                       store, sale, sellable, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network

    delivery = sysparam.get_object(store, 'DELIVERY_SERVICE')
    sellables = store.find(Sellable, Ne(Sellable.id, delivery.sellable.id))

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
    }
    response = b1food_client.get('b1food/terceiros/restful/material',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert len(res) == sellables.count()

    res_item = [item for item in res if item['idMaterial'] == sellable.id]
    assert res_item == [{
        'idMaterial': sellable.id,
        'codigo': sellable.code,
        'descricao': sellable.description,
        'unidade': sellable.unit,
        'dataAlteracao': sellable.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'ativo': sellable.status == Sellable.STATUS_AVAILABLE,
        'redeId': network['id'],
        'lojaId': None,
        'isTaxa': False,
        'isRepique': False,
        'isGorjeta': False,
        'isEntrega': False,
        'grupo': _get_category_info(sellable)
    }]


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sellables_with_lojas_filter(get_config_mock, get_network_info, b1food_client,
                                         store, sale, current_station, sellable, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network

    branch_id = current_station.branch.id
    ProductBranchOverride(store=store, product=sellable.product, branch_id=branch_id)

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'lojas': [current_station.branch.id]
    }
    response = b1food_client.get('b1food/terceiros/restful/material',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert len(res) == 1

    res_item = [item for item in res if item['idMaterial'] == sellable.id]
    assert res_item == [{
        'idMaterial': sellable.id,
        'codigo': sellable.code,
        'descricao': sellable.description,
        'unidade': sellable.unit,
        'dataAlteracao': sellable.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'ativo': sellable.status == Sellable.STATUS_AVAILABLE,
        'redeId': network['id'],
        'lojaId': branch_id,
        'isTaxa': False,
        'isRepique': False,
        'isGorjeta': False,
        'isEntrega': False,
        'grupo': _get_category_info(sellable)
    }]


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sellables_with_lojas_filter_without_pbo(get_config_mock, get_network_info,
                                                     b1food_client, store, sale, current_station,
                                                     sellable, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network

    delivery = sysparam.get_object(store, 'DELIVERY_SERVICE')
    sellables = store.find(Sellable, Ne(Sellable.id, delivery.sellable.id))
    branch_id = current_station.branch.id

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'lojas': [current_station.branch.id]
    }
    response = b1food_client.get('b1food/terceiros/restful/material',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert len(res) == sellables.count()

    res_item = [item for item in res if item['idMaterial'] == sellable.id]
    assert res_item == [{
        'idMaterial': sellable.id,
        'codigo': sellable.code,
        'descricao': sellable.description,
        'unidade': sellable.unit,
        'dataAlteracao': sellable.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'ativo': sellable.status == Sellable.STATUS_AVAILABLE,
        'redeId': network['id'],
        'lojaId': branch_id,
        'isTaxa': False,
        'isRepique': False,
        'isGorjeta': False,
        'isEntrega': False,
        'grupo': _get_category_info(sellable)
    }]


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sellables_with_lojas_filter_branch_not_found(get_config_mock, get_network_info,
                                                          b1food_client, store, sale,
                                                          current_station, sellable, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network

    branch_id = 'e78a5f80-9b17-4b31-85e9-f3ebbdfc15fa'
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'lojas': [branch_id]
    }
    response = b1food_client.get('b1food/terceiros/restful/material',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 404
    msg = "Branch(es) ['{}'] not found".format(branch_id)
    assert msg in res['message']


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sellables_available(get_config_mock, get_network_info, b1food_client,
                                 store, sale, sellable, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network

    sellables = Sellable.get_available_sellables(store)
    sellable.status = Sellable.STATUS_CLOSED

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 1
    }
    response = b1food_client.get('b1food/terceiros/restful/material',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert len(res) == sellables.count()

    res_unavailable = [item for item in res if item['ativo'] is False]
    assert len(res_unavailable) == 0


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sellables_unavailable(get_config_mock, get_network_info, b1food_client,
                                   store, sale, sellable, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network

    sellable.status = Sellable.STATUS_CLOSED
    unavailable_sellables = store.find(Sellable, Sellable.status != Sellable.STATUS_AVAILABLE)

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 0
    }
    response = b1food_client.get('b1food/terceiros/restful/material',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert len(res) == unavailable_sellables.count()

    res_available = [item for item in res if item['ativo'] is True]
    assert len(res_available) == 0


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payment_with_lojas_filter(get_config_mock, b1food_client, store,
                                       current_station, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'lojas': [current_station.branch.id]
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    payments = store.find(Payment)

    assert payments.count() > 1
    assert len(res) == 1


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_payment_with_consumidores_filter(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'consumidores': [97050782033, 70639759000102]
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_payment_with_operacaocupom_filter(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'operacaocupom': [
            '33200423335270000159650830000000181790066862'
        ]
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payment_with_cnpj_client_successfully(get_config_mock, b1food_client,
                                                   store, example_creator, sale_with_cnpj):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert res[0]['consumidores'] == [{'documento': '35600423000127', 'tipo': 'CNPJ'}]


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payment_with_empty_document(get_config_mock, b1food_client, store, sale):
    sale.client.person.individual.cpf = ''
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03'
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert res[0]['consumidores'] == [{'documento': '', 'tipo': ''}]


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payments_successfully(get_config_mock, get_network_info,
                                   b1food_client, store, sale, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03'
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))
    salesperson = sale.salesperson
    payment = sale.group.payments[0]
    card_payment = sale.group.payments[1]
    document = raw_document(sale.get_client_document())
    card_data = card_payment.card_data
    provider = card_data.provider
    card_type = card_data.card_type
    assert response.status_code == 200
    assert res == [
        {
            'idMovimentoCaixa': sale.id,
            'redeId': network['id'],
            'rede': network['name'],
            'lojaId': sale.branch.id,
            'loja': sale.branch.name,
            'hora': '00',
            'cancelado': sale.status == Sale.STATUS_CANCELLED,
            'idAtendente': salesperson.person.login_user.id,
            'codAtendente': salesperson.person.login_user.username,
            'nomeAtendente': sale.salesperson.person.name,
            'vlDesconto': 0.0,
            'vlAcrescimo': 0.0,
            'vlTotalReceber': 0.0,
            'vlTotalRecebido': 15.0,
            'vlTrocoFormasPagto': 0.0,
            'vlServicoRecebido': 0,
            'vlRepique': 0,
            'vlTaxaEntrega': 0,
            'numPessoas': 1,
            'operacaoId': sale.id,
            'maquinaId': sale.station.id,
            'nomeMaquina': sale.station.name,
            'maquinaCod': payment.station.id,
            'maquinaPortaFiscal': None,
            'meiosPagamento': [
                {
                    'id': payment.method.id,
                    'codigo': payment.method.id,
                    'nome': _get_payment_method_name(payment.method.method_name),
                    'descricao': _get_payment_method_description(payment.method),
                    'valor': float(payment.paid_value),
                    'troco': float(payment.base_value - payment.value),
                    'valorRecebido': float(payment.value),
                    'idAtendente': sale.salesperson.person.login_user.id,
                    'codAtendente': sale.salesperson.person.login_user.username,
                    'nomeAtendente': sale.salesperson.person.name,
                },
                {
                    'id': _get_payment_method_with_provider_code(card_type, provider),
                    'codigo': _get_payment_method_with_provider_code(card_type, provider),
                    'nome': _get_card_name(card_payment.card_data.card_type,
                                           card_payment.card_data.provider.short_name),
                    'descricao': _get_card_description(card_payment.card_data.card_type,
                                                       card_payment.card_data.provider.short_name),
                    'valor': float(card_payment.paid_value),
                    'troco': float(card_payment.base_value - card_payment.value),
                    'valorRecebido': float(card_payment.value),
                    'idAtendente': sale.salesperson.person.login_user.id,
                    'codAtendente': sale.salesperson.person.login_user.username,
                    'nomeAtendente': sale.salesperson.person.name,
                }
            ],
            'consumidores': [
                {
                    'documento': document,
                    'tipo': 'CPF'
                }
            ],
            'dataContabil': '2020-01-02 00:00:00 -0300',
            'periodoId': None,
            'periodoCod': None,
            'periodoNome': None,
            'centroRendaId': None,
            'centroRendaCod': None,
            'centroRendaNome': None
        },
    ]


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payments_active(get_config_mock, get_network_info, b1food_client,
                             store, cancelled_sale, sale, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'ativo': 1
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))
    salesperson = sale.salesperson
    payment = sale.group.payments[0]
    card_payment = sale.group.payments[1]
    document = raw_document(sale.get_client_document())
    provider = card_payment.card_data.provider
    card_type = card_payment.card_data.card_type
    assert response.status_code == 200
    assert res == [
        {
            'codAtendente': salesperson.person.login_user.username,
            'consumidores': [
                {
                    'documento': document,
                    'tipo': 'CPF'
                }
            ],
            'dataContabil': '2020-01-02 00:00:00 -0300',
            'hora': '00',
            'cancelado': sale.status == Sale.STATUS_CANCELLED,
            'idAtendente': salesperson.person.login_user.id,
            'idMovimentoCaixa': sale.id,
            'loja': sale.branch.name,
            'lojaId': sale.branch.id,
            'maquinaCod': payment.station.id,
            'maquinaId': sale.station.id,
            'maquinaPortaFiscal': None,
            'meiosPagamento': [
                {
                    'id': payment.method.id,
                    'codigo': payment.method.id,
                    'nome': _get_payment_method_name(payment.method.method_name),
                    'descricao': _get_payment_method_description(payment.method),
                    'valor': float(payment.paid_value),
                    'troco': float(payment.base_value - payment.value),
                    'valorRecebido': float(payment.value),
                    'idAtendente': sale.salesperson.person.login_user.id,
                    'codAtendente': sale.salesperson.person.login_user.username,
                    'nomeAtendente': sale.salesperson.person.name,
                },
                {
                    'id': _get_payment_method_with_provider_code(card_type, provider),
                    'codigo': _get_payment_method_with_provider_code(card_type, provider),
                    'nome': _get_card_name(card_payment.card_data.card_type,
                                           card_payment.card_data.provider.short_name),
                    'descricao': _get_card_description(card_payment.card_data.card_type,
                                                       card_payment.card_data.provider.short_name),
                    'valor': float(card_payment.paid_value),
                    'troco': float(card_payment.base_value - card_payment.value),
                    'valorRecebido': float(card_payment.value),
                    'idAtendente': sale.salesperson.person.login_user.id,
                    'codAtendente': sale.salesperson.person.login_user.username,
                    'nomeAtendente': sale.salesperson.person.name,
                }
            ],
            'nomeAtendente': sale.salesperson.person.name,
            'nomeMaquina': sale.station.name,
            'numPessoas': 1,
            'operacaoId': sale.id,
            'rede': network['name'],
            'redeId': network['id'],
            'vlAcrescimo': 0.0,
            'vlTotalReceber': 0.0,
            'vlTotalRecebido': 15.0,
            'vlDesconto': 0.0,
            'vlRepique': 0,
            'vlServicoRecebido': 0,
            'vlTaxaEntrega': 0,
            'vlTrocoFormasPagto': 0,
            'periodoId': None,
            'periodoCod': None,
            'periodoNome': None,
            'centroRendaId': None,
            'centroRendaCod': None,
            'centroRendaNome': None
        },
    ]


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payments_inactive(get_config_mock, get_network_info, b1food_client,
                               store, sale, cancelled_sale, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'ativo': 0
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))
    salesperson = cancelled_sale.salesperson
    payment = cancelled_sale.group.payments[0]
    document = raw_document(cancelled_sale.get_client_document())
    assert response.status_code == 200
    assert res == [
        {
            'codAtendente': salesperson.person.login_user.username,
            'consumidores': [
                {
                    'documento': document,
                    'tipo': 'CPF'
                }
            ],
            'dataContabil': '2020-01-02 00:00:00 -0300',
            'hora': '00',
            'cancelado': cancelled_sale.status == Sale.STATUS_CANCELLED,
            'idAtendente': salesperson.person.login_user.id,
            'idMovimentoCaixa': cancelled_sale.id,
            'loja': cancelled_sale.branch.name,
            'lojaId': cancelled_sale.branch.id,
            'maquinaCod': payment.station.id,
            'maquinaId': cancelled_sale.station.id,
            'maquinaPortaFiscal': None,
            'meiosPagamento': [
                {
                    'id': payment.method.id,
                    'codigo': payment.method.id,
                    'nome': _get_payment_method_name(payment.method.method_name),
                    'descricao': _get_payment_method_description(payment.method),
                    'valor': float(payment.paid_value),
                    'troco': float(payment.base_value - payment.value),
                    'valorRecebido': float(payment.value),
                    'idAtendente': cancelled_sale.salesperson.person.login_user.id,
                    'codAtendente': cancelled_sale.salesperson.person.login_user.username,
                    'nomeAtendente': cancelled_sale.salesperson.person.name,
                }
            ],
            'nomeAtendente': cancelled_sale.salesperson.person.name,
            'nomeMaquina': cancelled_sale.station.name,
            'numPessoas': 1,
            'operacaoId': cancelled_sale.id,
            'rede': network['name'],
            'redeId': network['id'],
            'vlAcrescimo': 0.0,
            'vlTotalReceber': 0.0,
            'vlTotalRecebido': 10.0,
            'vlDesconto': 0.0,
            'vlRepique': 0,
            'vlServicoRecebido': 0,
            'vlTaxaEntrega': 0,
            'vlTrocoFormasPagto': 0,
            'periodoId': None,
            'periodoCod': None,
            'periodoNome': None,
            'centroRendaId': None,
            'centroRendaCod': None,
            'centroRendaNome': None
        },
    ]


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payment_with_type_out(get_config_mock, b1food_client,
                                   store, example_creator, sale_type_out):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
    }

    with pytest.raises(Exception) as error:
        response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                     query_string=query_string)

        assert response.status_code == 500
        assert "Inconsistent database, please contact support." in str(error.value)


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payments_cancelled_false(get_config_mock, b1food_client, store, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    sale.status = Sale.STATUS_CANCELLED
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'cancelados': 0
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payments_cancelled_true(get_config_mock, b1food_client, store, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    sale.status = Sale.STATUS_CANCELLED
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'cancelados': 1
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert len(res) == 1
    assert res[0]['cancelado'] is True


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_stations_successfully(get_config_mock, get_network_info,
                                   b1food_client, active_station, network):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
    }

    response = b1food_client.get('/b1food/terceiros/restful/terminais',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))
    res_item = [item for item in res if item['id'] == active_station.id]

    assert res_item == [
        {
            'apelido': active_station.name,
            'ativo': active_station.is_active,
            'codigo': active_station.id,
            'id': active_station.id,
            'lojaId': active_station.branch.id,
            'nome': active_station.name,
            'portaFiscal': None,
            'redeId': network['id'],
            'dataAlteracao': active_station.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
            'dataCriacao': active_station.te.te_time.strftime('%Y-%m-%d %H:%M:%S -0300'),
        }
    ]


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_inactive_stations(get_config_mock, get_network_info,
                               b1food_client, inactive_station, network):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 0,
    }

    response = b1food_client.get('/b1food/terceiros/restful/terminais',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))
    res_item = [item for item in res if item['id'] == inactive_station.id]

    assert res_item == [
        {
            'apelido': inactive_station.name,
            'ativo': inactive_station.is_active,
            'codigo': inactive_station.id,
            'id': inactive_station.id,
            'lojaId': inactive_station.branch.id,
            'nome': inactive_station.name,
            'portaFiscal': None,
            'redeId': network['id'],
            'dataAlteracao': inactive_station.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
            'dataCriacao': inactive_station.te.te_time.strftime('%Y-%m-%d %H:%M:%S -0300'),
        }
    ]


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_active_stations_from_branch(get_config_mock, get_network_info, b1food_client, store,
                                         inactive_station, active_station, inactive_station2,
                                         network):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 1,
        'lojas': active_station.branch.id
    }

    response = b1food_client.get('/b1food/terceiros/restful/terminais',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    stations = store.find(BranchStation, branch_id=active_station.branch.id)

    assert stations.count() == 2
    assert len(res) == 1
    assert res == [
        {
            'apelido': active_station.name,
            'ativo': active_station.is_active,
            'codigo': active_station.id,
            'id': active_station.id,
            'lojaId': active_station.branch.id,
            'nome': active_station.name,
            'portaFiscal': None,
            'redeId': network['id'],
            'dataAlteracao': active_station.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
            'dataCriacao': active_station.te.te_time.strftime('%Y-%m-%d %H:%M:%S -0300'),
        }
    ]


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_stations_branch(get_config_mock, get_network_info, b1food_client, store,
                             active_station, inactive_station2, network):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'lojas': active_station.branch.id
    }

    response = b1food_client.get('/b1food/terceiros/restful/terminais',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    branch_stations = store.find(BranchStation, branch_id=active_station.branch.id)

    assert len(res) == 2
    assert branch_stations.count() == 2


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_receipts_with_lojas_filter(get_config_mock, b1food_client, store,
                                        current_station, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'lojas': [current_station.branch.id]
    }
    response = b1food_client.get('b1food/terceiros/restful/comprovante',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    sales = store.find(Sale)

    assert sales.count() > 1
    assert len(res) == 1


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_receipts_with_consumidores_filter(get_config_mock, b1food_client, store, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'consumidores': [sale.get_client_document()]
    }
    response = b1food_client.get('b1food/terceiros/restful/comprovante',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    sales = store.find(Sale)

    assert sales.count() > 1
    assert len(res) == 1


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_receipts_with_operacaocupom_filter(get_config_mock, b1food_client, store, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'operacaocupom': [sale.invoice.key]
    }
    response = b1food_client.get('b1food/terceiros/restful/comprovante',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    sales = store.find(Sale)

    assert len(res) == 1
    assert sales.count() == 4


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_receipts_with_usarDtMov_filter(get_config_mock, b1food_client, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    sale.confirm_date = datetime.strptime('2020-01-04', '%Y-%m-%d')
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'usarDtMov': 0
    }
    response = b1food_client.get('b1food/terceiros/restful/comprovante',
                                 query_string=query_string)
    res1 = json.loads(response.data.decode('utf-8'))

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'usarDtMov': 1
    }
    response = b1food_client.get('b1food/terceiros/restful/comprovante',
                                 query_string=query_string)
    res2 = json.loads(response.data.decode('utf-8'))

    assert len(res1) == 1
    assert len(res2) == 0


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_receipts_successfully(get_config_mock, b1food_client, store, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03'
    }
    response = b1food_client.get('b1food/terceiros/restful/comprovante',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))
    item = sale.get_items()[0]
    discount = item.item_discount
    payment = sale.group.payments[0]
    card_payment = sale.group.payments[1]
    provider = card_payment.card_data.provider
    card_type = card_payment.card_data.card_type
    assert response.status_code == 200
    assert res == [
        {
            'maquinaCod': sale.station.id,
            'nomeMaquina': sale.station.name,
            'nfNumero': sale.invoice.invoice_number,
            'nfSerie': sale.invoice.series,
            'denominacao': sale.invoice.mode,
            'valor': sale.total_amount,
            'maquinaId': sale.station.id,
            'desconto': float(sale.discount_value),
            'acrescimo': float(-1 * min(discount, 0)),
            'chaveNfe': sale.invoice.key,
            'dataContabil': sale.confirm_date.strftime('%Y-%m-%d'),
            'dataEmissao': sale.confirm_date.strftime('%Y-%m-%d %H:%M:%S -0300'),
            'idOperacao': sale.id,
            'troco': 0.0,
            'pagamentos': float(sale.paid),
            'dataMovimento': sale.confirm_date.strftime('%Y-%m-%d %H:%M:%S -0300'),
            'cancelado': True if sale.cancel_date else False,
            'detalhes': [
                {
                    'ordem': None,
                    'idMaterial': item.sellable.id,
                    'codigo': item.sellable.code,
                    'desconto': float(item.item_discount),
                    'descricao': item.sellable.description,
                    'quantidade': float(item.quantity),
                    'valorBruto': float(item.base_price * item.quantity),
                    'valorUnitario': float(item.base_price),
                    'valorUnitarioLiquido': float(item.price),
                    'valorLiquido': float(item.price * item.quantity),
                    'codNcm': item.sellable.product.ncm,
                    'idOrigem': None,
                    'codOrigem': None,
                    'cfop': str(item.cfop.code),
                    'acrescimo': 0.0,
                    'cancelado': True if sale.cancel_date else False,
                    'maquinaId': sale.station.id,
                    'nomeMaquina': sale.station.name,
                    'maquinaCod': sale.station.id,
                    'isTaxa': None,
                    'isRepique': None,
                    'isGorjeta': None,
                    'isEntrega': None,
                }
            ],
            'meios': [
                {
                    'id': payment.method.id,
                    'codigo': payment.method.id,
                    'nome': _get_payment_method_name(payment.method.method_name),
                    'descricao': _get_payment_method_description(payment.method),
                    'valor': float(payment.paid_value),
                    'troco': float(payment.base_value - payment.value),
                    'valorRecebido': float(payment.value),
                    'idAtendente': sale.salesperson.person.login_user.id,
                    'codAtendente': sale.salesperson.person.login_user.username,
                    'nomeAtendente': sale.salesperson.person.name,
                },
                {
                    'id': _get_payment_method_with_provider_code(card_type, provider),
                    'codigo': _get_payment_method_with_provider_code(card_type, provider),
                    'nome': _get_card_name(card_payment.card_data.card_type,
                                           card_payment.card_data.provider.short_name),
                    'descricao': _get_card_description(card_payment.card_data.card_type,
                                                       card_payment.card_data.provider.short_name),
                    'valor': float(card_payment.paid_value),
                    'troco': float(card_payment.base_value - card_payment.value),
                    'valorRecebido': float(card_payment.value),
                    'idAtendente': sale.salesperson.person.login_user.id,
                    'codAtendente': sale.salesperson.person.login_user.username,
                    'nomeAtendente': sale.salesperson.person.name,
                }
            ],
        }
    ]


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_receipts_cancelled_false(get_config_mock, b1food_client, store, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    sale.status = Sale.STATUS_CANCELLED
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'cancelados': 0
    }
    response = b1food_client.get('b1food/terceiros/restful/comprovante',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_receipts_cancelled_true(get_config_mock, b1food_client, store, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    sale.status = Sale.STATUS_CANCELLED
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03',
        'cancelados': 1
    }
    response = b1food_client.get('b1food/terceiros/restful/comprovante',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert len(res) == 1
    assert res[0]['cancelado'] is True


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payment_methods(get_config_mock, get_network_info,
                             b1food_client, store, sale, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network
    payment_methods = store.find(PaymentMethod)
    payment_method = store.find(PaymentMethod, method_name='money').one()
    provider = CreditProvider(store=store, short_name='TESTE')
    CreditCardData(store=store, card_type='credit', provider=provider)

    query_string = {'Authorization': 'Bearer B1FoodClientId'}
    response = b1food_client.get('b1food/terceiros/restful/meio-pagamento',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200

    select = Select((CreditCardData.card_type, CreditCardData.provider_id), distinct=True)
    credit_providers = store.execute(select)
    # -1 because 'card' payment_method is replaced by the credit providers
    assert len(res) == payment_methods.count() + credit_providers.rowcount - 1

    res_item_payment_method = [item for item in res if item['id'] == payment_method.id]
    assert res_item_payment_method == [{
        'ativo': payment_method.is_active,
        'id': payment_method.id,
        'codigo': payment_method.id,
        'nome': _get_payment_method_name(payment_method.method_name),
        'redeId': network['id'],
        'lojaId': None
    }]

    credit_provider = credit_providers.get_one()
    card_type = credit_provider[0]
    provider_id = credit_provider[1]
    provider = store.get(CreditProvider, provider_id)
    provider_code = _get_payment_method_with_provider_code(card_type, provider)
    res_item_credit_provider = [item for item in res if item['id'] == provider_code]
    assert res_item_credit_provider == [{
        'ativo': provider.visible,
        'id': provider_code,
        'codigo': provider_code,
        'nome': _get_card_name(card_type, provider.short_name),
        'redeId': network['id'],
        'lojaId': None
    }]


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payment_methods_active(get_config_mock, get_network_info,
                                    b1food_client, store, sale, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network
    payment_methods_active = PaymentMethod.get_active_methods(store)
    payment_method_active = payment_methods_active[0]

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 1
    }
    response = b1food_client.get('b1food/terceiros/restful/meio-pagamento',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200

    select = Select((CreditCardData.card_type, CreditCardData.provider_id), distinct=True)
    credit_providers_count = store.execute(select).rowcount
    assert len(res) == len(payment_methods_active) + credit_providers_count - 1

    assert res[0] == {
        'ativo': payment_method_active.is_active,
        'id': payment_method_active.id,
        'codigo': payment_method_active.id,
        'nome': _get_payment_method_name(payment_method_active.method_name),
        'redeId': network['id'],
        'lojaId': None
    }


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payment_methods_active_card_inactive(get_config_mock, get_network_info,
                                                  b1food_client, store, sale, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network
    payment_methods = store.find(PaymentMethod)

    card_payment_method = payment_methods.find(method_name='card').one()
    card_payment_method.is_active = False

    payment_methods_active = payment_methods.find(is_active=True)
    payment_method_active = payment_methods_active.any()

    provider_visible = CreditProvider(store=store, short_name='VISIBLE PROVIDER', visible=True)
    CreditCardData(store=store, card_type='credit', provider=provider_visible)
    provider_not_visible = CreditProvider(store=store, short_name='NOT VISIBLE PROVIDER',
                                          visible=False)
    CreditCardData(store=store, card_type='credit', provider=provider_not_visible)

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 1
    }
    response = b1food_client.get('b1food/terceiros/restful/meio-pagamento',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200
    assert len(res) == payment_methods_active.count()

    assert not any(res_item['id'] == card_payment_method.id for res_item in res)

    res_item = {
        'ativo': payment_method_active.is_active,
        'id': payment_method_active.id,
        'codigo': payment_method_active.id,
        'nome': _get_payment_method_name(payment_method_active.method_name),
        'redeId': network['id'],
        'lojaId': None
    }
    assert res_item in res


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payment_methods_inactive(get_config_mock, get_network_info,
                                      b1food_client, store, sale, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network

    payment_method = store.find(PaymentMethod, method_name='money').one()
    payment_method.is_active = False

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 0
    }
    response = b1food_client.get('b1food/terceiros/restful/meio-pagamento',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert len(res) == 1

    assert res[0] == {
        'ativo': payment_method.is_active,
        'id': payment_method.id,
        'codigo': payment_method.id,
        'nome': _get_payment_method_name(payment_method.method_name),
        'redeId': network['id'],
        'lojaId': None
    }


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payment_methods_inactive_card_active(get_config_mock, get_network_info,
                                                  b1food_client, store, sale, network):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    get_network_info.return_value = network
    payment_methods = store.find(PaymentMethod)

    inactive_payment_method = payment_methods.find(method_name='money').one()
    inactive_payment_method.is_active = False

    card_payment_method = payment_methods.find(method_name='card')
    card_payment_method.is_active = True

    provider_visible = CreditProvider(store=store, short_name='VISIBLE PROVIDER', visible=True)
    ccd = CreditCardData(store=store, card_type='credit', provider=provider_visible)
    provider_not_visible = CreditProvider(store=store, short_name='NOT VISIBLE PROVIDER',
                                          visible=False)
    credit_card_data = CreditCardData(store=store, card_type='credit',
                                      provider=provider_not_visible)

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 0
    }
    response = b1food_client.get('b1food/terceiros/restful/meio-pagamento',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert response.status_code == 200
    assert len(res) == 2

    res_item_payment_method = {
        'ativo': inactive_payment_method.is_active,
        'id': inactive_payment_method.id,
        'codigo': inactive_payment_method.id,
        'nome': _get_payment_method_name(inactive_payment_method.method_name),
        'redeId': network['id'],
        'lojaId': None
    }
    assert res_item_payment_method in res

    res_item_credit_provider = {
        'ativo': False,
        'id': _get_payment_method_with_provider_code(ccd.card_type, provider_not_visible),
        'codigo': _get_payment_method_with_provider_code(ccd.card_type, provider_not_visible),
        'nome': _get_card_name(credit_card_data.card_type,
                               provider_not_visible.short_name),
        'redeId': network['id'],
        'lojaId': None
    }
    assert res_item_credit_provider in res


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_tills_successfully(get_config_mock, get_network_info,
                                b1food_client, close_till, network):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
    }

    response = b1food_client.get('/b1food/terceiros/restful/periodos',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
def test_get_user_profile_successfully(get_config_mock, get_network_info, b1food_client,
                                       current_user, network):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    profile = current_user.profile
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
    }

    response = b1food_client.get('/b1food/terceiros/restful/cargos',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert len(res) > 0
    assert res[0] == {
        'ativo': True,
        'id': profile.id,
        'codigo': profile.id,
        'dataCriacao': profile.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'dataAlteracao': profile.te.te_time.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'nome': profile.name,
        'redeId': network['id'],
        'lojaId': None,
    }


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
def test_get_user_profile_active(get_config_mock, get_network_info, b1food_client,
                                 current_user, network):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network
    profile = current_user.profile
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 1
    }

    response = b1food_client.get('/b1food/terceiros/restful/cargos',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert len(res) > 0
    assert res[0] == {
        'ativo': True,
        'id': profile.id,
        'codigo': profile.id,
        'dataCriacao': profile.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'dataAlteracao': profile.te.te_time.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'nome': profile.name,
        'redeId': network['id'],
        'lojaId': None,
    }


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_user_profile_inactive(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 0
    }

    response = b1food_client.get('/b1food/terceiros/restful/cargos',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
def test_get_branches_successfully(get_config_mock, get_network_info,
                                   b1food_client, network):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
    }

    response = b1food_client.get('/b1food/terceiros/restful/rede-loja',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert len(res) > 0
    assert res[0]['idRede'] == network['id']
    assert res[0]['nome'] == network['name']
    assert res[0]['ativo'] is True
    assert len(res[0]['lojas']) > 0
    assert 'idLoja' in res[0]['lojas'][0]
    assert 'nome' in res[0]['lojas'][0]
    assert 'ativo' in res[0]['lojas'][0]


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
def test_get_branches_only_active(get_config_mock, get_network_info,
                                  b1food_client, network):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': '1',
    }

    response = b1food_client.get('/b1food/terceiros/restful/rede-loja',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert len(res) > 0
    assert res[0]['idRede'] == network['id']
    assert res[0]['nome'] == network['name']
    assert res[0]['ativo'] is True
    assert len(res[0]['lojas']) > 0
    assert 'idLoja' in res[0]['lojas'][0]
    assert 'nome' in res[0]['lojas'][0]
    assert 'ativo' in res[0]['lojas'][0]
    assert res[0]['lojas'][0]['ativo'] is True


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_discount_categories_successfully(get_config_mock, get_network_info,
                                              b1food_client, network, client_category):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
    }

    response = b1food_client.get('/b1food/terceiros/restful/tiposdescontos',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert len(res) > 0
    assert res[0] == {
        'ativo': True,
        'id': client_category.id,
        'codigo': client_category.id,
        'dataCriacao': client_category.te.te_time.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'dataAlteracao': client_category.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'nome': client_category.name,
        'redeId': network['id'],
        'lojaId': None
    }


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_discount_categories_active(get_config_mock, get_network_info,
                                        b1food_client, network, client_category):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 1
    }

    response = b1food_client.get('/b1food/terceiros/restful/tiposdescontos',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert len(res) > 0
    assert res[0] == {
        'ativo': True,
        'id': client_category.id,
        'codigo': client_category.id,
        'dataCriacao': client_category.te.te_time.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'dataAlteracao': client_category.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'nome': client_category.name,
        'redeId': network['id'],
        'lojaId': None
    }


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_discount_categories_inactive(get_config_mock, get_network_info,
                                          b1food_client, network, client_category):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 0
    }

    response = b1food_client.get('/b1food/terceiros/restful/tiposdescontos',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
def test_get_login_users(get_config_mock, get_network_info, store,
                         b1food_client, network, current_user):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
    }

    response = b1food_client.get('/b1food/terceiros/restful/funcionarios',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert len(res) == store.find(LoginUser).count()
    person_names = _get_person_names(current_user.person)
    current_user_res = {
        'id': current_user.id,
        'codigo': current_user.username,
        'dataCriacao': current_user.te.te_time.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'dataAlteracao': current_user.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'primeiroNome': person_names['primeiroNome'],
        'segundoNome': person_names['segundoNome'],
        'sobrenome': person_names['sobrenome'],
        'apelido': person_names['apelido'],
        'idCargo': current_user.profile.id,
        'codCargo': current_user.profile.id,
        'nomeCargo': current_user.profile.name,
        'redeId': network['id'],
        'lojaId': None,
        'ativo': current_user.is_active
    }
    assert current_user_res in res


@pytest.mark.usefixtures('mock_new_store')
@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
def test_get_login_users_active(get_config_mock, get_network_info, store,
                                b1food_client, current_user, network):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network
    current_user.is_active = False

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 1
    }

    response = b1food_client.get('/b1food/terceiros/restful/funcionarios',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert len(res) == store.find(LoginUser, is_active=True).count()
    assert not any(res_item['id'] == current_user.id for res_item in res)


@pytest.mark.usefixtures('mock_new_store')
@mock.patch('stoqserver.api.resources.b1food._get_network_info')
@mock.patch('stoqserver.api.decorators.get_config')
def test_get_login_users_inactive(get_config_mock, get_network_info,
                                  b1food_client, current_user, network):
    get_config_mock.return_value.get.return_value = 'B1FoodClientId'
    get_network_info.return_value = network

    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'ativo': 0
    }

    response = b1food_client.get('/b1food/terceiros/restful/funcionarios',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []
