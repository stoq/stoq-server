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

import base64
import contextlib
import datetime
import decimal
import functools
import json
import logging
import os
import pickle
import psycopg2
from gevent.queue import Queue
from gevent.event import Event
from gevent.lock import Semaphore
import io
import select
import traceback
import hashlib
import requests
from hashlib import md5

from gevent.pywsgi import WSGIServer
import gevent
from blinker import signal

from kiwi.component import provide_utility
from kiwi.currency import currency
from flask import Flask, request, session, abort, send_file, make_response, Response
from flask_restful import Api, Resource
from raven.contrib.flask import Sentry
from serial.serialutil import SerialException
from stoqdrivers.exceptions import InvalidReplyException

from stoqlib.api import api
from stoqlib.database.runtime import get_current_station
from stoqlib.database.interfaces import ICurrentUser
from stoqlib.domain.events import SaleConfirmedRemoteEvent
from stoqlib.domain.devices import DeviceSettings
from stoqlib.domain.image import Image
from stoqlib.domain.overrides import ProductBranchOverride, SellableBranchOverride
from stoqlib.domain.payment.group import PaymentGroup
from stoqlib.domain.payment.method import PaymentMethod
from stoqlib.domain.payment.card import CreditCardData, CreditProvider, CardPaymentDevice
from stoqlib.domain.payment.payment import Payment
from stoqlib.domain.person import LoginUser, Person, Client, ClientCategory
from stoqlib.domain.product import Product
from stoqlib.domain.sale import Sale
from stoqlib.domain.sellable import (Sellable, SellableCategory,
                                     ClientCategoryPrice)
from stoqlib.domain.till import Till, TillSummary
from stoqlib.exceptions import LoginError
from stoqlib.lib.configparser import get_config
from stoqlib.lib.dateutils import (INTERVALTYPE_MONTH, create_date_interval,
                                   localnow)
from stoqlib.lib.environment import is_developer_mode
from stoqlib.lib.formatters import raw_document
from stoqlib.lib.osutils import get_application_dir
from stoqlib.lib.translation import dgettext
#from stoqlib.lib.threadutils import threadit
from stoqlib.lib.pluginmanager import get_plugin_manager, PluginError
from storm.expr import Desc, LeftJoin, Join, And, Ne

from stoqserver import main
from stoqserver.lib.lock import lock_pinpad, lock_sat, LockFailedException

_ = lambda s: dgettext('stoqserver', s)

try:
    from stoqnfe.events import NfeProgressEvent, NfeWarning, NfeSuccess
    from stoqnfe.exceptions import PrinterException as NfePrinterException, NfeRejectedException
    has_nfe = True
except ImportError:
    has_nfe = False

    class NfePrinterException(Exception):
        pass

    class NfeRejectedException(Exception):
        pass

try:
    from stoqsat.exceptions import PrinterException as SatPrinterException
    has_sat = True
except ImportError:
    has_sat = False

    class SatPrinterException(Exception):
        pass

_last_gc = None
_expire_time = datetime.timedelta(days=1)
_session = None
_printer_lock = Semaphore()
log = logging.getLogger(__name__)

TRANSPARENT_PIXEL = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='  # nopep8

WORKERS = []

# Device status events
CheckSatStatusEvent = signal('CheckSatStatusEvent')
CheckPinpadStatusEvent = signal('CheckPinpadStatusEvent')

# Tef events
TefPrintReceiptsEvent = signal('TefPrintReceiptsEvent')
TefCheckPendingEvent = signal('TefCheckPendingEvent')


def override(column):
    from storm.references import Reference

    # Column is already a property. No need to override it.
    if isinstance(column, property):
        return column

    # Save a reference to the original column
    if isinstance(column, Reference):
        name = column._relation.local_key[0].name[:-3]
        klass = column._cls
        setattr(klass, '__' + name, column)
    else:
        assert False, type(column)

    def _get(self):
        branch = api.get_current_branch(self.store)

        if klass == Sellable:
            override = self.store.find(SellableBranchOverride, sellable=self, branch=branch).one()
        elif klass == Product:
            override = self.store.find(ProductBranchOverride, product=self, branch=branch).one()

        original = getattr(self, '__' + name)
        return getattr(override, name, original) or original

    def _set(self, value):
        assert False

    return property(_get, _set)


# Monkey patch sellable overrides until we release a new version of stoq
Sellable.default_sale_cfop = override(Sellable.default_sale_cfop)


def _get_user_hash():
    return md5(
        api.sysparam.get_string('USER_HASH').encode('UTF-8')).hexdigest()


@contextlib.contextmanager
def _get_session():
    global _session
    global _last_gc

    # Indexing some session data by the USER_HASH will help to avoid
    # maintaining sessions between two different databases. This could lead to
    # some errors in the POS in which the user making the sale does not exist.
    session_file = os.path.join(
        get_application_dir(), 'session-{}.db'.format(_get_user_hash()))
    if os.path.exists(session_file):
        with open(session_file, 'rb') as f:
            try:
                _session = pickle.load(f)
            except Exception:
                _session = {}
    else:
        _session = {}

    # From time to time remove old entries from the session dict
    now = localnow()
    if now - (_last_gc or datetime.datetime.min) > _expire_time:
        for k, v in list(_session.items()):
            if now - v['date'] > _expire_time:
                del _session[k]
        _last_gc = localnow()

    yield _session

    with open(session_file, 'wb') as f:
        pickle.dump(_session, f)


