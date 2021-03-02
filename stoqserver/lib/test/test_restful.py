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

import datetime
import contextlib
import hashlib
import json
from decimal import Decimal
from unittest import mock

from stoqlib.api import api
from stoqlib.domain.sale import Sale, SaleItem
from stoqlib.domain.transfer import TransferOrderItem
from stoqlib.domain.receiving import ReceivingOrderItem
from stoqlib.domain.purchase import PurchaseItem
from stoqlib.domain.service import Service
from stoqlib.domain.product import (Product, Storable, ProductStockItem, StockTransactionHistory,
                                    ProductSupplierInfo, ProductHistory)
from stoqlib.domain.sellable import Sellable, SellableCategory
from stoqlib.domain.commission import CommissionSource
from stoqlib.domain.test.domaintest import DomainTest
from stoqlib.lib.configparser import register_config, StoqConfig
from storm.expr import Desc

from stoqserver.app import bootstrap_app
from stoqserver.lib.restful import (PingResource,
                                    LoginResource,
                                    DataResource,
                                    SaleResource,
                                    ImageResource)


class _TestFlask(DomainTest):

    resource_class = None

    def setUp(self):
        super().setUp()

        register_config(StoqConfig())
        app = bootstrap_app()
        app.testing = True
        self.client = app.test_client()

    @contextlib.contextmanager
    def fake_store(self, mock_rollback=False):
        with contextlib.ExitStack() as es:
            es.enter_context(mock.patch.object(self.store, 'commit')),
            es.enter_context(mock.patch.object(self.store, 'close')),
            if mock_rollback:
                es.enter_context(mock.patch.object(self.store, 'rollback')),

            new_store = es.enter_context(
                mock.patch('stoqserver.lib.restful.api.new_store'))
            new_store.return_value = self.store

            yield es

    def login(self):
        user = api.get_current_user(self.store) or self.create_user()
        station = api.get_current_station(self.store) or self.create_station()
        station.is_active = True
        rv = self.client.post(
            '/login',
            data={'user': user.username, 'pw_hash': user.pw_hash, 'station_name': station.name})
        ans = json.loads(rv.data.decode())
        return ans['token'].replace('JWT', 'Bearer')

    def test_get(self):
        for route in self.resource_class.routes:
            self.assertEqual(self.client.get(route).status_code, 405)

    def test_post(self):
        for route in self.resource_class.routes:
            self.assertEqual(self.client.post(route).status_code, 405)

    def test_put(self):
        for route in self.resource_class.routes:
            self.assertEqual(self.client.put(route).status_code, 405)

    def test_delete(self):
        for route in self.resource_class.routes:
            self.assertEqual(self.client.delete(route).status_code, 405)


class TestPingResource(_TestFlask):

    resource_class = PingResource

    def test_get(self):
        self.assertEqual(
            json.loads(self.client.get('/ping').data.decode()), 'pong from stoqserver')


class TestLoginResource(_TestFlask):

    resource_class = LoginResource

    def test_post(self):
        with self.fake_store(mock_rollback=True):
            # foo user doesn't exist
            station = self.create_station()
            station.is_active = True
            rv = self.client.post(
                '/login', data={'user': 'foo', 'pw_hash': 'bar', 'station_name': station.name})
            self.assertEqual(rv.status_code, 403),
            self.assertEqual(json.loads(rv.data.decode()),
                             {'message': 'Invalid user or password'})

            # Create user foo
            u = self.create_user(username='foo')
            u.set_password('bar')

            # foo with wrong password
            rv = self.client.post(
                '/login', data={'user': 'foo', 'pw_hash': '_wrong_', 'station_name': station.name})
            self.assertEqual(rv.status_code, 403),
            self.assertEqual(json.loads(rv.data.decode()),
                             {'message': 'Invalid user or password'})

            # foo with wrong password (unhashed)
            rv = self.client.post(
                '/login', data={'user': 'foo', 'pw_hash': 'bar', 'station_name': station.name})
            self.assertEqual(rv.status_code, 403),
            self.assertEqual(json.loads(rv.data.decode()),
                             {'message': 'Invalid user or password'})

            # foo with right password
            rv = self.client.post(
                '/login',
                data={'user': 'foo', 'pw_hash': u.hash('bar'), 'station_name': station.name})
            self.assertEqual(rv.status_code, 200)
            self.assertEqual(json.loads(rv.data.decode())['user']['id'], u.id)


