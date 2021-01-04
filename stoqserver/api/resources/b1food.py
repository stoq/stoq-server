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
from storm.expr import And, Join, LeftJoin, Ne, Or
from storm.info import ClassAlias

from stoqlib.domain.fiscal import Invoice, CfopData
from stoqlib.domain.overrides import ProductBranchOverride
from stoqlib.domain.payment.method import PaymentMethod
from stoqlib.domain.payment.payment import Payment
from stoqlib.domain.payment.group import PaymentGroup
from stoqlib.domain.person import (Branch, Company, Individual, LoginUser, SalesPerson,
                                   Person, EmployeeRole, ClientCategory, Client)
from stoqlib.domain.product import Product
from stoqlib.domain.system import TransactionEntry
from stoqlib.domain.sale import Sale, SaleItem
from stoqlib.domain.sellable import Sellable, SellableCategory
from stoqlib.domain.station import BranchStation
from stoqlib.domain.taxes import InvoiceItemIcms
from stoqlib.lib.configparser import get_config
from stoqlib.lib.formatters import raw_document
from stoqlib.lib.parameters import sysparam

from stoqserver.api.decorators import store_provider, b1food_login_required, info_logger
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


def _parse_request_list(request_list):
    return_list = []
    if request_list:
        request_list = request_list.replace('[', '').replace(']', '')
        return_list = request_list.split(',')
    return return_list


def _get_category_info(sellable):
    return {
        'idGrupo': sellable.category and sellable.category.id,
        'codigo': '',
        'descricao': sellable.category and sellable.category.description,
        'idGrupoPai': sellable.category and sellable.category.category_id,
        'dataAlteracao': sellable.category and
        sellable.category.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
        'ativo': True,
    }


def _get_network_info():
    # We do not have this infos on database, so until we have them we get from config
    config = get_config()
    return {
        'id': config.get('B1Food', 'network_id') or '',
        'name': config.get('B1Food', 'network_name') or '',
    }


def _get_payments_info(payments_list, login_user, sale):
    payments = []
    for payment in payments_list:
        payments.append({
            'id': payment.method.id,
            'codigo': None,
            'nome': payment.method.method_name,
            'descricao': payment.method.method_name,
            'valor': float(payment.base_value or 0),
            'troco': float(payment.base_value - payment.value),
            'valorRecebido': float(payment.value or 0),
            'idAtendente': login_user.id,
            'codAtendente': login_user.username,
            'nomeAtendente': sale.salesperson.person.name,
        })
    return payments


class B1foodLoginResource(BaseResource):
    method_decorators = [info_logger]
    routes = ['/b1food/oauth/authenticate']

    def get(self):
        data = request.args
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
    method_decorators = [b1food_login_required, info_logger]
    routes = ['/b1food/terceiros/restful/centrosrenda']

    def get(self):
        return []


