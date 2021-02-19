# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2021 Stoq Tecnologia <http://www.stoq.com.br>
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

from datetime import datetime

from freezegun import freeze_time
import pytest

from stoqlib.domain.person import UserBranchAccess
from stoqlib.domain.nfe import NFePurchase
from stoqnfe.domain.distribution import ImportedNfe
from stoqserver.api.resources.imported_nfe import MAX_PAGE_SIZE


@pytest.fixture
@freeze_time('2021-02-10 12:00:00', ignore=['gi'])
def imported_nfe(store):
    key = '351997900074569005160550140014218121505174511'
    xml = '<infNFe Id="NFe{}"></infNFe>'.format(key)
    return ImportedNfe(store=store, key=key, xml=xml, cnpj='99.399.705/0001-90',
                       process_date=datetime.now())


@pytest.fixture
def branch_with_access(store, client, example_creator):
    branch = example_creator.create_branch(cnpj='99.399.705/0001-90')
    UserBranchAccess(store=store, user=client.user, branch=branch)
    return branch


@pytest.mark.parametrize('query_string', ({}, {'limit': 10}, {'offset': 30},
                                          {'limit': 10, 'offset': 30}))
def test_get_imported_nfe_without_cnpj(client, query_string):
    response = client.get('/api/v1/imported_nfe', query_string=query_string)

    assert response.status_code == 400
    assert response.json == {'message': "'cnpj' not provided"}


@pytest.mark.parametrize('cnpj', ('123', '11111111111' '780.442.670-42',
                                  '11111111111111', '00.000.000/0000-01'))
def test_get_imported_nfe_invalid_cnpj(client, cnpj):
    query_string = {
        'cnpj': cnpj
    }
    response = client.get('/api/v1/imported_nfe', query_string=query_string)

    assert response.status_code == 400
    assert response.json == {'message': "Invalid 'cnpj' provided"}


@pytest.mark.parametrize('limit', ('', {}, True))
def test_get_imported_nfe_not_number_limit(client, limit):
    query_string = {
        'cnpj': '99.399.705/0001-90',
        'limit': limit
    }
    response = client.get('/api/v1/imported_nfe', query_string=query_string)

    assert response.status_code == 400
    assert response.json == {'message': "'limit' must be a number"}


def test_get_imported_limit_greater_than_max(client):
    query_string = {
        'cnpj': '99.399.705/0001-90',
        'limit': MAX_PAGE_SIZE + 1,
    }
    response = client.get('/api/v1/imported_nfe', query_string=query_string)

    assert response.status_code == 400
    assert response.json == {'message': "'limit' must be lower than 100"}


@pytest.mark.parametrize('offset', ('', {}, True))
def test_get_imported_nfe_not_number_offset(client, offset):
    query_string = {
        'cnpj': '99.399.705/0001-90',
        'offset': offset
    }
    response = client.get('/api/v1/imported_nfe', query_string=query_string)

    assert response.status_code == 400
    assert response.json == {'message': "'offset' must be a number"}


def test_get_imported_nfe_no_branch(client, imported_nfe):
    query_string = {
        'cnpj': imported_nfe.cnpj
    }
    response = client.get('/api/v1/imported_nfe', query_string=query_string)

    assert response.status_code == 500
    assert response.json['exception'] == 'AssertionError\n'


@pytest.mark.usefixtures('mock_new_store')
def test_get_imported_nfe_user_without_access_to_branch(client, imported_nfe,
                                                        example_creator):
    branch = example_creator.create_branch(cnpj=imported_nfe.cnpj)
    query_string = {
        'cnpj': imported_nfe.cnpj
    }
    response = client.get('/api/v1/imported_nfe', query_string=query_string)

    assert response.status_code == 403
    assert response.json == {'message': 'login_user {} does not have access to branch {}'.format(
        client.user.id, branch.id)}


@pytest.mark.usefixtures('mock_new_store')
def test_get_imported_nfe_no_imported_nfe(client, example_creator, branch_with_access):
    query_string = {
        'cnpj': branch_with_access.person.get_cnpj_or_cpf()
    }
    response = client.get('/api/v1/imported_nfe', query_string=query_string)

    assert response.status_code == 200
    assert response.json == {
        'previous': None,
        'next': None,
        'count': 0,
        'total_records': 0,
        'records': []
    }


