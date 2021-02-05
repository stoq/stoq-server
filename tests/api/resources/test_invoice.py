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

from unittest import mock

import pytest
from lxml import etree
from stoqnfe.domain.distribution import ImportedNfe

from stoqserver.utils import get_pytests_datadir


@pytest.fixture
def mock_new_store(monkeypatch, store):
    monkeypatch.setattr('stoqserver.lib.restful.api.new_store', mock.Mock(return_value=store))


@pytest.fixture
def imported_nfe(store):
    return ImportedNfe(store=store, cnpj='95.941.054/0001-68')


@pytest.fixture
def imported_nfe_xml():
    xml_path = get_pytests_datadir('nfe.xml')
    parser_etree = etree.XMLParser(remove_blank_text=True)
    return etree.parse(xml_path, parser_etree)


@pytest.fixture
def imported_nfe_payload(imported_nfe, current_branch):
    return {
        'imported_nfe_id': imported_nfe.id,
        'branch_id': current_branch.id,
    }


@pytest.mark.usefixtures('mock_new_store')
def test_nfe_purchase_endpoint(client, imported_nfe, imported_nfe_payload,
                               current_branch, imported_nfe_xml):
    imported_nfe.xml = imported_nfe_xml
    response = client.post('/api/v1/invoice/import', json=imported_nfe_payload)

    assert response.status_code == 201
    assert response.json['invoice_number'] == 476
    assert response.json['invoice_series'] == 1
    assert response.json['process_date']


def test_nfe_purchase_endpoint_without_imported_nfe_id(client, imported_nfe_payload):
    imported_nfe_payload['imported_nfe_id'] = None

    response = client.post('/api/v1/invoice/import', json=imported_nfe_payload)
    assert response.status_code == 400
    assert response.json['message'] == 'No imported_nfe_id provided'


def test_nfe_purchase_endpoint_without_branch_id(client, imported_nfe_payload):
    imported_nfe_payload['branch_id'] = None

    response = client.post('/api/v1/invoice/import', json=imported_nfe_payload)
    assert response.status_code == 400
    assert response.json['message'] == 'No branch_id provided'


@pytest.mark.parametrize('branch_id', ('f5eb332a-6ae2-11eb-8c34-9f57ba2f882b',
                                       'd6fc443b-6ae2-11eb-8c34-9f57ba2f771b'))
def test_nfe_purchase_endpoint_invalid_branch_id(client, imported_nfe_payload, branch_id):
    imported_nfe_payload['branch_id'] = branch_id

    response = client.post('/api/v1/invoice/import', json=imported_nfe_payload)
    assert response.status_code == 400
    assert response.json['message'] == 'Branch not found'


@pytest.mark.parametrize('imported_nfe_id', ('d4da221a-6ae2-11eb-8c34-9f57ba2f882b',
                                             'f5eb332a-6ae2-11eb-8c34-9f57ba2f771b'))
def test_nfe_purchase_endpoint_imported_nfe_not_found(
        client, imported_nfe, imported_nfe_id, imported_nfe_payload):
    imported_nfe_payload['imported_nfe_id'] = imported_nfe_id

    response = client.post('/api/v1/invoice/import', json=imported_nfe_payload)
    assert response.status_code == 400
    assert response.json['message'] == 'ImportedNfe not found'