class B1FoodSaleItemResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider, info_logger]
    routes = ['/b1food/terceiros/restful/itemvenda']

    def get(self, store):
        data = request.args

        required_params = ['dtinicio', 'dtfim']
        _check_required_params(data, required_params)

        initial_date = datetime.strptime(data['dtinicio'], '%Y-%m-%d')
        end_date = datetime.strptime(data['dtfim'], '%Y-%m-%d')

        request_branches = data.get('lojas')
        request_documents = data.get('consumidores')
        request_invoice_keys = data.get('operacaocupom')

        branch_ids = _parse_request_list(request_branches)
        documents = _parse_request_list(request_documents)
        invoice_keys = _parse_request_list(request_invoice_keys)

        if data.get('usarDtMov') and data.get('usarDtMov') == '1':
            clauses = [Sale.confirm_date >= initial_date, Sale.confirm_date <= end_date]
        else:
            clauses = [Sale.open_date >= initial_date, Sale.open_date <= end_date]

        ClientPerson = ClassAlias(Person, 'person_client')
        ClientIndividual = ClassAlias(Individual, 'individual_client')
        ClientCompany = ClassAlias(Company, 'company_client')

        SalesPersonPerson = ClassAlias(Person, 'person_sales_person')
        SalesPersonIndividual = ClassAlias(Individual, 'individual_sales_person')

        tables = [
            Sale,
            Join(Branch, Sale.branch_id == Branch.id),
            LeftJoin(Client, Client.id == Sale.client_id),
            Join(Person, Person.id == Client.person_id),
            Join(BranchStation, Sale.station_id == BranchStation.id),
            LeftJoin(ClientPerson, Client.person_id == ClientPerson.id),
            LeftJoin(ClientIndividual, Client.person_id == ClientIndividual.person_id),
            LeftJoin(Individual, Client.person_id == Individual.person_id),
            LeftJoin(ClientCompany, Client.person_id == ClientCompany.person_id),
            LeftJoin(Company, Client.person_id == Company.person_id),
            LeftJoin(SalesPerson, SalesPerson.id == Sale.salesperson_id),
            LeftJoin(SalesPersonPerson, SalesPerson.person_id == SalesPersonPerson.id),
            LeftJoin(SalesPersonIndividual,
                     SalesPerson.person_id == SalesPersonIndividual.person_id),
            Join(LoginUser, LoginUser.person_id == SalesPerson.person_id),
            Join(Invoice, Sale.invoice_id == Invoice.id),
        ]

        sale_item_tables = [
            SaleItem,
            Join(Sellable, SaleItem.sellable_id == Sellable.id),
            Join(Product, SaleItem.sellable_id == Product.id),
            LeftJoin(SellableCategory, Sellable.category_id == SellableCategory.id),
            LeftJoin(TransactionEntry, SellableCategory.te_id == TransactionEntry.id)
        ]

        sale_objs = (Sale, ClientCompany, ClientIndividual, LoginUser, Branch, BranchStation,
                     Client, ClientPerson, SalesPerson, SalesPersonPerson)

        sale_items_objs = (SaleItem, Sellable, SellableCategory, Product, TransactionEntry)

        if len(branch_ids) > 0:
            clauses.append(Branch.id.is_in(branch_ids))

        if len(documents) > 0:
            clauses.append(Or(Individual.cpf.is_in(documents), Company.cnpj.is_in(documents)))

        if len(invoice_keys) > 0:
            clauses.append(Invoice.key.is_in(invoice_keys))

        if data.get('cancelados') and data.get('cancelados') == '0':
            clauses.append(Sale.status != Sale.STATUS_CANCELLED)

        data = list(store.using(*tables).find(sale_objs, And(*clauses)))

        sale_ids = [i[0].id for i in data]
        sale_items = list(store.using(*sale_item_tables).find(sale_items_objs,
                                                              SaleItem.sale_id.is_in(sale_ids)))

        sales = {}
        for item in sale_items:
            sales.setdefault(item[0].sale_id, [])
            sales[item[0].sale_id].append(item[0])

        response = []

        for row in data:
            sale, company, individual, login_user = row[:4]
            for item in sales[sale.id]:
                discount = item.item_discount
                sellable = item.sellable
                station = sale.station
                salesperson = sale.salesperson

                cpf = individual and individual.cpf
                cnpj = company and company.cnpj

                document = cpf or cnpj or ''

                if cpf:
                    document_type = 'CPF'
                elif cnpj:
                    document_type = 'CNPJ'
                else:
                    document_type = ''

                network = _get_network_info()

                res_item = {
                    'idItemVenda': item.id,
                    'valorUnitario': float(item.base_price),
                    'valorBruto': float(item.base_price * item.quantity),
                    'valorUnitarioLiquido': float(item.price),
                    'valorLiquido': float(item.price * item.quantity),
                    'idOrigem': None,
                    'codOrigem': None,
                    'desconto': float(discount),
                    'acrescimo': 0,
                    'maquinaId': station.id,
                    'nomeMaquina': station.name,
                    'maquinaCod': station.code,
                    'quantidade': float(item.quantity),
                    'redeId': network['id'],
                    'lojaId': sale.branch.id,
                    'idMaterial': sellable.id,
                    'codMaterial': sellable.code,
                    'descricao': sellable.description,
                    'grupo': _get_category_info(sellable),
                    'operacaoId': sale.id,
                    'atendenteId': login_user.id,
                    'atendenteCod': login_user.username,
                    'atendenteNome': salesperson.person.name,
                    'isTaxa': False,
                    'isRepique': False,
                    'isGorjeta': False,
                    'isEntrega': False,  # FIXME maybe should be true if external order
                    'consumidores': [{
                        'documento': raw_document(document),
                        'tipo': document_type
                    }],
                    'cancelado': sale.status == Sale.STATUS_CANCELLED,
                    'dtLancamento': sale.confirm_date.strftime('%Y-%m-%d'),
                    'horaLancamento': sale.confirm_date.strftime('%H:%M')
                }

                response.append(res_item)

        return response


