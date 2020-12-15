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

from datetime import datetime
from flask import abort, make_response, jsonify, request
from storm.expr import And, Join, Or

from stoqlib.domain.person import Branch, Company, Individual, Person
from stoqlib.domain.sale import Sale
from stoqlib.domain.station import BranchStation
from stoqlib.lib.configparser import get_config
from stoqlib.lib.formatters import raw_document

from stoqserver.api.decorators import store_provider, b1food_login_required
from stoqserver.lib.baseresource import BaseResource

log = logging.getLogger(__name__)

global b1food_token


# just a random token untill we have a domain to persist this.
def generate_b1food_token(size=128):
    import string
    import random

    chars = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(size))


b1food_token = generate_b1food_token()


def _check_required_params(data, required_params):
    for param in required_params:
        if param not in data:
            message = 'Missing parameter \'%s\'' % param
            log.error(message)
            abort(400, message)


def _get_acronyms(request_branches):
    acronyms = []
    if request_branches:
        request_branches = request_branches.replace('[', '').replace(']', '')
        request_branches = request_branches.split(',')
        for acronym in request_branches:
            acronyms.append('%04d' % int(acronym) + ' -')
    return acronyms


def _get_documents(request_documents):
    documents = []
    if request_documents:
        request_documents = request_documents.replace('[', '').replace(']', '')
        documents = request_documents.split(',')
    return documents


def _get_invoice_ids(request_invoice_ids):
    invoice_ids = []
    if request_invoice_ids:
        request_invoice_ids = request_invoice_ids.replace('[', '').replace(']', '')
        invoice_ids = request_invoice_ids.split(',')
    return invoice_ids


class B1foodLoginResource(BaseResource):
    routes = ['/b1food/oauth/authenticate']

    def get(self):
        data = request.args
        log.debug("/oauth/authenticate query string: %s, header: %s, body: %s",
                  data, request.headers, self.get_json())
        if 'client_id' not in data:
            abort(400, 'Missing client_id')
        client_id = data['client_id']

        config = get_config()
        config_client_id = config.get("B1Food", "client_id") or ""
        access_token = config.get("B1Food", "access_token") or ""
        if client_id != config_client_id and config_client_id != "":
            log.error('Login failed for client_id %s', client_id)
            abort(403, 'Login failed for client_id {}'.format(client_id))

        return make_response(jsonify({
            'token_type': 'Bearer',
            'expires_in': float('inf'),
            'access_token': access_token
        }), 200)


class IncomeCenterResource(BaseResource):
    method_decorators = [b1food_login_required]
    routes = ['/b1food/terceiros/restful/centrosrenda']

    def get(self):
        data = request.args
        log.debug("query string: %s, header: %s, body: %s",
                  data, request.headers, self.get_json())
        return []


