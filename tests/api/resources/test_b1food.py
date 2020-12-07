import json
import pytest

from unittest import mock

from stoqserver.api.resources.b1food import generate_b1food_token


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

    response = b1food_client.get('/b1food/oauth/authenticate', query_string=query_string)
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

    response = b1food_client.get('/b1food/oauth/authenticate', query_string=query_string)
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
    response = b1food_client.get('/b1food/oauth/authenticate', query_string=query_string)

    assert response.status_code == 403


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_income_center(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "B1FoodClientId"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
    }
    response = b1food_client.get('b1food/centrosrenda', query_string=query_string)
    res = json.loads(response.data.decode('utf-8'))

    assert res == []


@mock.patch('stoqserver.api.decorators.get_config')
def test_get_income_center_with_wrong_authorization(get_config_mock, b1food_client):
    get_config_mock.return_value.get.return_value = "dasdadasded"
    query_string = {
        'Authorization': 'Bearer B1FoodClientId',
    }
    response = b1food_client.get('b1food/centrosrenda', query_string=query_string)

    assert response.status_code == 401