class B1FoodSellableResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider, info_logger]
    routes = ['/b1food/terceiros/restful/material']

    def get(self, store):
        data = request.args

        request_available = data.get('ativo')
        request_branches = data.get('lojas')
        branch_ids = _parse_request_list(request_branches)
        branches = store.find(Branch, Branch.id.is_in(branch_ids))

        delivery = sysparam.get_object(store, 'DELIVERY_SERVICE')
        if request_available:
            sellables = Sellable.get_available_sellables(store)
        else:
            sellables = store.find(Sellable, Ne(Sellable.id, delivery.sellable.id))

        network = _get_network_info()
        response = []

        for sellable in sellables:
            if not request_branches:
                res_item = {
                    'idMaterial': sellable.id,
                    'codigo': sellable.code,
                    'descricao': sellable.description,
                    'unidade': sellable.unit and sellable.unit.description,
                    'dataAlteracao': sellable.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
                    'ativo': sellable.status == Sellable.STATUS_AVAILABLE,
                    'redeId': network['id'],
                    'lojaId': None,
                    'isTaxa': False,
                    'isRepique': False,
                    'isGorjeta': False,
                    'isEntrega': False,
                    'grupo': _get_category_info(sellable)
                }
                response.append(res_item)
            else:
                for branch in branches:
                    query = And(ProductBranchOverride.product_id == sellable.id,
                                ProductBranchOverride.branch_id == branch.id)
                    if store.find(ProductBranchOverride, query):
                        res_item = {
                            'idMaterial': sellable.id,
                            'codigo': sellable.code,
                            'descricao': sellable.description,
                            'unidade': sellable.unit and sellable.unit.description,
                            'dataAlteracao': sellable.te.te_server.strftime(
                                '%Y-%m-%d %H:%M:%S -0300'),
                            'ativo': sellable.status == Sellable.STATUS_AVAILABLE,
                            'redeId': network['id'],
                            'lojaId': branch.id,
                            'isTaxa': False,
                            'isRepique': False,
                            'isGorjeta': False,
                            'isEntrega': False,
                            'grupo': _get_category_info(sellable)
                        }
                        response.append(res_item)

        return response


