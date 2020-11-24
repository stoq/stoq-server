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

import logging

from blinker import signal
from flask import abort, request
from storm.expr import Join, LeftJoin

from stoqlib.domain.address import Address, CityLocation
from stoqlib.domain.person import Person, Client, ClientCategory, Individual, Company
from stoqlib.lib.formatters import raw_document, format_cpf
from stoqlib.lib.validators import validate_cpf

from stoqserver.lib.baseresource import BaseResource
from stoqserver.api.decorators import login_required, store_provider

log = logging.getLogger(__name__)


class ClientResource(BaseResource):
    """Client RESTful resource."""
    method_decorators = [login_required, store_provider]
    routes = ['/client']

    @classmethod
    def create_address(cls, person, address):
        if not address.get('city_location'):
            log.error('Missing city location')
            abort(400, "Missing city location")

        city_location = CityLocation.get(
            person.store,
            country=address['city_location']['country'],
            city=address['city_location']['city'],
            state=address['city_location']['state'],
        )
        if not city_location:
            log.error('Invalid city location: %s', address['city_location'])
            abort(400, "Invalid city location")

        Address(street=address['street'],
                streetnumber=address['streetnumber'],
                district=address['district'],
                postal_code=address['postal_code'],
                complement=address.get('complement'),
                is_main_address=address['is_main_address'],
                person=person,
                city_location=city_location,
                store=person.store)

    @classmethod
    def get_client(cls, store, cpf):
        tables = [Client,
                  Join(Person, Client.person_id == Person.id),
                  Join(Individual, Individual.person_id == Person.id)]
        return store.using(*tables).find(Client, Individual.cpf == cpf).one()

    @classmethod
    def create_client(cls, store, name, cpf, address=None):
        # TODO: Add phone number
        person = Person(name=name, store=store)
        Individual(cpf=cpf, person=person, store=store)
        if address:
            cls.create_address(person, address)

        client = Client(person=person, store=store)
        return client

    def _dump_client(self, client):
        person = client.person
        birthdate = person.individual.birth_date if person.individual else None

        last_items = {}
        # Disable this for now, since this query is taking way to long to process and no one really
        # uses this.
        # saleviews = person.client.get_client_sales().order_by(Desc('confirm_date'))
        # for saleview in saleviews:
        #     for item in saleview.sale.get_items():
        #         last_items[item.sellable_id] = item.sellable.description
        #         # Just the last 3 products the client bought
        #         if len(last_items) == 3:
        #             break

        if person.company:
            doc = person.company.cnpj
        else:
            doc = person.individual.cpf

        category_name = client.category.name if client.category else ""

        data = dict(
            id=client.id,
            category=client.category_id,
            doc=doc,
            last_items=last_items,
            name=person.name,
            birthdate=birthdate,
            category_name=category_name,
        )

        return data

    def _get_by_doc(self, store, data, doc):
        # Extra precaution in case we ever send the cpf already formatted
        document = format_cpf(raw_document(doc))

        person = Person.get_by_document(store, document)
        if person and person.client:
            data = self._dump_client(person.client)

        # Plugins that listen to this signal will return extra fields
        # to be added to the response
        responses = signal('CheckRewardsPermissionsEvent').send(doc)
        for response in responses:
            data.update(response[1])

        return data

    def _get_by_category(self, store, category_name):
        # Pre-fetch person and Individual as they will be used down the line by _dump_client
        tables = [Client,
                  Join(Person, Person.id == Client.person_id),
                  LeftJoin(Individual, Person.id == Individual.person_id),
                  LeftJoin(Company, Person.id == Company.person_id),
                  Join(ClientCategory, Client.category_id == ClientCategory.id)]
        clients = store.using(*tables).find((Client, Person, Individual, ClientCategory),
                                            ClientCategory.name == category_name)
        retval = []
        for data in clients:
            retval.append(self._dump_client(data[0]))
        return retval

    def get(self, store):
        doc = request.args.get('doc')
        name = request.args.get('name')
        category_name = request.args.get('category_name')

        if doc:
            return self._get_by_doc(store, {'doc': doc, 'name': name}, doc)
        if category_name:
            return self._get_by_category(store, category_name)

        return {'doc': doc, 'name': name}

    def post(self, store):
        data = self.get_json()

        client_name = data.get('client_name')
        client_document = data.get('client_document')
        address_info = data.get('address')

        log.debug("POST /client station: %s payload: %s",
                  self.get_current_station(store), data)

        # We should change the api callsite so that city_location is inside the address
        if address_info:
            address_info.setdefault('city_location', data.get('city_location'))

        if not client_name:
            log.error('no client_name provided: %s', data)
            return {'message': 'no client_name provided'}, 400

        if not client_document:
            log.error('no client_document provided: %s', data)
            return {'message': 'no client_document provided'}, 400
        if not validate_cpf(client_document):
            log.error('invalid client_document provided: %s', data)
            return {'message': 'invalid client_document provided'}, 400

        if not address_info:
            # Note that city location is validated when creating the address
            log.error('no address provided: %s', data)
            return {'message': 'no address provided'}, 400

        client = self.get_client(store, client_document)
        if client:
            log.error('client with cpf %s already exists', client_document)
            return {
                'message': 'A client with this CPF already exists',
                'data': {
                    'id': client.id,
                }
            }, 200

        client = self.create_client(store, client_name, client_document, address_info)
        return {
            'message': 'Client created',
            'data': {
                'id': client.id,
            }
        }, 201