class TestDataResource(_TestFlask):

    resource_class = DataResource

    def test_get_without_sellables(self):
        # We must remove every thing that references sellable in order to remove all sellables
        self.clean_domain([Service, StockTransactionHistory, ProductStockItem, ProductHistory,
                           SaleItem, ReceivingOrderItem, PurchaseItem, TransferOrderItem,
                           ProductSupplierInfo, Storable, Product, Sellable, CommissionSource,
                           SellableCategory])

        with self.fake_store():
            # Close all sellables
            token = self.login()
            rv = self.client.get('/data', headers={'Authorization': token})
            self.assertEqual(rv.status_code, 200)

            retval = json.loads(rv.data.decode())
            self.assertEqual(retval['categories'], [])

    def test_get(self):
        with self.fake_store():
            token = self.login()
            b = api.get_current_branch(self.store)

            s1 = self.create_sellable(description='s1')
            self.create_storable(product=s1.product, stock=10, branch=b)
            s2 = self.create_sellable(description='s2')
            s2.short_description = '2'
            self.create_storable(product=s2.product, stock=20, branch=b)
            s3 = self.create_sellable(description='s3')
            self.create_storable(product=s3.product, stock=30, branch=b)
            s4 = self.create_sellable(description='s4')

            c1 = self.create_sellable_category(description='c1')
            c2 = self.create_sellable_category(description='c2')
            c3 = self.create_sellable_category(description='c3')
            c4 = self.create_sellable_category(description='c4')

            c2.category = c1
            s1.category = c1
            s2.category = c2
            s3.category = c3
            s4.category = c2

            img = self.create_image()
            img.image = b'foobar'
            img.sellable_id = s1.id
            img.is_main = True

            c_ids = [c1.id, c2.id, c3.id, c4.id]

            def adjust_categories(obj):
                if isinstance(obj, dict):
                    del obj['id']
                    for c in obj['children']:
                        adjust_categories(c)
                    obj['products'].sort(key=lambda k: k['description'])
                    for p in obj['products']:
                        del p['id']
                elif isinstance(obj, list):
                    obj.sort(key=lambda k: k['description'])
                    for o in obj[:]:
                        if o['id'] not in c_ids:
                            obj.remove(o)
                        else:
                            adjust_categories(o)
                return obj

            rv = self.client.get('/data', headers={'Authorization': token})
            self.assertEqual(rv.status_code, 200)

            retval = json.loads(rv.data.decode())
            self.assertEqual(retval['branch'], b.id)
            self.assertEqual(retval['parameters'], {
                'NFCE_CAN_SEND_DIGITAL_INVOICE': False,
                'NFE_SEFAZ_TIMEOUT': 10,
                'PASSBOOK_FIDELITY': None,
                'SCALE_BARCODE_FORMAT': 0,
                'INCLUDE_CASH_FUND_ON_TILL_CLOSING': False,
                'AUTOMATIC_LOGOUT': 0,
            })
            # Those are the default payment methods created by example data
            self.assertEqual(
                retval['payment_methods'],
                [{'name': 'bill', 'max_installments': 12},
                 {'name': 'card', 'max_installments': 12,
                  'card_types': ['credit', 'debit']},
                 {'name': 'check', 'max_installments': 12},
                 {'name': 'credit', 'max_installments': 1},
                 {'name': 'money', 'max_installments': 1},
                 {'name': 'multiple', 'max_installments': 12},
                 {'name': 'store_credit', 'max_installments': 1}]
            )

            self.assertTrue(isinstance(retval['categories'], list))
            self.assertEqual(
                adjust_categories(retval['categories']),
                [{'children': [{'children': [],
                                'description': 'c2',
                                'order': 0,
                                'products': [{'availability': {b.id: '20.000'},
                                              'order': '0',
                                              'category_prices': {},
                                              'color': '',
                                              'description': 's2',
                                              'short_description': '2',
                                              'code': '',
                                              'barcode': '',
                                              'price': '10',
                                              'requires_kitchen_production': False,
                                              'has_image': False},
                                             {'availability': None,
                                              'order': '0',
                                              'category_prices': {},
                                              'color': '',
                                              'code': '',
                                              'barcode': '',
                                              'description': 's4',
                                              'short_description': '',
                                              'price': '10',
                                              'requires_kitchen_production': False,
                                              'has_image': False}]}],
                  'description': 'c1',
                  'order': 0,
                  'products': [{'availability': {b.id: '10.000'},
                                'order': '0',
                                'category_prices': {},
                                'color': '',
                                'description': 's1',
                                'short_description': '',
                                'code': '',
                                'barcode': '',
                                'price': '10',
                                'requires_kitchen_production': False,
                                'has_image': True}]},
                 {'children': [],
                  'description': 'c3',
                  'order': 0,
                  'products': [{'availability': {b.id: '30.000'},
                                'order': '0',
                                'category_prices': {},
                                'color': '',
                                'description': 's3',
                                'short_description': '',
                                'code': '',
                                'barcode': '',
                                'price': '10',
                                'requires_kitchen_production': False,
                                'has_image': False}]},
                 {'children': [], 'description': 'c4', 'order': 0, 'products': []}]
            )