class B1FoodPaymentsResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider, info_logger]
    routes = ['/b1food/terceiros/restful/movimentocaixa']

    def _get_payments_sum(self, payments):
        # FIXME We opted to not use sale.get_total_paid() to prevent extra queries
        # We reimplemented this private method without out payments, purchase and
        # renegotiation. For now we raises exceptions hopping that our client do
        # not use those features
        out_payments = [p for p in payments if p.payment_type == Payment.TYPE_OUT]
        if len(out_payments) > 0:
            raise Exception("Inconsistent database, please contact support.")

        in_payments = [p for p in payments if p.payment_type == Payment.TYPE_IN]
        return sum([payment.value for payment in in_payments])

    def get(self, store):
        data = request.args

        required_params = ['dtinicio', 'dtfim']
        _check_required_params(data, required_params)

        initial_date = datetime.strptime(data['dtinicio'], '%Y-%m-%d')
        end_date = datetime.strptime(data['dtfim'], '%Y-%m-%d')

        request_branches = data.get('lojas')
        request_documents = data.get('consumidores')
        request_invoice_keys = data.get('operacaocupom')

        branch_ids = _parse_request_list(request_branches)
        documents = _parse_request_list(request_documents)
        invoice_keys = _parse_request_list(request_invoice_keys)

        clauses = [Sale.confirm_date >= initial_date, Sale.confirm_date <= end_date]

        ClientPerson = ClassAlias(Person, 'person_client')
        ClientIndividual = ClassAlias(Individual, 'individual_client')
        ClientCompany = ClassAlias(Company, 'company_client')

        SalesPersonPerson = ClassAlias(Person, 'person_sales_person')
        SalesPersonIndividual = ClassAlias(Individual, 'individual_sales_person')

        tables = [
            Sale,
            Join(Branch, Sale.branch_id == Branch.id),
            LeftJoin(Client, Client.id == Sale.client_id),
            Join(Person, Person.id == Client.person_id),
            Join(BranchStation, Sale.station_id == BranchStation.id),
            LeftJoin(ClientPerson, Client.person_id == ClientPerson.id),
            LeftJoin(ClientIndividual, Client.person_id == ClientIndividual.person_id),
            LeftJoin(Individual, Client.person_id == Individual.person_id),
            LeftJoin(ClientCompany, Client.person_id == ClientCompany.person_id),
            LeftJoin(Company, Client.person_id == Company.person_id),
            LeftJoin(SalesPerson, SalesPerson.id == Sale.salesperson_id),
            LeftJoin(SalesPersonPerson, SalesPerson.person_id == SalesPersonPerson.id),
            LeftJoin(SalesPersonIndividual,
                     SalesPerson.person_id == SalesPersonIndividual.person_id),
            Join(LoginUser, LoginUser.person_id == SalesPerson.person_id),
            Join(PaymentGroup, PaymentGroup.id == Sale.group_id),
            Join(Invoice, Sale.invoice_id == Invoice.id),
        ]

        payment_tables = [
            Payment,
            Join(PaymentMethod, Payment.method_id == PaymentMethod.id),
            Join(PaymentGroup, Payment.group_id == PaymentGroup.id),
        ]

        sale_objs = (Sale, ClientCompany, ClientIndividual, LoginUser, Branch, PaymentGroup,
                     BranchStation, Client, ClientPerson, SalesPerson, SalesPersonPerson)

        payment_objs = (Payment, PaymentMethod, PaymentGroup)

        if len(branch_ids) > 0:
            clauses.append(Branch.id.is_in(branch_ids))

        if len(documents) > 0:
            clauses.append(Or(Individual.cpf.is_in(documents), Company.cnpj.is_in(documents)))

        if len(invoice_keys) > 0:
            clauses.append(Invoice.key.is_in(invoice_keys))

        data = list(store.using(*tables).find(sale_objs, And(*clauses)))

        group_ids = [i[0].group_id for i in data]

        payments_list = list(store.using(*payment_tables).find(payment_objs,
                                                               Payment.group_id.is_in(group_ids)))

        sale_payments = {}
        for payment in payments_list:
            sale_payments.setdefault(payment[0].group_id, [])
            sale_payments[payment[0].group_id].append(payment[0])

        response = []

        for row in data:
            sale, company, individual, login_user, branch, group = row[:6]
            cpf = individual and individual.cpf
            cnpj = company and company.cnpj

            document = cpf or cnpj or ''

            if cpf:
                document_type = 'CPF'
            elif cnpj:
                document_type = 'CNPJ'
            else:
                document_type = ''

            network = _get_network_info()

            res_item = {
                'idMovimentoCaixa': sale.id,
                'redeId': network['id'],
                'rede': network['name'],
                'lojaId': branch.id,
                'loja': branch.name,
                'hora': sale.confirm_date.strftime('%H'),
                'idAtendente': login_user.id,
                'codAtendente': login_user.username,
                'nomeAtendente': sale.salesperson.person.name,
                'vlDesconto': float(sale.discount_value),
                'vlAcrescimo': float(sale.surcharge_value),
                'vlTotalReceber': float(sale.total_amount),
                'vlTotalRecebido': float(self._get_payments_sum(sale_payments[sale.group_id])),
                'vlTrocoFormasPagto': 0,
                'vlServicoRecebido': 0,
                'vlRepique': 0,
                'vlTaxaEntrega': 0,
                'numPessoas': 1,
                'operacaoId': sale.id,
                'maquinaId': sale.station.id,
                'nomeMaquina': sale.station.name,
                'maquinaCod': sale.station.code,
                'maquinaPortaFiscal': None,
                'meiosPagamento': _get_payments_info(sale_payments[sale.group_id],
                                                     login_user, sale),
                'consumidores': [{
                    'documento': raw_document(document),
                    'tipo': document_type,
                }],
                # FIXME B1Food expect this date to be the same as the emission date
                # we want the emission date of nfe_data for this field
                # https://gitlab.com/stoqtech/private/stoq-plugin-nfe/-/issues/111
                'dataContabil': sale.confirm_date.strftime('%Y-%m-%d %H:%M:%S -0300'),
            }

            response.append(res_item)

        return response


