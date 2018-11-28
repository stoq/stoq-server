# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2018 Async Open Source <http://www.async.com.br>
## All rights reserved
##
## This program is free software; you can redistribute it and/or
## modify it under the terms of the GNU Lesser General Public License
## as published by the Free Software Foundation; either version 2
## of the License, or (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU Lesser General Public License for more details.
##
## You should have received a copy of the GNU Lesser General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., or visit: http://www.gnu.org/.
##
## Author(s): Stoq Team <stoq-devel@async.com.br>
##

import datetime
import contextlib
import hashlib
import json

import mock
from kiwi.currency import currency
from stoqlib.api import api
from stoqlib.domain.sale import Sale
from stoqlib.domain.test.domaintest import DomainTest
from stoqlib.lib.configparser import register_config, StoqConfig
from storm.expr import Desc

from stoqserver.lib.restful import (bootstrap_app,
                                    PingResource,
                                    LoginResource,
                                    DataResource,
                                    SaleResource,
                                    ImageResource)


class _TestFlask(DomainTest):

    resource_class = None

    def setUp(self):
        super().setUp()

        from stoqntk.ntkui import NtkUI
        register_config(StoqConfig())
        self.plugin = NtkUI()
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
        u = self.create_user()
        rv = self.client.post('/login',
                              data={'user': u.username, 'pw_hash': u.pw_hash})
        return json.loads(rv.data.decode())

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
            rv = self.client.post('/login',
                                  data={'user': 'foo', 'pw_hash': 'bar'})
            self.assertEqual(rv.status_code, 403),
            self.assertEqual(json.loads(rv.data.decode()),
                             {'message': 'Invalid user or password'})

            # Create user foo
            u = self.create_user(username='foo')
            u.set_password('bar')

            # foo with wrong password
            rv = self.client.post('/login',
                                  data={'user': 'foo', 'pw_hash': '_wrong_'})
            self.assertEqual(rv.status_code, 403),
            self.assertEqual(json.loads(rv.data.decode()),
                             {'message': 'Invalid user or password'})

            # foo with wrong password (unhashed)
            rv = self.client.post('/login',
                                  data={'user': 'foo', 'pw_hash': 'bar'})
            self.assertEqual(rv.status_code, 403),
            self.assertEqual(json.loads(rv.data.decode()),
                             {'message': 'Invalid user or password'})

            # foo with right password
            rv = self.client.post('/login',
                                  data={'user': 'foo', 'pw_hash': u.hash('bar')})
            self.assertEqual(rv.status_code, 200)
            self.assertEqual(json.loads(rv.data.decode()), u.id)


class TestDataResource(_TestFlask):

    resource_class = DataResource

    def test_get(self):
        with self.fake_store():
            s = self.login()
            b = api.get_current_branch(self.store)

            s1 = self.create_sellable(description='s1')
            self.create_storable(product=s1.product, stock=10, branch=b)
            s2 = self.create_sellable(description='s2')
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

            rv = self.client.get('/data', headers={'stoq-session': s})
            self.assertEqual(rv.status_code, 200)

            retval = json.loads(rv.data.decode())
            self.assertEqual(retval['branch'], b.id)
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
            self.assertEqual(
                adjust_categories(retval['categories']),
                [{'children': [{'children': [],
                                'description': 'c2',
                                'products': [{'availability': {b.id: '20.000'},
                                              'order': '0',
                                              'category_prices': {},
                                              'color': '',
                                              'description': 's2',
                                              'price': '10'},
                                             {'availability': None,
                                              'order': '0',
                                              'category_prices': {},
                                              'color': '',
                                              'description': 's4',
                                              'price': '10'}]}],
                  'description': 'c1',
                  'products': [{'availability': {b.id: '10.000'},
                                'order': '0',
                                'category_prices': {},
                                'color': '',
                                'description': 's1',
                                'price': '10'}]},
                 {'children': [],
                  'description': 'c3',
                  'products': [{'availability': {b.id: '30.000'},
                                'order': '0',
                                'category_prices': {},
                                'color': '',
                                'description': 's3',
                                'price': '10'}]},
                 {'children': [], 'description': 'c4', 'products': []}]
            )


class TestSaleResource(_TestFlask):

    resource_class = SaleResource

    @mock.patch('stoqserver.lib.restful.hashlib')
    def test_post(self, hl):
        hl.sha1.return_value = hashlib.sha1(b'foo')

        with self.sysparam(DEMO_MODE=True):
            with self.fake_store() as es:
                e = es.enter_context(
                    mock.patch('stoqserver.lib.restful.SaleConfirmedRemoteEvent.emit'))
                d = datetime.datetime(2018, 3, 6, 4, 20, 53)
                now = es.enter_context(
                    mock.patch('stoqserver.lib.restful.localnow'))
                now.return_value = d
                tt = es.enter_context(
                    mock.patch('stoqlib.domain.sale.TransactionTimestamp'))
                tt.return_value = d
                s = self.login()

                p1 = self.create_product(price=10)
                p1.manage_stock = False
                s1 = p1.sellable

                p2 = self.create_product(price=currency('20.5'))
                p2.manage_stock = False
                s2 = p2.sellable

                c = self.create_client()
                c.person.individual.cpf = '333.341.828-27'

                rv = self.client.post(
                    '/sale',
                    headers={'stoq-session': s},
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

                self.assertEqual(rv.status_code, 200)
                self.assertEqual(json.loads(rv.data.decode()), True)

                # This should be the sale made by the call above
                sale = self.store.find(Sale).order_by(Desc(Sale.open_date)).first()
                self.assertEqual(sale.get_total_sale_amount(), currency('40.5'))
                self.assertEqual(sale.open_date, d)
                self.assertEqual(sale.confirm_date, d)
                self.assertEqual(
                    {(i.sellable, i.quantity, i.price) for i in sale.get_items()},
                    {(s1, 2, s1.price),
                     (s2, 1, s2.price)})
                self.assertEqual(
                    {(p.method.method_name, p.due_date, p.value)
                     for p in sale.group.get_items()},
                    {('card', d, currency('15')),
                     ('card', datetime.datetime(2018, 4, 6, 4, 20, 53), currency('15')),
                     ('money', d, currency('10.5'))}
                )

                self.assertEqual(e.call_count, 1)
                (sale, doc), _ = e.call_args_list[0]
                self.assertEqual(doc, '333.341.828-27')

                # Test the same sale again, but this time, lets mimic an exception
                # happening in SaleConfirmedRemoteEvent
                e.side_effect = Exception('foobar exception')

                # Add a till to Store
                self.create_till()

                # NOTE: This will print the original traceback to stdout, that
                # doesn't mean that the test is failing (unless it really fail)
                rv = self.client.post(
                    '/sale',
                    headers={'stoq-session': s},
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


class TestImageResource(_TestFlask):

    resource_class = ImageResource

    def test_get(self):
        with self.sysparam(DEMO_MODE=True):
            with self.fake_store():
                api.get_current_branch(self.store)
                s = self.login()

                sellable = self.create_sellable()
                img = self.create_image()
                img.image = b'foobar'
                img.sellable_id = sellable.id

                rv = self.client.get('/image/' + sellable.id, headers={'stoq-session': s})
                self.assertEqual(rv.status_code, 200)
                self.assertEqual(rv.data, b'foobar')