class B1FoodSaleItemResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider]
    routes = ['/b1food/terceiros/restful/itemvenda']

    def get(self, store):
        data = request.args
        log.debug("query string: %s, header: %s, body: %s",
                  data, request.headers, self.get_json())

        required_params = ['dtinicio', 'dtfim']
        _check_required_params(data, required_params)

        initial_date = datetime.strptime(data['dtinicio'], '%Y-%m-%d')
        end_date = datetime.strptime(data['dtfim'], '%Y-%m-%d')

        request_branches = data.get('lojas')
        request_documents = data.get('consumidores')
        request_invoice_ids = data.get('operacaocupom')

        acronyms = _get_acronyms(request_branches)
        documents = _get_documents(request_documents)
        invoice_ids = _get_invoice_ids(request_invoice_ids)

        if bool(data.get('usarDtMov')) is True:
            query = And(Sale.open_date >= initial_date, Sale.open_date <= end_date)
        else:
            query = And(Sale.confirm_date >= initial_date, Sale.confirm_date <= end_date)

        tables = [Sale]

        if len(acronyms) > 0 or len(documents) > 0:
            tables.append(Join(Branch, Sale.branch_id == Branch.id))

        if len(acronyms) > 0:
            query = And(query, Branch.acronym.is_in(acronyms))

        if len(documents) > 0:
            tables = tables + [Join(Person, Person.id == Branch.person_id),
                               Join(Individual, Individual.person_id == Person.id),
                               Join(Company, Company.person_id == Person.id)]
            query = And(query, Or(Individual.cpf.is_in(documents), Company.cnpj.is_in(documents)))

        if len(invoice_ids) > 0:
            query = And(query, Sale.invoice_id.is_in(invoice_ids))

        # These args are sent but we do not have them on the domain
        # 'redes', 'cancelados'

        sales = store.using(*tables).find(Sale, query)

        response = []

        for sale in sales:
            for item in sale.get_items():
                discount = item.item_discount
                sellable = item.sellable
                station = sale.station
                salesperson = sale.salesperson
                document = raw_document(sale.get_client_document() or "")

                if len(document) == 11:
                    document_type = 'CPF'
                elif len(document) == 14:
                    document_type = 'CNPJ'
                else:
                    document_type = ''

                res_item = {
                    'idItemVenda': item.id,
                    'valorUnitario': float(item.base_price),
                    'valorBruto': float(item.base_price * item.quantity),
                    'valorUnitarioLiquido': float(item.price - discount),
                    'valorLiquido': float((item.price - discount) * item.quantity),
                    'idOrigem': None,
                    'codOrigem': None,
                    'desconto': float(discount),
                    'acrescimo': 0,
                    'maquinaId': station.id,
                    'nomeMaquina': station.name,
                    'maquinaCod': station.code,
                    'quantidade': float(item.quantity),
                    'redeId': sale.branch.person.company.id,
                    'lojaId': sale.branch.id,
                    'idMaterial': sellable.id,
                    'codMaterial': sellable.code,
                    'descricao': sellable.description,
                    'grupo': {
                        'idGrupo': sellable.category.id,
                        'codigo': sellable.category.id,
                        'descricao': sellable.category.description,
                        'idGrupoPai': sellable.category.category_id or '',
                        'dataAlteracao': '',  # FIXME
                        'ativo': True,
                    },
                    'operacaoId': sale.id,
                    'atendenteId': salesperson.id,
                    'atendenteCod': salesperson.person.login_user.username,
                    'atendenteNome': salesperson.person.name,
                    'isTaxa': False,
                    'isRepique': False,
                    'isGorjeta': False,
                    'isEntrega': False,  # FIXME maybe should be true if external order
                    'consumidores': [{
                        'documento': document,
                        'tipo': document_type
                    }],
                    'cancelado': False,
                    'dtLancamento': sale.confirm_date.strftime('%Y-%m-%d'),
                    'horaLancamento': sale.confirm_date.strftime('%H:%M')
                }

                response.append(res_item)

        return response