def _login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        session_id = request.headers.get('stoq-session', None)
        # FIXME: Remove this once all frontends are updated.
        if session_id is None:
            abort(401, 'No session id provided in header')

        user_id = request.headers.get('stoq-user', None)
        with api.new_store() as store:
            user = (user_id or session_id) and store.get(LoginUser, user_id or session_id)
            if user:
                provide_utility(ICurrentUser, user, replace=True)
                return f(*args, **kwargs)

        with _get_session() as s:
            session_data = s.get(session_id, None)
            if session_data is None:
                abort(401, 'Session does not exist')

            if localnow() - session_data['date'] > _expire_time:
                abort(401, 'Session expired')

            # Refresh last date to avoid it expiring while being used
            session_data['date'] = localnow()
            session['user_id'] = session_data['user_id']
            with api.new_store() as store:
                user = store.get(LoginUser, session['user_id'])
                provide_utility(ICurrentUser, user, replace=True)

        return f(*args, **kwargs)

    return wrapper


def _store_provider(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        with api.new_store() as store:
            try:
                return f(store, *args, **kwargs)
            except Exception as e:
                store.retval = False
                raise e

    return wrapper


def worker(f):
    """A marker for a function that should be threaded when the server executes.

    Usefull for regular checks that should be made on the server that will require warning the
    client
    """
    WORKERS.append(f)
    return f


def lock_printer(func):
    """Decorator to handle printer access locking.

    This will make sure that only one callsite is using the printer at a time.
    """
    def new_func(*args, **kwargs):
        if _printer_lock.locked():
            log.info('Waiting printer lock release in func %s' % func)

        with _printer_lock:
            return func(*args, **kwargs)

    return new_func


def get_plugin(manager, name):
    try:
        return manager.get_plugin(name)
    except PluginError:
        return None


def _nfe_progress_event(message):
    EventStream.put({'type': 'NFE_PROGRESS', 'message': message})


def _nfe_warning_event(message, details):
    EventStream.put({'type': 'NFE_WARNING', 'message': message, 'details': details})


def _nfe_success_event(message, details=None):
    EventStream.put({'type': 'NFE_SUCCESS', 'message': message, 'details': details})


if has_nfe:
    NfeProgressEvent.connect(_nfe_progress_event)
    NfeWarning.connect(_nfe_warning_event)
    NfeSuccess.connect(_nfe_success_event)


class UnhandledMisconfiguration(Exception):
    pass


class _BaseResource(Resource):

    routes = []

    def get_json(self):
        if not request.data:
            return None
        return json.loads(request.data.decode(), parse_float=decimal.Decimal)

    def get_arg(self, attr, default=None):
        """Get the attr from querystring, form data or json"""
        # This is not working on all versions.
        #if request.is_json:
        if self.get_json():
            return self.get_json().get(attr, None)

        return request.form.get(attr, request.args.get(attr, default))

    @classmethod
    def ensure_printer(cls, retries=20):
        assert _printer_lock.locked()

        store = api.get_default_store()
        device = DeviceSettings.get_by_station_and_type(store, get_current_station(store),
                                                        DeviceSettings.NON_FISCAL_PRINTER_DEVICE)
        if not device:
            # If we have no printer configured, there's nothing to ensure
            return

        # There is no need to lock the printer here, since it should already be locked by the
        # calling site of this method.
        # Test the printer to see if its working properly.
        printer = None
        try:
            printer = api.device_manager.printer
            return printer.is_drawer_open()
        except (SerialException, InvalidReplyException):
            if printer:
                printer._port.close()
            api.device_manager._printer = None
            for i in range(retries):
                log.info('Printer check failed. Reopening')
                try:
                    printer = api.device_manager.printer
                    printer.is_drawer_open()
                    break
                except SerialException:
                    gevent.sleep(1)
            else:
                # Reopening printer failed. re-raise the original exception
                raise

            # Invalidate the printer in the plugins so that it re-opens it
            manager = get_plugin_manager()

            # nfce does not need to reset the printer since it does not cache it.
            sat = get_plugin(manager, 'sat')
            if sat and sat.ui:
                sat.ui.printer = None

            nonfiscal = get_plugin(manager, 'nonfiscal')
            if nonfiscal and nonfiscal.ui:
                nonfiscal.ui.printer = printer

            return printer.is_drawer_open()


class DataResource(_BaseResource):
    """All the data the POS needs RESTful resource."""

    routes = ['/data']
    method_decorators = [_login_required, _store_provider]

    # All the tables get_data uses (directly or indirectly)
    watch_tables = ['sellable', 'product', 'storable', 'product_stock_item', 'branch_station',
                    'branch', 'login_user', 'sellable_category', 'client_category_price',
                    'payment_method', 'credit_provider']

    # Disabled for now while testing gevent instead of threads
    #@worker
    def _postgres_listen():
        store = api.new_store()
        conn = store._connection._raw_connection
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = store._connection.build_raw_cursor()
        cursor.execute("LISTEN update_te;")

        message = False
        while True:
            if select.select([conn], [], [], 5) != ([], [], []):
                conn.poll()
                while conn.notifies:
                    notify = conn.notifies.pop(0)
                    te_id, table = notify.payload.split(',')
                    # Update the data the client has when one of those changes
                    message = message or table in DataResource.watch_tables

            if message:
                EventStream.put({
                    'type': 'SERVER_UPDATE_DATA',
                    'data': DataResource.get_data(store)
                })
                message = False

    @classmethod
    def _get_categories(cls, store):
        categories_root = []
        aux = {}
        branch = api.get_current_branch(store)

        # SellableCategory and Sellable/Product data
        # FIXME: Remove categories that have no products inside them
        for c in store.find(SellableCategory):
            if c.category_id is None:
                parent_list = categories_root
            else:
                parent_list = aux.setdefault(
                    c.category_id, {}).setdefault('children', [])

            c_dict = aux.setdefault(c.id, {})
            parent_list.append(c_dict)

            # Set/Update the data
            c_dict.update({
                'id': c.id,
                'description': c.description,
            })
            c_dict.setdefault('children', [])
            products_list = c_dict.setdefault('products', [])

            tables = [Sellable, LeftJoin(Product, Product.id == Sellable.id)]

            if branch.person.company.cnpj.startswith('11.950.487'):
                # For now, only display products that have a fiscal configuration for the
                # current branch. We should find a better way to ensure this in the future
                tables.append(
                    Join(ProductBranchOverride,
                         And(ProductBranchOverride.product_id == Product.id,
                             ProductBranchOverride.branch_id == branch.id,
                             Ne(ProductBranchOverride.icms_template_id, None))))

            sellables = store.using(*tables).find(
                Sellable, category=c, status='available').order_by('height', 'description')
            for s in sellables:
                ccp = store.find(ClientCategoryPrice, sellable_id=s.id)
                ccp_dict = {}
                for item in ccp:
                    ccp_dict[item.category_id] = str(item.price)

                products_list.append({
                    'id': s.id,
                    'description': s.description,
                    'price': str(s.price),
                    'order': str(s.product.height),
                    'category_prices': ccp_dict,
                    'color': s.product.part_number,
                    'availability': (
                        s.product and s.product.storable and
                        {
                            si.branch.id: str(si.quantity)
                            for si in s.product.storable.get_stock_items()
                        }
                    )
                })

            aux[c.id] = c_dict
        return categories_root

    @classmethod
    def _get_payment_methods(self, store):
        # PaymentMethod data
        payment_methods = []
        for pm in PaymentMethod.get_active_methods(store):
            if not pm.selectable():
                continue

            data = {'name': pm.method_name,
                    'max_installments': pm.max_installments}
            if pm.method_name == 'card':
                # FIXME: Add voucher
                data['card_types'] = [CreditCardData.TYPE_CREDIT,
                                      CreditCardData.TYPE_DEBIT]

            payment_methods.append(data)

        return payment_methods

    @classmethod
    def _get_card_providers(self, store):
        providers = []
        for i in CreditProvider.get_card_providers(store):
            providers.append({'short_name': i.short_name, 'provider_id': i.provider_id})

        return providers

    @classmethod
    def get_data(cls, store):
        """Returns all data the POS needs to run

        This includes:

        - Which branch and statoin he is operating for
        - Current loged in user
        - What categories it has
            - What sellables those categories have
                - The stock amount for each sellable (if it controls stock)
        """
        station = get_current_station(store)
        user = api.get_current_user(store)
        staff_category = store.find(ClientCategory, ClientCategory.name == 'Staff').one()
        branch = station.branch
        config = get_config()
        can_send_sms = config.get("Twilio", "sid") is not None

        try:
            sat_status = check_sat()
        except LockFailedException:
            sat_status = True

        try:
            pinpad_status = check_pinpad()
        except LockFailedException:
            pinpad_status = True

        # Current branch data
        retval = dict(
            branch=branch.id,
            branch_station=station.name,
            branch_object=dict(
                id=branch.id,
                name=branch.name,
                acronym=branch.acronym,
            ),
            station=dict(
                id=station.id,
                code=station.code,
                name=station.name,
            ),
            user_id=user and user.id,
            user=user and user.username,
            user_object=user and dict(
                id=user.id,
                name=user.username,
                profile_id=user.profile_id,
            ),
            categories=cls._get_categories(store),
            payment_methods=cls._get_payment_methods(store),
            providers=cls._get_card_providers(store),
            staff_id=staff_category.id if staff_category else None,
            can_send_sms=can_send_sms,
            # Device statuses
            sat_status=sat_status,
            pinpad_status=pinpad_status,
            printer_status=None if DrawerResource.check_drawer() is None else True,
        )

        return retval

    def get(self, store):
        return self.get_data(store)


class DrawerResource(_BaseResource):
    """Drawer RESTful resource."""

    routes = ['/drawer']
    method_decorators = [_login_required]

    @lock_printer
    def check_drawer():
        try:
            return DrawerResource.ensure_printer(retries=1)
        except (SerialException, InvalidReplyException):
            return None

    @classmethod
    @worker
    def check_drawer_loop():
        # default value of is_open
        is_open = ''

        # Check every second if it is opened.
        # Alert only if changes.
        while True:
            new_is_open = DrawerResource.check_drawer()

            if is_open != new_is_open:
                message = {
                    True: 'DRAWER_ALERT_OPEN',
                    False: 'DRAWER_ALERT_CLOSE',
                    None: 'DRAWER_ALERT_ERROR',
                }
                EventStream.put({
                    'type': message[new_is_open],
                })
                status_printer = None if new_is_open is None else True
                EventStream.put({
                    'type': 'DEVICE_STATUS_CHANGED',
                    'device': 'printer',
                    'status': status_printer,
                })
                is_open = new_is_open

            gevent.sleep(1)

    @lock_printer
    def get(self):
        """Get the current status of the drawer"""
        return self.ensure_printer()

    @lock_printer
    def post(self):
        """Send a signal to open the drawer"""
        if not api.device_manager.printer:
            raise UnhandledMisconfiguration('Printer not configured in this station')

        api.device_manager.printer.open_drawer()
        return 'success', 200


class PingResource(_BaseResource):
    """Ping RESTful resource."""

    routes = ['/ping']

    def get(self):
        return 'pong from stoqserver'


def format_cpf(document):
    return '%s.%s.%s-%s' % (document[0:3], document[3:6], document[6:9],
                            document[9:11])


def format_cnpj(document):
    return '%s.%s.%s/%s-%s' % (document[0:2], document[2:5], document[5:8],
                               document[8:12], document[12:])


def format_document(document):
    if len(document) == 11:
        return format_cpf(document)
    else:
        return format_cnpj(document)


class TillResource(_BaseResource):
    """Till RESTful resource."""
    routes = ['/till']
    method_decorators = [_login_required]

    def _open_till(self, store, initial_cash_amount=0):
        station = get_current_station(store)
        last_till = Till.get_last(store)
        if not last_till or last_till.status != Till.STATUS_OPEN:
            # Create till and open
            till = Till(store=store, station=station)
            till.open_till()
            till.initial_cash_amount = decimal.Decimal(initial_cash_amount)
        else:
            # Error, till already opened
            assert False

    def _close_till(self, store, till_summaries):
        self.ensure_printer()
        # Here till object must exist
        till = Till.get_last(store)

        # Create TillSummaries
        till.get_day_summary()

        # Find TillSummary and store the user_value
        for till_summary in till_summaries:
            method = PaymentMethod.get_by_name(store, till_summary['method'])

            if till_summary['provider']:
                provider = store.find(CreditProvider, short_name=till_summary['provider']).one()
                summary = TillSummary.get_or_create(store, till=till, method=method.id,
                                                    provider=provider.id,
                                                    card_type=till_summary['card_type'])
            # Money method has no card_data or provider
            else:
                summary = TillSummary.get_or_create(store, till=till, method=method.id)

            summary.user_value = decimal.Decimal(till_summary['user_value'])

        balance = till.get_balance()
        if balance:
            till.add_debit_entry(balance, _('Blind till closing'))
        till.close_till()

    def _add_credit_or_debit_entry(self, store, data):
        # Here till object must exist
        till = Till.get_last(store)
        user = api.get_current_user(store)

        # FIXME: Check balance when removing to prevent negative till.
        if data['operation'] == 'debit_entry':
            reason = _('The user %s removed cash from till') % user.username
            till.add_debit_entry(decimal.Decimal(data['entry_value']), reason)
        elif data['operation'] == 'credit_entry':
            reason = _('The user %s supplied cash to the till') % user.username
            till.add_credit_entry(decimal.Decimal(data['entry_value']), reason)

    def _get_till_summary(self, store, till):
        payment_data = []
        for summary in till.get_day_summary():
            payment_data.append({
                'method': summary.method.method_name,
                'provider': summary.provider.short_name if summary.provider else None,
                'card_type': summary.card_type,
                'system_value': str(summary.system_value),
            })

        # XXX: We shouldn't create TIllSummaries since we are not closing the Till,
        # so we must rollback.
        store.rollback(close=False)

        return payment_data

    @lock_printer
    def post(self):
        data = self.get_json()
        with api.new_store() as store:
            # Provide responsible
            if data['operation'] == 'open_till':
                self._open_till(store, data['initial_cash_amount'])
            elif data['operation'] == 'close_till':
                self._close_till(store, data['till_summaries'])
            elif data['operation'] in ['debit_entry', 'credit_entry']:
                self._add_credit_or_debit_entry(store, data)

        return 200

    def get(self):
        # Retrieve Till data
        with api.new_store() as store:
            till = Till.get_last(store)

            if not till:
                return None

            till_data = {
                'status': till.status,
                'opening_date': till.opening_date.strftime('%Y-%m-%d'),
                'closing_date': (till.closing_date.strftime('%Y-%m-%d') if
                                 till.closing_date else None),
                'initial_cash_amount': str(till.initial_cash_amount),
                'final_cash_amount': str(till.final_cash_amount),
                # Get payments data that will be used on 'close_till' action.
                'entry_types': till.status == 'open' and self._get_till_summary(store, till) or [],
            }

        return till_data


class ClientResource(_BaseResource):
    """Client RESTful resource."""
    routes = ['/client']

    def _dump_client(self, client):
        person = client.person
        birthdate = person.individual.birth_date if person.individual else None

        saleviews = person.client.get_client_sales().order_by(Desc('confirm_date'))
        last_items = {}
        for saleview in saleviews:
            for item in saleview.sale.get_items():
                last_items[item.sellable_id] = item.sellable.description
                # Just the last 3 products the client bought
                if len(last_items) == 3:
                    break

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

        # Plugins that listen to this signal will return extra fields
        # to be added to the response
        responses = signal('CheckRewardsPermissionsEvent').send(doc)
        for response in responses:
            data.update(response[1])

        return data

    def _get_by_doc(self, store, data, doc):
        # Extra precaution in case we ever send the cpf already formatted
        document = format_cpf(raw_document(doc))

        person = Person.get_by_document(store, document)
        if person and person.client:
            data = self._dump_client(person.client)

        return data

    def _get_by_category(self, store, category_name):
        tables = [Client,
                  Join(ClientCategory, Client.category_id == ClientCategory.id)]
        clients = store.using(*tables).find(Client, ClientCategory.name == category_name)
        retval = []
        for client in clients:
            retval.append(self._dump_client(client))
        return retval

    def post(self):
        data = self.get_json()

        with api.new_store() as store:
            if data.get('doc'):
                return self._get_by_doc(store, data, data['doc'])
            elif data.get('category_name'):
                return self._get_by_category(store, data['category_name'])
        return data


class ExternalClientResource(_BaseResource):
    """Information about a client from external services, such as Passbook"""
    routes = ['/extra_client_info/<doc>']

    def get(self, doc):
        # Extra precaution in case we ever send the cpf already formatted
        doc = format_cpf(raw_document(doc))
        responses = signal('GetClientInfoEvent').send(doc)

        data = dict()
        for response in responses:
            data.update(response[1])
        return data


class LoginResource(_BaseResource):
    """Login RESTful resource."""

    routes = ['/login']

    def post(self):
        username = self.get_arg('user')
        pw_hash = self.get_arg('pw_hash')

        with api.new_store() as store:
            try:
                # FIXME: Respect the branch the user is in.
                user = LoginUser.authenticate(store, username, pw_hash, current_branch=None)
                provide_utility(ICurrentUser, user, replace=True)
            except LoginError as e:
                abort(403, str(e))

        return user.id


class AuthResource(_BaseResource):
    """Authenticate a user agasint the database.

    This will not replace the ICurrentUser. It will just validate if a login/password is valid.
    """

    routes = ['/auth']
    method_decorators = [_login_required, _store_provider]

    def post(self, store):
        username = self.get_arg('user')
        pw_hash = self.get_arg('pw_hash')
        permission = self.get_arg('permission')

        try:
            # FIXME: Respect the branch the user is in.
            user = LoginUser.authenticate(store, username, pw_hash, current_branch=None)
        except LoginError as e:
            return make_response(str(e), 403)

        if user.profile.check_app_permission(permission):
            return True
        return make_response(_('User does not have permission'), 403)


class EventStream(_BaseResource):
    """A stream of events from this server to the application.

    Callsites can use EventStream.put(event) to send a message from the server to the client
    asynchronously.

    Note that there should be only one client connected at a time. If more than one are connected,
    all of them will receive all events
    """
    _streams = []
    has_stream = Event()

    routes = ['/stream']

    @classmethod
    def put(cls, data):
        # Wait until we have at least one stream
        cls.has_stream.wait()

        # Put event in all streams
        for stream in cls._streams:
            stream.put(data)

    def _loop(self, stream):
        while True:
            data = stream.get()
            yield "data: " + json.dumps(data) + "\n\n"

    def get(self):
        stream = Queue()
        self._streams.append(stream)
        self.has_stream.set()

        # If we dont put one event, the event stream does not seem to get stabilished in the browser
        stream.put(json.dumps({}))

        # This is the best time to check if there are pending transactions, since the frontend just
        # stabilished a connection with the backend (thats us).
        has_canceled = TefCheckPendingEvent.send()
        if has_canceled and has_canceled[0][1]:
            EventStream.put({'type': 'TEF_WARNING_MESSAGE',
                             'message': ('Última transação TEF não foi efetuada.'
                                         ' Favor reter o Cupom.')})
            EventStream.put({'type': 'CLEAR_SALE'})
        return Response(self._loop(stream), mimetype="text/event-stream")


class TefResource(_BaseResource):
    routes = ['/tef/<signal_name>']
    method_decorators = [_login_required]

    waiting_reply = Event()
    reply = Queue()

    @lock_printer
    def _print_callback(self, lib, holder, merchant):
        printer = api.device_manager.printer
        if not printer:
            return

        # TODO: Add paramter to control if this will be printed or not
        if merchant:
            printer.print_line(merchant)
            printer.cut_paper()
        if holder:
            printer.print_line(holder)
            printer.cut_paper()

    def _message_callback(self, lib, message, can_abort=False):
        EventStream.put({
            'type': 'TEF_DISPLAY_MESSAGE',
            'message': message,
            'can_abort': can_abort,
        })

        # tef library (ntk/sitef) has some blocking calls (specially pinpad comunication).
        # Before returning, we need to briefly hint gevent to let the EventStream co-rotine run,
        # so that the message above can be sent to the frontend.
        gevent.sleep(0.001)

    def _question_callback(self, lib, question):
        EventStream.put({
            'type': 'TEF_ASK_QUESTION',
            'data': question,
        })

        log.info('Waiting tef reply')
        self.waiting_reply.set()
        reply = self.reply.get()
        log.info('Got tef reply: %s', reply)
        self.waiting_reply.clear()
        if not reply:
            # Returning false will make the transaction be canceled
            return False

        return reply

    @lock_pinpad(block=True)
    def post(self, signal_name):
        try:
            with _printer_lock:
                self.ensure_printer()
        except Exception:
            EventStream.put({
                'type': 'TEF_OPERATION_FINISHED',
                'success': False,
                'message': 'Erro comunicando com a impressora',
            })
            return

        signal('TefMessageEvent').connect(self._message_callback)
        signal('TefQuestionEvent').connect(self._question_callback)
        signal('TefPrintEvent').connect(self._print_callback)

        operation_signal = signal(signal_name)
        # There should be just one plugin connected to this event.
        assert len(operation_signal.receivers) == 1, operation_signal

        data = self.get_json()
        # Remove origin from data, if present
        data.pop('origin', None)
        try:
            # This operation will be blocked here until its complete, but since we are running
            # each request using threads, the server will still be available to handle other
            # requests (specially when handling comunication with the user through the callbacks
            # above)
            log.info('send tef signal %s (%s)', signal_name, data)
            retval = operation_signal.send(**data)[0][1]
            message = retval['message']
        except Exception as e:
            retval = False
            log.info('Tef failed: %s', str(e))
            if len(e.args) == 2:
                message = e.args[1]
            else:
                message = 'Falha na operação'

        EventStream.put({
            'type': 'TEF_OPERATION_FINISHED',
            'success': retval,
            'message': message,
        })


class TefReplyResource(_BaseResource):
    routes = ['/tef/reply']
    method_decorators = [_login_required]

    def post(self):
        assert TefResource.waiting_reply.is_set()

        data = self.get_json()
        TefResource.reply.put(json.loads(data['value']))


class TefCancelCurrentOperation(_BaseResource):
    routes = ['/tef/abort']
    method_decorators = [_login_required]

    def post(self):
        signal('TefAbortOperationEvent').send()


class ImageResource(_BaseResource):
    """Image RESTful resource."""

    routes = ['/image/<id>']

    def get(self, id):
        is_main = bool(request.args.get('is_main', None))
        # FIXME: The images should store tags so they could be requested by that tag and
        # product_id. At the moment, we simply check if the image is main or not and
        # return the first one.
        with api.new_store() as store:
            image = store.find(Image, sellable_id=id, is_main=is_main).any()

            if image:
                return send_file(io.BytesIO(image.image), mimetype='image/png')
            else:
                response = make_response(base64.b64decode(TRANSPARENT_PIXEL))
                response.headers.set('Content-Type', 'image/jpeg')
                return response


class SaleResourceMixin:
    """Mixin class that provides common methods for sale/advance_payment

    This includes:

        - Payment creation
        - Client verification
        - Sale/Advance already saved checking
    """

    PROVIDER_MAP = {
        'ELO CREDITO': 'ELO',
        'TICKET RESTA': 'TICKET REFEICAO',
        'VISA ELECTRO': 'VISA',
        'MAESTROCP': 'MASTER',
        'MASTERCARD D': 'MASTER',
        'MASTERCARD': 'MASTER',
    }

    def _check_already_saved(self, store, klass, obj_id):
        existing_sale = store.get(klass, obj_id)
        if existing_sale:
            log.info('Sale already saved: %s' % obj_id)
            log.info('send CheckCouponTransmittedEvent signal')
            is_coupon_transmitted = signal('CheckCouponTransmittedEvent').send(existing_sale)[0][1]
            if is_coupon_transmitted:
                return self._handle_coupon_printing_fail(existing_sale)
            raise AssertionError(_('Sale already saved'))

    def _get_client_and_document(self, store, data):
        client_id = data.get('client_id')
        document = raw_document(data.get('client_document', '') or '')

        if document:
            document = format_document(document)

        if client_id:
            client = store.get(Client, client_id)
        elif document:
            person = Person.get_by_document(store, document)
            client = person and person.client
        else:
            client = None

        return client, document

    def _handle_coupon_printing_fail(self, obj):
        log.exception('Error printing coupon')
        # XXX: Rever string
        message = _("Sale {sale_identifier} confirmed but printing coupon failed")
        return {
            # XXX: This is not really an error, more of a partial success were the coupon
            # (sat/nfce) was emitted, but the printing of the coupon failed. The frontend should
            # present to the user the option to try again or send the coupom via sms/email
            'error_type': 'printing',
            'message': message.format(sale_identifier=obj.identifier),
            'sale_id': obj.id
        }, 201

    def _get_card_device(self, store, name):
        device = store.find(CardPaymentDevice, description=name).any()
        if not device:
            device = CardPaymentDevice(store=store, description=name)
        return device

    def _get_provider(self, store, name):
        name = name.strip()
        name = self.PROVIDER_MAP.get(name, name)
        provider = store.find(CreditProvider, provider_id=name).one()
        if not provider:
            provider = CreditProvider(store=store, short_name=name, provider_id=name)
        return provider

    def _create_payments(self, store, group, branch, sale_total, payment_data):
        money_payment = None
        payments_total = 0
        for p in payment_data:
            method_name = p['method']
            tef_data = p.get('tef_data', {})
            if method_name == 'tef':
                p['provider'] = tef_data['card_name']
                method_name = 'card'

            method = PaymentMethod.get_by_name(store, method_name)
            installments = p.get('installments', 1) or 1

            due_dates = list(create_date_interval(
                INTERVALTYPE_MONTH,
                interval=1,
                start_date=localnow(),
                count=installments))

            payment_value = currency(p['value'])
            payments_total += payment_value

            p_list = method.create_payments(
                Payment.TYPE_IN, group, branch,
                payment_value, due_dates)

            if method.method_name == 'money':
                # FIXME Frontend should not allow more than one money payment. this can be changed
                # once https://gitlab.com/stoqtech/private/bdil/issues/75 is fixed?
                if not money_payment or payment_value > money_payment.value:
                    money_payment = p_list[0]
            elif method.method_name == 'card':
                for payment in p_list:
                    card_data = method.operation.get_card_data_by_payment(payment)

                    card_type = p['card_type']
                    if card_type == 'passbook':
                        card_type = 'credit'
                    provider = self._get_provider(store, p['provider'])

                    if tef_data:
                        card_data.nsu = tef_data['nsu']
                        card_data.auth = tef_data['auth']
                        authorizer = tef_data.get('authorizer', 'TEF')
                        device = self._get_card_device(store, authorizer)
                    else:
                        device = self._get_card_device(store, 'POS')

                    card_data.update_card_data(device, provider, card_type, installments)
                    card_data.te.metadata = tef_data

        # If payments total exceed sale total, we must adjust money payment so that the change is
        # correctly calculated..
        if payments_total > sale_total and money_payment:
            money_payment.value -= (payments_total - sale_total)
            assert money_payment.value >= 0, money_payment.value


class SaleResource(_BaseResource, SaleResourceMixin):
    """Sellable category RESTful resource."""

    routes = ['/sale', '/sale/<string:sale_id>']
    method_decorators = [_login_required, _store_provider]

    def _handle_nfe_coupon_rejected(self, sale, reason):
        log.exception('NFC-e sale rejected')
        message = _("NFC-e of sale {sale_identifier} was rejected")
        return {
            'error_type': 'rejection',
            'message': message.format(sale_identifier=sale.identifier),
            'sale_id': sale.id,
            'reason': reason
        }, 201

    def _encode_payments(self, payments):
        return [{'method': p.method.method_name,
                 'value': str(p.value)} for p in payments]

    def _encode_items(self, items):
        return [{'quantity': str(i.quantity),
                 'price': str(i.price),
                 'description': i.get_description()} for i in items]

    @lock_printer
    @lock_sat(block=True)
    def post(self, store):
        # FIXME: Check branch state and force fail if no override for that product is present.
        data = self.get_json()
        products = data['products']
        client_category_id = data.get('price_table')

        client, document = self._get_client_and_document(store, data)

        sale_id = data.get('sale_id')
        self._check_already_saved(store, Sale, sale_id)

        # Print the receipts and confirm the transaction before anything else. If the sale fails
        # (either by a sat device error or a nfce conectivity/rejection issue), the tef receipts
        # will still be printed/confirmed and the user can finish the sale or the client.
        TefPrintReceiptsEvent.send(sale_id)

        # Create the sale
        branch = api.get_current_branch(store)
        group = PaymentGroup(store=store)
        user = api.get_current_user(store)
        sale = Sale(
            store=store,
            id=sale_id,
            branch=branch,
            salesperson=user.person.sales_person,
            client=client,
            client_category_id=client_category_id,
            group=group,
            open_date=localnow(),
            coupon_id=None,
        )

        # Add products
        for p in products:
            sellable = store.get(Sellable, p['id'])
            item = sale.add_sellable(sellable, price=currency(p['price']),
                                     quantity=decimal.Decimal(p['quantity']))
            # XXX: bdil has requested that when there is a special discount, the discount does
            # not appear on the coupon. Instead, the item wil be sold using the discount price
            # as the base price. Maybe this should be a parameter somewhere
            item.base_price = item.price

        # Add payments
        self._create_payments(store, group, branch, sale.get_total_sale_amount(), data['payments'])

        # Confirm the sale
        group.confirm()
        sale.order()

        till = Till.get_last(store)
        sale.confirm(till)

        # Fiscal plugins will connect to this event and "do their job"
        # It's their responsibility to raise an exception in case of any error
        try:
            SaleConfirmedRemoteEvent.emit(sale, document)
        except (NfePrinterException, SatPrinterException):
            return self._handle_coupon_printing_fail(sale)
        except NfeRejectedException as e:
            return self._handle_nfe_coupon_rejected(sale, e.reason)

        return True

    def get(self, store, sale_id):
        sale = store.get(Sale, sale_id)
        if not sale:
            abort(404)
        transmitted = signal('CheckCouponTransmittedEvent').send(sale)
        is_coupon_transmitted = transmitted[0][1] if transmitted else False
        return {
            'id': sale.id,
            'confirm_date': str(sale.confirm_date),
            'items': self._encode_items(sale.get_items()),
            'total': str(sale.total_amount),
            'payments': self._encode_payments(sale.payments),
            'client': sale.get_client_name(),
            'status': sale.status_str,
            'transmitted': is_coupon_transmitted,
        }, 200


class AdvancePaymentResource(_BaseResource, SaleResourceMixin):

    routes = ['/advance_payment']
    method_decorators = [_login_required, _store_provider]

    @lock_printer
    def post(self, store):
        # We need to delay this import since the plugin will only be in the path after stoqlib
        # initialization
        from stoqpassbook.domain import AdvancePayment
        data = self.get_json()
        client, document = self._get_client_and_document(store, data)

        advance_id = data.get('sale_id')
        self._check_already_saved(store, AdvancePayment, advance_id)

        # Print the receipts and confirm the transaction before anything else. If the sale fails
        # (either by a sat device error or a nfce conectivity/rejection issue), the tef receipts
        # will still be printed/confirmed and the user can finish the sale or the client.
        TefPrintReceiptsEvent.send(advance_id)

        branch = api.get_current_branch(store)
        group = PaymentGroup(store=store)
        user = api.get_current_user(store)
        advance = AdvancePayment(
            id=advance_id,
            store=store,
            branch=branch,
            group=group,
            user=user)

        # Add payments
        self._create_payments(store, group, branch, advance.total, data['payments'])
        till = Till.get_last(store)
        advance.confirm(till)

        #try:
        #    PrintAdvancePaymentReceipt.send(advance)
        #except (XXX):
        #    return self._handle_coupon_printing_fail(sale)

        return True


class PrintCouponResource(_BaseResource):
    """Image RESTful resource."""

    routes = ['/sale/<sale_id>/print_coupon']
    method_decorators = [_login_required, _store_provider]

    @lock_printer
    def get(self, store, sale_id):
        self.ensure_printer()

        sale = store.get(Sale, sale_id)
        signal('PrintCouponCopyEvent').send(sale)


class SmsResource(_BaseResource):
    """SMS RESTful resource."""
    routes = ['/sale/<sale_id>/send_coupon_sms']
    method_decorators = [_login_required, _store_provider]

    def _send_sms(self, to, message):
        config = get_config()
        sid = config.get('Twilio', 'sid')
        secret = config.get('Twilio', 'secret')
        from_phone_number = config.get('Twilio', 'from')

        sms_data = {"From": from_phone_number, "To": to, "Body": message}

        r = requests.post('https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json' % sid,
                          data=sms_data, auth=(sid, secret))
        return r.text

    def post(self, store, sale_id):
        GetCouponSmsTextEvent = signal('GetCouponSmsTextEvent')
        assert len(GetCouponSmsTextEvent.receivers) == 1

        sale = store.get(Sale, sale_id)
        message = GetCouponSmsTextEvent.send(sale)[0][1]
        to = '+55' + self.get_json()['phone_number']
        return self._send_sms(to, message)


def bootstrap_app():
    app = Flask(__name__)

    # Indexing some session data by the USER_HASH will help to avoid maintaining
    # sessions between two different databases. This could lead to some errors in
    # the POS in which the user making the sale does not exist.
    app.config['SECRET_KEY'] = _get_user_hash()
    app.config['PROPAGATE_EXCEPTIONS'] = True
    flask_api = Api(app)

    for cls in _BaseResource.__subclasses__():
        flask_api.add_resource(cls, *cls.routes)

    signal('StoqTouchStartupEvent').send()

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        traceback_info = "\n".join(traceback.format_tb(e.__traceback__))
        traceback_hash = hashlib.sha1(traceback_info.encode('utf-8')).hexdigest()[:8]
        traceback_exception = traceback.format_exception_only(type(e), e)[-1]
        timestamp = localnow().strftime('%Y%m%d-%H%M%S')

        log.exception('Unhandled Exception: {timestamp} {error} {traceback_hash}'.format(
            timestamp=timestamp, error=e, traceback_hash=traceback_hash))

        main.sentry_report(type(e), e, e.__traceback__, traceback_hash=traceback_hash)

        return Response(json.dumps({'error': _('bad request!'), 'timestamp': timestamp,
                                    'exception': traceback_exception,
                                    'traceback_hash': traceback_hash}),
                        500, mimetype='application/json')

    return app


def run_flaskserver(port, debug=False):
    from stoqlib.lib.environment import configure_locale
    # Force pt_BR for now.
    configure_locale('pt_BR')

    # Check drawer in a separated thread
    for function in WORKERS:
        gevent.spawn(function)

    try:
        from stoqserver.lib import stacktracer
        stacktracer.start_trace("/tmp/trace-stoqserver-flask.txt", interval=5, auto=True)
    except ImportError:
        pass

    app = bootstrap_app()
    app.debug = debug
    if not is_developer_mode():
        main.raven_client = Sentry(app, dsn=main.SENTRY_URL, client=main.raven_client)

    @app.after_request
    def after_request(response):
        # Add all the CORS headers the POS needs to have its ajax requests
        # accepted by the browser
        origin = request.headers.get('origin')
        if not origin:
            origin = request.args.get('origin', request.form.get('origin', '*'))
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'stoq-session, stoq-user, Content-Type'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response

    log.info('Starting wsgi server (has_sat=%s, has_nfe=%s)', has_sat, has_nfe)
    http_server = WSGIServer(('127.0.0.1', port), app, spawn=gevent.spawn_raw, log=log,
                             error_log=log)
    http_server.serve_forever()


@lock_sat(block=False)
def check_sat():
    if len(CheckSatStatusEvent.receivers) == 0:
        # No SAT was found, what means there is no need to warn front-end there is a missing
        # or broken SAT
        return True

    event_reply = CheckSatStatusEvent.send()
    return event_reply and event_reply[0][1]


@worker
def check_sat_loop():
    if len(CheckSatStatusEvent.receivers) == 0:
        return

    sat_ok = -1

    while True:
        try:
            new_sat_ok = check_sat()
        except LockFailedException:
            # Keep previous state.
            new_sat_ok = sat_ok

        if sat_ok != new_sat_ok:
            EventStream.put({
                'type': 'DEVICE_STATUS_CHANGED',
                'device': 'sat',
                'status': new_sat_ok,
            })
            sat_ok = new_sat_ok

        gevent.sleep(60 * 5)


@lock_pinpad(block=False)
def check_pinpad():
    event_reply = CheckPinpadStatusEvent.send()
    return event_reply and event_reply[0][1]


@worker
def check_pinpad_loop():
    pinpad_ok = -1

    while True:
        try:
            new_pinpad_ok = check_pinpad()
        except LockFailedException:
            # Keep previous state.
            new_pinpad_ok = pinpad_ok

        if pinpad_ok != new_pinpad_ok:
            EventStream.put({
                'type': 'DEVICE_STATUS_CHANGED',
                'device': 'pinpad',
                'status': new_pinpad_ok,
            })
            pinpad_ok = new_pinpad_ok

        gevent.sleep(60)