class TestSaleResource(_TestFlask):

    resource_class = SaleResource

    @mock.patch('stoqserver.app.hashlib')
    def test_post(self, hl):
        hl.sha1.return_value = hashlib.sha1(b'foo')

        with self.sysparam(DEMO_MODE=True):
            with self.fake_store() as es:
                e = es.enter_context(
                    mock.patch('stoqserver.lib.restful.SaleConfirmedRemoteEvent.emit'))
                e.return_value = {}
                d = datetime.datetime(2018, 3, 6, 4, 20, 53)
                restful_now = es.enter_context(mock.patch('stoqserver.lib.restful.localnow'))
                restful_now.return_value = d
                app_now = es.enter_context(mock.patch('stoqserver.app.localnow'))
                app_now.return_value = d
                tt = es.enter_context(
                    mock.patch('stoqlib.domain.sale.TransactionTimestamp'))
                tt.return_value = d
                token = self.login()

                p1 = self.create_product(price=10)
                p1.manage_stock = False
                s1 = p1.sellable

                p2 = self.create_product(price=Decimal('20.5'))
                p2.manage_stock = False
                s2 = p2.sellable

                c = self.create_client()
                c.person.individual.cpf = '333.341.828-27'

                # Add a till to Store
                till = self.create_till()
                user = self.create_user()
                till.open_till(user)

                rv = self.client.post(
                    '/sale',
                    headers={'Authorization': token},
                    content_type='application/json',
                    data=json.dumps({
                        'client_document': '999.999.999-99',
                        'coupon_document': '333.341.828-27',
                        'products': [
                            {'id': s1.id,
                             'price': str(s1.price),
                             'quantity': 2},
                            {'id': s2.id,
                             'price': str(s2.price),
                             'quantity': 1},
                        ],
                        'payments': [
                            {'method': 'money',
                             'mode': None,
                             'provider': None,
                             'installments': 1,
                             'value': '10.5'},
                            {'method': 'card',
                             'mode': 'credit',
                             'provider': 'VISA',
                             'installments': 2,
                             'value': '30',
                             'card_type': 'credit'},
                        ],
                    }),
                )

                self.assertEqual(rv.status_code, 201)

                reponse_data = json.loads(rv.data.decode())
                self.assertIn('sale_id', reponse_data)
                self.assertIn('client_id', reponse_data)
                self.assertEqual(reponse_data['client_id'], None)

                # This should be the sale made by the call above
                sale = self.store.find(Sale).order_by(Desc(Sale.open_date)).first()
                self.assertEqual(sale.get_total_sale_amount(), Decimal('40.5'))
                self.assertEqual(sale.open_date, d)
                self.assertEqual(sale.confirm_date, d)
                self.assertEqual(
                    {(i.sellable, i.quantity, i.price) for i in sale.get_items()},
                    {(s1, 2, s1.price),
                     (s2, 1, s2.price)})
                self.assertEqual(
                    {(p.method.method_name, p.due_date, p.value)
                     for p in sale.group.get_items()},
                    {('card', d, Decimal('15')),
                     ('card', datetime.datetime(2018, 4, 6, 4, 20, 53), Decimal('15')),
                     ('money', d, Decimal('10.5'))}
                )

                self.assertEqual(e.call_count, 1)
                retval = e.call_args_list[0]
                self.assertEqual(len(retval), 2)
                self.assertEqual(retval[0][1], '333.341.828-27')

                # Test the same sale again, but this time, lets mimic an exception
                # happening in SaleConfirmedRemoteEvent
                e.side_effect = Exception('foobar exception')

                # NOTE: This will print the original traceback to stdout, that
                # doesn't mean that the test is failing (unless it really fail)
                rv = self.client.post(
                    '/sale',
                    headers={'Authorization': token},
                    content_type='application/json',
                    data=json.dumps({
                        'client_document': '333.341.828-27',
                        'products': [
                            {'id': s1.id,
                             'price': str(s1.price),
                             'quantity': 2},
                            {'id': s2.id,
                             'price': str(s2.price),
                             'quantity': 1},
                        ],
                        'payments': [
                            {'method': 'money',
                             'value': '40.5'},
                        ],
                    }),
                )
                self.assertEqual(rv.status_code, 500)
                self.assertEqual(json.loads(rv.data.decode()),
                                 {'error': 'bad request!',
                                  'exception': 'Exception: foobar exception\n',
                                  'timestamp': '20180306-042053',
                                  'traceback_hash': '0beec7b5'})

    def test_get(self):
        with self.sysparam(DEMO_MODE=True):
            with self.fake_store():
                token = self.login()
                sale = self.create_sale()
                sale_id = sale.id
                rv = self.client.get(
                    '/sale/{}'.format(sale_id),
                    headers={'Authorization': token})
                recv_sale = json.loads(rv.data.decode())
                self.assertEqual(rv.status_code, 200)
                self.assertEqual(recv_sale['id'], sale_id)

    def test_delete(self):
        pass


class TestImageResource(_TestFlask):

    resource_class = ImageResource

    def test_get(self):
        with self.sysparam(DEMO_MODE=True):
            with self.fake_store():
                api.get_current_branch(self.store)

                sellable = self.create_sellable()
                img = self.create_image()
                img.image = b'foobar'
                img.sellable_id = sellable.id

                rv = self.client.get('/image/' + sellable.id)
                self.assertEqual(rv.status_code, 200)
                self.assertEqual(rv.data, b'foobar')

                sellable2 = self.create_sellable()
                rv = self.client.get('/image/' + sellable2.id)
                self.assertEqual(rv.status_code, 404)
                self.assertEqual(rv.data, b'Image not found.')