@pytest.mark.usefixtures('mock_new_store', 'branch_with_access')
def test_get_imported_nfe_without_nfe_purchase(client, branch_with_access, imported_nfe):
    query_string = {
        'cnpj': imported_nfe.cnpj
    }
    response = client.get('/api/v1/imported_nfe', query_string=query_string)

    assert response.status_code == 200
    assert response.json == {
        'previous': None,
        'next': None,
        'count': 1,
        'total_records': 1,
        'records': [{
            'id': imported_nfe.id,
            'key': imported_nfe.key,
            'process_date': imported_nfe.process_date.isoformat(),
            'purchase_invoice_id': None
        }]
    }


@pytest.mark.usefixtures('mock_new_store')
def test_get_imported_nfe_with_nfe_purchase(store, client, branch_with_access,
                                            example_creator, imported_nfe):
    nfe_purchase = NFePurchase(store=store, branch=branch_with_access,
                               cnpj=imported_nfe.cnpj, xml=imported_nfe.xml)
    query_string = {
        'cnpj': imported_nfe.cnpj
    }
    response = client.get('/api/v1/imported_nfe', query_string=query_string)

    assert response.status_code == 200
    assert response.json == {
        'previous': None,
        'next': None,
        'count': 1,
        'total_records': 1,
        'records': [{
            'id': imported_nfe.id,
            'key': imported_nfe.key,
            'process_date': imported_nfe.process_date.isoformat(),
            'purchase_invoice_id': nfe_purchase.id
        }]
    }


@freeze_time('2021-02-10 12:00:00', ignore=['gi'])
@pytest.mark.usefixtures('mock_new_store', 'branch_with_access')
def test_get_imported_nfe_with_next(store, client, imported_nfe):
    other_imported_nfe = ImportedNfe(store=store, key='123', xml='<infNFe Id="NFe123"></infNFe>',
                                     cnpj=imported_nfe.cnpj, process_date=datetime.now())
    query_string = {
        'cnpj': imported_nfe.cnpj,
        'limit': 1
    }
    route = '/api/v1/imported_nfe'
    response = client.get(route, query_string=query_string)

    assert response.status_code == 200
    assert response.json == {
        'previous': None,
        'next': route + '?limit=1&offset=1&cnpj={}'.format(imported_nfe.cnpj),
        'count': 1,
        'total_records': 2,
        'records': [{
            'id': other_imported_nfe.id,
            'key': other_imported_nfe.key,
            'process_date': other_imported_nfe.process_date.isoformat(),
            'purchase_invoice_id': None
        }]
    }


@freeze_time('2021-02-10 12:00:00', ignore=['gi'])
@pytest.mark.usefixtures('mock_new_store', 'branch_with_access')
def test_get_imported_nfe_with_previous(store, client, imported_nfe):
    ImportedNfe(store=store, cnpj=imported_nfe.cnpj, key='123', xml='<infNFe Id="NFe123"></infNFe>',
                process_date=datetime.now())
    query_string = {
        'cnpj': imported_nfe.cnpj,
        'limit': 1,
        'offset': 1
    }
    route = '/api/v1/imported_nfe'
    response = client.get(route, query_string=query_string)

    assert response.status_code == 200
    assert response.json == {
        'previous': route + '?limit=1&offset=0&cnpj={}'.format(imported_nfe.cnpj),
        'next': None,
        'count': 1,
        'total_records': 2,
        'records': [{
            'id': imported_nfe.id,
            'key': imported_nfe.key,
            'process_date': imported_nfe.process_date.isoformat(),
            'purchase_invoice_id': None
        }]
    }


@freeze_time('2021-02-10 12:00:00', ignore=['gi'])
@pytest.mark.usefixtures('mock_new_store', 'branch_with_access')
def test_get_imported_nfe_with_previous_and_next(store, client, imported_nfe):
    other_imported_nfe = ImportedNfe(store=store, key='123', xml='<infNFe Id="NFe123"></infNFe>',
                                     cnpj=imported_nfe.cnpj, process_date=datetime.now())
    ImportedNfe(store=store, cnpj=imported_nfe.cnpj, key='456', xml='<infNFe Id="NFe456"></infNFe>',
                process_date=datetime.now())
    query_string = {
        'cnpj': imported_nfe.cnpj,
        'limit': 1,
        'offset': 1
    }
    route = '/api/v1/imported_nfe'
    response = client.get(route, query_string=query_string)

    assert response.status_code == 200
    assert response.json == {
        'previous': route + '?limit=1&offset=0&cnpj={}'.format(imported_nfe.cnpj),
        'next': route + '?limit=1&offset=2&cnpj={}'.format(imported_nfe.cnpj),
        'count': 1,
        'total_records': 3,
        'records': [{
            'id': other_imported_nfe.id,
            'key': other_imported_nfe.key,
            'process_date': other_imported_nfe.process_date.isoformat(),
            'purchase_invoice_id': None
        }]
    }