class B1FoodPaymentMethodResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider, info_logger]
    routes = ['/b1food/terceiros/restful/meio-pagamento']

    def get(self, store):
        data = request.args

        request_is_active = data.get('ativo')

        payment_methods = store.find(PaymentMethod)
        if request_is_active:
            payment_methods = PaymentMethod.get_active_methods(store)

        network = _get_network_info()

        response = []
        for payment_method in payment_methods:
            res_item = {
                'ativo': payment_method.is_active,
                'id': payment_method.id,
                'codigo': None,
                'nome': payment_method.method_name,
                'redeId': network['id'],
                'lojaId': None
            }
            response.append(res_item)

        return response


class B1FoodStationResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider, info_logger]
    routes = ['/b1food/terceiros/restful/terminais']

    def get(self, store):
        data = request.args

        request_branches = data.get('lojas')
        active = data.get('ativo')

        branch_ids = _parse_request_list(request_branches)
        tables = [BranchStation]
        clauses = []

        if active is not None:
            is_active = active == '1'
            clauses.append(BranchStation.is_active == is_active)

        if len(branch_ids) > 0:
            tables.append(Join(Branch, BranchStation.branch_id == Branch.id))
            clauses.append(Branch.id.is_in(branch_ids))

        if len(clauses) > 0:
            stations = store.using(*tables).find(BranchStation, And(*clauses))
        else:
            stations = store.using(*tables).find(BranchStation)

        network = _get_network_info()

        response = []
        for station in stations:
            response.append({
                'ativo': station.is_active,
                'id': station.id,
                'codigo': station.code,
                'nome': station.name,
                'apelido': None,
                'portaFiscal': None,
                'redeId': network['id'],
                'lojaId': station.branch.id,
                'dataAlteracao': station.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
                'dataCriacao': station.te.te_time.strftime('%Y-%m-%d %H:%M:%S -0300'),
            })

        return response


