import json
import pytest

from unittest import mock
from datetime import datetime

from stoqlib.domain.station import BranchStation
from stoqlib.lib.formatters import raw_document

from stoqserver.api.resources.b1food import generate_b1food_token


@pytest.fixture
def sale(example_creator, current_user):
    test_sale = example_creator.create_sale()
    test_sale.open_date = datetime.strptime('2020-01-02', '%Y-%m-%d')
    test_sale.confirm_date = datetime.strptime('2020-01-02', '%Y-%m-%d')
    sale_item = example_creator.create_sale_item(test_sale)
    sellable_category = example_creator.create_sellable_category(description='Category 1')
    sale_item.sellable.category = sellable_category
    client = example_creator.create_client()
    client.person.individual.cpf = '737.948.760-40'
    test_sale.client = client
    person = example_creator.create_person()
    person.login_user = current_user
    test_sale.salesperson.person = person
    payment = example_creator.create_payment(group=test_sale.group)
    payment.paid_value = 10

    return test_sale


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
    assert res['expires_in'] == float('inf')


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
def test_get_sale_item_with_usarDtMov_arg(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'usarDtMov': 1
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_sale_item_with_lojas_arg(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'lojas': 1
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_sale_item_with_lojas_as_list_arg(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'lojas': [1, 2, 4]
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_sale_item_with_consumidores_as_list_arg(get_config_mock, b1food_client):
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
def test_get_sale_item_with_consumidores_and_lojas_args(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'consumidores': [97050782033, 70639759000102],
        'lojas': [1, 2, 4]
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_sale_item_with_operacaocupom_as_list_arg(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'operacaocupom': [
            'a25dd1ad-7dae-11ea-b5ac-b285fb9a2a4e',
            '21b5a545-7aa1-11ea-b5ac-b285fb9a2a4e'
        ]
    }
    response = b1food_client.get('b1food/terceiros/restful/itemvenda',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sale_item_successfully(get_config_mock, b1food_client, store, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
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
        'atendenteId': salesperson.id,
        'atendenteNome': salesperson.person.name,
        'cancelado': False,
        'codMaterial': '',
        'codOrigem': None,
        'consumidores': [{'documento': document, 'tipo': 'CPF'}],
        'desconto': -90.0,
        'descricao': 'Description',
        'dtLancamento': '2020-01-02',
        'grupo': {
            'ativo': True,
            'codigo': sellable.category.id,
            'dataAlteracao': '',
            'descricao': sellable.category.description,
            'idGrupo': sellable.category.id,
            'idGrupoPai': sellable.category.category_id or ''
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
        'maquinaCod': station.code,
        'maquinaId': station.id,
        'nomeMaquina': station.name,
        'operacaoId': sale.id,
        'quantidade': 1.0,
        'redeId': sale.branch.person.company.id,
        'valorBruto': 10.0,
        'valorLiquido': 190.0,
        'valorUnitario': 10.0,
        'valorUnitarioLiquido': 190.0
    }]


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_sale_item_with_cnpj_client_successfully(get_config_mock, b1food_client,
                                                     store, example_creator, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    sale.client.person.individual = None
    company = example_creator.create_company()
    company.cnpj = '35.600.423/0001-27'
    sale.client.person.company = company
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
def test_get_payment_with_lojas_arg(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'lojas': 1
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_payment_with_lojas_as_list_arg(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'lojas': [1, 2, 4]
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_payment_with_consumidores_as_list_arg(get_config_mock, b1food_client):
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
def test_get_payment_with_consumidores_and_lojas_args(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'consumidores': [97050782033, 70639759000102],
        'lojas': [1, 2, 4]
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_payment_with_operacaocupom_as_list_arg(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-01',
        'operacaocupom': [
            'a25dd1ad-7dae-11ea-b5ac-b285fb9a2a4e',
            '21b5a545-7aa1-11ea-b5ac-b285fb9a2a4e'
        ]
    }
    response = b1food_client.get('b1food/terceiros/restful/movimentocaixa',
                                 query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payment_with_cnpj_client_successfully(get_config_mock, b1food_client,
                                                   store, example_creator, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    sale.client.person.individual = None
    company = example_creator.create_company()
    company.cnpj = '35.600.423/0001-27'
    sale.client.person.company = company
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
        'dtinicio': '2020-01-01',
        'dtfim': '2020-01-03'
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


@mock.patch('stoqserver.api.decorators.get_config')
@pytest.mark.usefixtures('mock_new_store')
def test_get_payments_successfully(get_config_mock, b1food_client, store, sale):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
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
    document = raw_document(sale.get_client_document())
    assert response.status_code == 200
    assert res == [
        {
            'codAtendente': 'admin',
            'consumidores': [
                {
                    'documento': document,
                    'tipo': 'CPF'
                }
            ],
            'dataContabil': '2020-01-02 00:00:00 ',
            'hora': '00',
            'idAtendente': salesperson.id,
            'idMovimentoCaixa': sale.id,
            'loja': None,
            'lojaId': sale.branch.id,
            'maquinaCod': '',
            'maquinaId': sale.station.id,
            'maquinaPortaFiscal': None,
            'meiospagamento': [
                {
                    'id': payment.method.id,
                    'codigo': payment.method.id,
                    'nome': payment.method.method_name,
                    'valor': payment.value,
                    'troco': 0,
                    'valorRecebido': payment.paid_value,
                    'idAtendente': sale.salesperson.id,
                    'codAtendente': sale.salesperson.person.login_user.username,
                    'nomeAtendente': sale.salesperson.person.name,
                }
            ],
            'nomeAtendente': 'John',
            'nomeMaquina': sale.station.name,
            'numPessoas': 1,
            'operacaoId': sale.id,
            'rede': 'Stoq Roupas e Acessórios Ltda',
            'redeId': sale.branch.person.company.id,
            'vlAcrescimo': None,
            'vlTotalReceber': sale.group.get_total_value(),
            'vlTotalRecebido': sale.group.get_total_paid(),
            'vlDesconto': 0.0,
            'vlRepique': 0,
            'vlServicoRecebido': 0,
            'vlTaxaEntrega': 0,
            'vlTrocoFormasPagto': 0
        },
    ]