class B1FoodPaymentsResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider]
    routes = ['/b1food/terceiros/restful/movimentocaixa']

    def get(self, store):
        data = request.args
        log.debug("query string: %s, header: %s, body: %s",
                  data, request.headers, self.get_json())

        required_params = ['dtinicio', 'dtfim']
        _check_required_params(data, required_params)

        initial_date = datetime.strptime(data['dtinicio'], '%Y-%m-%d')
        end_date = datetime.strptime(data['dtfim'], '%Y-%m-%d')

        request_branches = data.get('lojas')
        request_documents = data.get('consumidores')
        request_invoice_ids = data.get('operacaocupom')

        acronyms = _get_acronyms(request_branches)
        documents = _get_documents(request_documents)
        invoice_ids = _get_invoice_ids(request_invoice_ids)

        query = And(Sale.confirm_date >= initial_date, Sale.confirm_date <= end_date)

        tables = [Sale]

        if len(acronyms) > 0 or len(documents) > 0:
            tables.append(Join(Branch, Sale.branch_id == Branch.id))

        if len(acronyms) > 0:
            query = And(query, Branch.acronym.is_in(acronyms))

        if len(documents) > 0:
            tables = tables + [Join(Person, Person.id == Branch.person_id),
                               Join(Individual, Individual.person_id == Person.id),
                               Join(Company, Company.person_id == Person.id)]
            query = And(query, Or(Individual.cpf.is_in(documents), Company.cnpj.is_in(documents)))

        if len(invoice_ids) > 0:
            query = And(query, Sale.invoice_id.is_in(invoice_ids))

        sales = store.using(*tables).find(Sale, query)

        response = []

        for sale in sales:
            document = raw_document(sale.get_client_document() or "")
            if len(document) == 11:
                document_type = 'CPF'
            elif len(document) == 14:
                document_type = 'CNPJ'
            else:
                document_type = ''

            payments = []
            for payment in sale.group.payments:
                payments.append({
                    'id': payment.method.id,
                    'codigo': payment.method.id,
                    'nome': payment.method.method_name,
                    'valor': float(payment.value),
                    'troco': 0,
                    'valorRecebido': float(payment.paid_value),
                    'idAtendente': sale.salesperson.id,
                    'codAtendente': sale.salesperson.person.login_user.username,
                    'nomeAtendente': sale.salesperson.person.name,
                })
            res_item = {
                'idMovimentoCaixa': sale.id,
                'redeId': sale.branch.person.company.id,
                'rede': sale.branch.person.name,
                'lojaId': sale.branch.id,
                'loja': sale.branch.acronym,
                'hora': sale.confirm_date.strftime('%H'),
                'idAtendente': sale.salesperson.id,
                'codAtendente': sale.salesperson.person.login_user.username,
                'nomeAtendente': sale.salesperson.person.name,
                'vlDesconto': float(sale.discount_value),
                'vlAcrescimo': None,
                'vlTotalReceber': float(sale.group.get_total_value()),
                'vlTotalRecebido': float(sale.group.get_total_paid()),
                'vlTrocoFormasPagto': 0,  # ?????????????
                'vlServicoRecebido': 0,  # ?????????????
                'vlRepique': 0,  # ?????????????
                'vlTaxaEntrega': 0,  # ????????????? FIXME: ExternalOrder
                'numPessoas': 1,
                'operacaoId': sale.id,
                'maquinaId': sale.station.id,
                'nomeMaquina': sale.station.name,
                'maquinaCod': sale.station.code,
                'maquinaPortaFiscal': None,
                'meiospagamento': payments,
                'consumidores': [{
                    'documento': document,
                    'tipo': document_type,
                }],
                'dataContabil': sale.confirm_date.strftime('%Y-%m-%d %H:%M:%S %Z'),
            }

            response.append(res_item)

        return response


class B1FoodStationResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider]
    routes = ['/b1food/terceiros/restful/terminais']

    def get(self, store):
        data = request.args
        log.debug("query string: %s, header: %s, body: %s",
                  data, request.headers, self.get_json())

        request_branches = data.get('lojas')
        active = data.get('ativo')

        acronyms = _get_acronyms(request_branches)
        tables = [BranchStation]
        query = None

        if active is not None:
            is_active = active == '1'
            query = BranchStation.is_active == is_active

        if len(acronyms) > 0:
            tables.append(Join(Branch, BranchStation.branch_id == Branch.id))
            if query is not None:
                query = And(query, Branch.acronym.is_in(acronyms))
            else:
                query = Branch.acronym.is_in(acronyms)

        if query:
            stations = store.using(*tables).find(BranchStation, query)
        else:
            stations = store.using(*tables).find(BranchStation)

        response = []
        for station in stations:
            response.append({
                'ativo': station.is_active,
                'id': station.id,
                'codigo': station.id,
                'nome': station.name,
                'apelido': station.name,
                'portaFiscal': None,
                'redeId': station.branch.person.company.id,
                'lojaId': station.branch.id
            })

        return response
