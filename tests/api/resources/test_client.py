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

from stoqlib.domain.person import Client


@pytest.mark.usefixtures('mock_new_store')
def test_client_post_without_name(client):
    payload = {}
    response = client.post('/client', json=payload)
    assert response.status_code == 400
    assert response.json['message'] == 'no client_name provided'


@pytest.mark.usefixtures('mock_new_store')
def test_client_post_without_doc(client):
    payload = {
        'client_name': 'Zeca',
    }
    response = client.post('/client', json=payload)
    assert response.status_code == 400
    assert response.json['message'] == 'no client_document provided'


@pytest.mark.usefixtures('mock_new_store')
def test_client_post_with_invalid_doc(client):
    payload = {
        'client_name': 'Zeca',
        'client_document': '111.111.111-12'
    }
    response = client.post('/client', json=payload)
    assert response.status_code == 400
    assert response.json['message'] == 'invalid client_document provided'


@pytest.mark.usefixtures('mock_new_store')
def test_client_post_without_address(client):
    payload = {
        'client_name': 'Zeca',
        'client_document': '111.111.111-11'
    }
    response = client.post('/client', json=payload)
    assert response.status_code == 400
    assert response.json['message'] == 'no address provided'


@pytest.mark.usefixtures('mock_new_store')
def test_client_post_without_city_location(client):
    payload = {
        'client_name': 'Zeca',
        'client_document': '111.111.111-11',
        'address': {
            'street': 'Rua Aquidaban',
            'streetnumber': 1,
            'district': 'Centro',
            'postal_code': '13560-120',
            'is_main_address': True,
        }
    }
    response = client.post('/client', json=payload)
    assert response.status_code == 400
    assert response.json['message'] == 'Missing city location'


@pytest.mark.usefixtures('mock_new_store')
def test_client_post_with_invalid_city_location(client):
    payload = {
        'client_name': 'Zeca',
        'client_document': '111.111.111-11',
        'address': {
            'street': 'Rua Aquidaban',
            'streetnumber': 1,
            'district': 'Centro',
            'postal_code': '13560-120',
            'is_main_address': True,
        },
        'city_location': {
            'country': 'Brazil',
            'state': 'SP',
            'city': 'Invalid',
        }
    }
    response = client.post('/client', json=payload)
    assert response.status_code == 400
    assert response.json['message'] == 'Invalid city location'


@pytest.mark.usefixtures('mock_new_store')
def test_client_post(client):
    payload = {
        'client_name': 'Zeca',
        'client_document': '111.111.111-11',
        'address': {
            'street': 'Rua Aquidaban',
            'streetnumber': 1,
            'district': 'Centro',
            'postal_code': '13560-120',
            'is_main_address': True,
        },
        'city_location': {
            'country': 'Brazil',
            'state': 'SP',
            'city': 'São Carlos',
        }
    }
    response = client.post('/client', json=payload)
    assert response.status_code == 201

    # The request also accests the city_location inside the address
    payload['address']['city_location'] = payload.pop('city_location')
    payload['client_document'] = '222.222.222-22'

    assert 'city_location' not in payload
    assert 'city_location' in payload['address']
    response = client.post('/client', json=payload)
    assert response.status_code == 201

    payload['client_document'] = '222.222.222-22'

    assert 'city_location' not in payload
    assert 'city_location' in payload['address']
    response = client.post('/client', json=payload)
    assert response.status_code == 200


@pytest.mark.usefixtures('mock_new_store')
def test_client_get(client, example_creator, store):
    payload = {
        'name': 'Franciso Elisio de Lima Junior',
    }

    response = client.get("/client", query_string=payload)

    assert response.status_code == 200
    res = json.loads(response.data.decode('utf-8'))
    assert res['name'] == payload['name']
    assert res['doc'] is None


@pytest.mark.usefixtures('mock_new_store')
def test_client_get_by_doc(client, example_creator, store):
    payload = {
        'doc': '160.618.061-40',
        'name': 'Franciso Elisio de Lima Junior'
    }

    response = client.get("/client", query_string=payload)

    assert response.status_code == 200
    res = json.loads(response.data.decode('utf-8'))
    assert res['doc'] == payload['doc']
    assert res['name'] == payload['name']


@pytest.mark.usefixtures('mock_new_store')
def test_client_get_by_category(client, example_creator, store):
    payload = {
        'name': 'Franciso Elisio de Lima Junior',
        'category_name': 'Categoria'
    }

    client_category = example_creator.create_client_category(name='Categoria')
    store_client = store.find(Client)[0]
    store_client.category = client_category
    response = client.get("/client", query_string=payload)

    assert response.status_code == 200
    res = json.loads(response.data.decode('utf-8'))[0]
    assert res['name'] == payload['name']
    assert res['category_name'] == payload['category_name']