class B1FoodReceiptsResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider, info_logger]
    routes = ['/b1food/terceiros/restful/comprovante']

    def get(self, store):
        data = request.args

        required_params = ['dtinicio', 'dtfim']
        _check_required_params(data, required_params)

        initial_date = datetime.strptime(data['dtinicio'], '%Y-%m-%d')
        end_date = datetime.strptime(data['dtfim'], '%Y-%m-%d')

        request_branches = data.get('lojas')
        request_documents = data.get('consumidores')
        request_invoice_keys = data.get('operacaocupom')

        branch_ids = _parse_request_list(request_branches)
        documents = _parse_request_list(request_documents)
        invoice_keys = _parse_request_list(request_invoice_keys)

        if data.get('usarDtMov') and data.get('usarDtMov') == '1':
            clauses = [Sale.confirm_date >= initial_date, Sale.confirm_date <= end_date]
        else:
            clauses = [Sale.open_date >= initial_date, Sale.open_date <= end_date]

        ClientPerson = ClassAlias(Person, 'person_client')
        ClientIndividual = ClassAlias(Individual, 'individual_client')
        ClientCompany = ClassAlias(Company, 'company_client')

        SalesPersonPerson = ClassAlias(Person, 'person_sales_person')
        SalesPersonIndividual = ClassAlias(Individual, 'individual_sales_person')

        tables = [
            Sale,
            Join(Branch, Sale.branch_id == Branch.id),
            LeftJoin(Client, Client.id == Sale.client_id),
            Join(Person, Person.id == Client.person_id),
            Join(BranchStation, Sale.station_id == BranchStation.id),
            LeftJoin(ClientPerson, Client.person_id == ClientPerson.id),
            LeftJoin(ClientIndividual, Client.person_id == ClientIndividual.person_id),
            LeftJoin(Individual, Client.person_id == Individual.person_id),
            LeftJoin(ClientCompany, Client.person_id == ClientCompany.person_id),
            LeftJoin(Company, Client.person_id == Company.person_id),
            LeftJoin(SalesPerson, SalesPerson.id == Sale.salesperson_id),
            LeftJoin(SalesPersonPerson, SalesPerson.person_id == SalesPersonPerson.id),
            LeftJoin(SalesPersonIndividual,
                     SalesPerson.person_id == SalesPersonIndividual.person_id),
            Join(LoginUser, LoginUser.person_id == SalesPerson.person_id),
            Join(PaymentGroup, PaymentGroup.id == Sale.group_id),
            Join(Invoice, Invoice.id == Sale.invoice_id),
        ]

        sale_item_tables = [
            SaleItem,
            Join(Sellable, SaleItem.sellable_id == Sellable.id),
            Join(Product, SaleItem.sellable_id == Product.id),
            LeftJoin(SellableCategory, Sellable.category_id == SellableCategory.id),
            LeftJoin(TransactionEntry, SellableCategory.te_id == TransactionEntry.id),
            LeftJoin(InvoiceItemIcms, InvoiceItemIcms.id == SaleItem.icms_info_id),
            LeftJoin(CfopData, CfopData.id == SaleItem.cfop_id)
        ]

        payment_tables = [
            Payment,
            Join(PaymentMethod, Payment.method_id == PaymentMethod.id),
            Join(PaymentGroup, Payment.group_id == PaymentGroup.id),
        ]

        sale_objs = (Sale, ClientCompany, ClientIndividual, LoginUser, Invoice, Branch,
                     PaymentGroup, BranchStation, Client, ClientPerson, SalesPerson,
                     SalesPersonPerson)

        sale_items_objs = (SaleItem, Sellable, SellableCategory, Product, CfopData,
                           TransactionEntry, InvoiceItemIcms)

        payment_objs = (Payment, PaymentMethod, PaymentGroup)

        if len(branch_ids) > 0:
            clauses.append(Branch.id.is_in(branch_ids))

        if len(documents) > 0:
            clauses.append(Or(Individual.cpf.is_in(documents), Company.cnpj.is_in(documents)))

        if len(invoice_keys) > 0:
            clauses.append(Invoice.key.is_in(invoice_keys))

        if data.get('cancelados') and data.get('cancelados') == '0':
            clauses.append(Sale.status != Sale.STATUS_CANCELLED)

        data = list(store.using(*tables).find(sale_objs, And(*clauses)))

        sale_ids = [i[0].id for i in data]
        group_ids = [i[0].group_id for i in data]
        sale_items = list(store.using(*sale_item_tables).find(sale_items_objs,
                                                              SaleItem.sale_id.is_in(sale_ids)))
        payments_list = list(store.using(*payment_tables).find(payment_objs,
                                                               Payment.group_id.is_in(group_ids)))

        sale_payments = {}
        for payment in payments_list:
            sale_payments.setdefault(payment[0].group_id, [])
            sale_payments[payment[0].group_id].append(payment[0])

        sales = {}
        for item in sale_items:
            sales.setdefault(item[0].sale_id, [])
            sales[item[0].sale_id].append(item[0])

        response = []

        for row in data:
            sale, company, individual, login_user, invoice = row[:5]
            items = []
            for item in sales[sale.id]:
                discount = item.item_discount
                product = item.sellable.product
                items.append({
                    'ordem': None,
                    'idMaterial': item.sellable.id,
                    'codigo': item.sellable.code,
                    'descricao': item.sellable.description,
                    'quantidade': float(item.quantity),
                    'valorBruto': float(item.base_price * item.quantity),
                    'valorUnitario': float(item.base_price),
                    'valorUnitarioLiquido': float(item.price),
                    'valorLiquido': float(item.price * item.quantity),
                    'codNcm': product.ncm,
                    'idOrigem': None,
                    'codOrigem': None,
                    'cfop': str(item.cfop.code),
                    'desconto': float(max(discount, 0)),
                    'acrescimo': float(-1 * min(discount, 0)),
                    'cancelado': sale.status == Sale.STATUS_CANCELLED,
                    'maquinaId': sale.station.id,
                    'nomeMaquina': sale.station.name,
                    'maquinaCod': sale.station.code,
                    'isTaxa': None,
                    'isRepique': None,
                    'isGorjeta': None,
                    'isEntrega': None,
                })

            payment_methods = _get_payments_info(sale_payments[sale.group_id], login_user, sale)
            change = sum(payment['troco'] for payment in payment_methods)

            res_item = {
                'maquinaCod': sale.station.code,
                'nomeMaquina': sale.station.name,
                'nfNumero': invoice.invoice_number,
                'nfSerie': invoice.series,
                'denominacao': invoice.mode,
                'valor': float(sale.total_amount),
                'maquinaId': sale.station.id,
                'desconto': float(sale.discount_value or 0),
                'acrescimo': float(sale.surcharge_value or 0),
                'chaveNfe': invoice.key,
                # FIXME B1Food expect this date to be the same as the emission date
                # we want the emission date of nfe_data for this field
                # https://gitlab.com/stoqtech/private/stoq-plugin-nfe/-/issues/111
                'dataContabil': sale.confirm_date.strftime('%Y-%m-%d'),
                'dataEmissao': sale.confirm_date.strftime('%Y-%m-%d %H:%M:%S -0300'),
                'idOperacao': sale.id,
                'troco': change,
                'pagamentos': float(sale.paid),
                'dataMovimento': sale.confirm_date.strftime('%Y-%m-%d %H:%M:%S -0300'),
                'cancelado': sale.status == Sale.STATUS_CANCELLED,
                'detalhes': items,
                'meios': payment_methods,
            }

            response.append(res_item)

        return response


class B1FoodTillResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider, info_logger]
    routes = ['/b1food/terceiros/restful/periodos']

    def get(self, store):
        return []


class B1FoodRolesResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider, info_logger]
    routes = ['/b1food/terceiros/restful/cargos']

    def get(self, store):
        roles = store.find(EmployeeRole)

        network = _get_network_info()

        response = []
        for role in roles:
            response.append({
                'ativo': True,
                'id': role.id,
                'codigo': role.id,
                'dataCriacao': role.te.te_time.strftime('%Y-%m-%d %H:%M:%S -0300'),
                'dataAlteracao': role.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
                'nome': role.name,
                'redeId': network['id'],
                'lojaId': None
            })

        return response


class B1FoodBranchResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider, info_logger]
    routes = ['/b1food/terceiros/restful/rede-loja']

    def get(self, store):
        data = request.args

        tables = [Branch]
        query = None

        active = data.get('ativo')

        if active is not None:
            is_active = active == '1'
            query = Branch.is_active == is_active

        if query:
            branches = store.using(*tables).find(Branch, query)
        else:
            branches = store.using(*tables).find(Branch)

        network = _get_network_info()

        response = [{
            'idRede': network['id'],
            'nome': network['name'],
            'ativo': True,
            'idRedePai': None,
            'lojas': [],
        }]
        for branch in branches:
            response[0]['lojas'].append({
                'idLoja': branch.id,
                'nome': branch.name,
                'ativo': branch.is_active
            })

        return response


class B1FoodDiscountCategoryResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider, info_logger]
    routes = ['/b1food/terceiros/restful/tiposdescontos']

    def get(self, store):
        categories = store.find(ClientCategory)

        network = _get_network_info()

        response = []
        for category in categories:
            response.append({
                'ativo': True,
                'id': category.id,
                'codigo': category.id,
                'dataCriacao': category.te.te_time.strftime('%Y-%m-%d %H:%M:%S -0300'),
                'dataAlteracao': category.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
                'nome': category.name,
                'redeId': network['id'],
                'lojaId': None
            })

        return response


class B1FoodLoginUserResource(BaseResource):
    method_decorators = [b1food_login_required, store_provider, info_logger]
    routes = ['/b1food/terceiros/restful/funcionarios']

    def get(self, store):
        data = request.args

        request_branches = data.get('lojas')
        branch_ids = _parse_request_list(request_branches)

        active_users = LoginUser.get_active_users(store)

        user_access_list = []
        if len(branch_ids) > 0:
            for user in active_users:
                associeted_branches = user.get_associated_branches()
                for user_access in associeted_branches:
                    if user_access.branch.id in branch_ids:
                        user_access_list.append(user_access)
        else:
            for user in active_users:
                for user_access in user.get_associated_branches():
                    user_access_list.append(user_access)

        response = []
        for user_access in user_access_list:
            name = user_access.user.person.name
            if ' ' in name:
                firstname, lastname = name.split(' ', maxsplit=1)
            else:
                firstname = name
                lastname = ''
            profile = user_access.user.profile
            network = _get_network_info()

            response.append({
                'id': user_access.user.id,
                'codigo': user_access.user.username,
                'dataCriacao': user_access.user.te.te_time.strftime('%Y-%m-%d %H:%M:%S -0300'),
                'dataAlteracao': user_access.user.te.te_server.strftime('%Y-%m-%d %H:%M:%S -0300'),
                'primeiroNome': firstname,
                'sobrenome': lastname,
                'apelido': None,
                'idCargo': profile.id if profile else None,
                'codCargo': None,
                'nomeCargo': profile.name if profile else None,
                'redeId': network['id'],
                'lojaId': user_access.branch.id,
                'dtContratacao': None,
            })

        return response
