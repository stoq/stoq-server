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

import base64
import datetime
import decimal
import functools
import io
import logging
from decimal import Decimal
from typing import Dict, Optional

from blinker import signal, ANY as ANY_SENDER
import gevent
import requests

from stoqlib.lib.component import provide_utility
from flask import request, abort, send_file, make_response, jsonify

from stoqlib.api import api
from stoqlib.database.interfaces import ICurrentUser
from stoqlib.domain.events import SaleConfirmedRemoteEvent
from stoqlib.domain.image import Image
from stoqlib.domain.overrides import ProductBranchOverride, SellableBranchOverride
from stoqlib.domain.payment.group import PaymentGroup
from stoqlib.domain.payment.method import PaymentMethod
from stoqlib.domain.payment.card import CreditCardData, CreditProvider, CardPaymentDevice
from stoqlib.domain.payment.payment import Payment
from stoqlib.domain.person import (LoginUser, Person, Client, ClientCategory, Company,
                                   Transporter)
from stoqlib.domain.product import Product, Storable, ProductStockItem
from stoqlib.domain.purchase import PurchaseOrder
from stoqlib.domain.sale import Sale, SaleContext, Context, Delivery
from stoqlib.domain.station import BranchStation
from stoqlib.domain.token import AccessToken
from stoqlib.domain.payment.renegotiation import PaymentRenegotiation
from stoqlib.domain.sellable import (Sellable, SellableCategory,
                                     ClientCategoryPrice)
from stoqlib.domain.till import Till, TillSummary
from stoqlib.exceptions import LoginError, TillError, ExternalOrderError
from stoqlib.lib.configparser import get_config
from stoqlib.lib.dateutils import INTERVALTYPE_MONTH, create_date_interval, localnow
from stoqlib.lib.defaults import quantize
from stoqlib.lib.formatters import raw_document, format_document, format_cpf
from stoqlib.lib.translation import dgettext
from stoqlib.lib.pluginmanager import get_plugin_manager
from storm.expr import LeftJoin, Join, And, Eq, Ne, Coalesce, Sum

from stoqserver.app import is_multiclient
from stoqserver.lib.baseresource import BaseResource
from stoqserver.lib.eventstream import EventStream, EventStreamBrokenException, STREAM_BROKEN
from .checks import check_drawer, check_pinpad, check_sat
from .constants import PROVIDER_MAP
from .lock import lock_pinpad, lock_printer, lock_sat, printer_lock, LockFailedException
from ..api.decorators import login_required, store_provider
from ..signals import (GenerateAdvancePaymentReceiptPictureEvent,
                       GenerateInvoicePictureEvent, GenerateTillClosingReceiptImageEvent,
                       GrantLoyaltyPointsEvent, PrintAdvancePaymentReceiptEvent,
                       PrintKitchenCouponEvent, FinishExternalOrderEvent,
                       SearchForPassbookUsersByDocumentEvent, StartPassbookSaleEvent,
                       TefPrintReceiptsEvent, StartExternalOrderEvent,
                       CancelExternalOrderEvent, GenerateExternalOrderReceiptImageEvent,
                       PrintExternalOrderEvent, ReadyToDeliverExternalOrderEvent,
                       PrintTillEntryCouponEvent)

from stoqserver.api.resources.b1food import (B1foodLoginResource, IncomeCenterResource)
from stoqserver.api.resources.branch import BranchResource
from stoqserver.api.resources.client import ClientResource
from stoqserver.api.resources.inventory import InventoryResource
from stoqserver.api.resources.invoice import NfePurchaseResource
from stoqserver.api.resources.imported_nfe import ImportedNfeResource
from stoqserver.api.resources.sellable import SellableResource
from stoqserver.api.resources.webhook import WebhookEvent

# This needs to be imported to workaround a storm limitation
PurchaseOrder, PaymentRenegotiation

# Pyflakes
Dict

# Resources
B1foodLoginResource
IncomeCenterResource
BranchResource
ClientResource
ImportedNfeResource
InventoryResource
SellableResource
WebhookEvent
NfePurchaseResource

_ = functools.partial(dgettext, 'stoqserver')
PDV_VERSION = None

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

log = logging.getLogger(__name__)


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
            obj = self.store.find(SellableBranchOverride, sellable=self, branch=branch).one()
        elif klass == Product:
            obj = self.store.find(ProductBranchOverride, product=self, branch=branch).one()

        original = getattr(self, '__' + name)
        return getattr(obj, name, original) or original

    def _set(self, value):
        assert False, self

    return property(_get, _set)


# Monkey patch sellable overrides until we properly implement this in stoq
# FIXME: https://gitlab.com/stoqtech/private/stoq-server/issues/45
Sellable.default_sale_cfop = override(Sellable.default_sale_cfop)


class UnhandledMisconfiguration(Exception):
    pass


class DataResource(BaseResource):
    """All the data the POS needs RESTful resource."""

    routes = ['/data']
    method_decorators = [login_required, store_provider]

    def _get_sellable_data(self, store, station):
        tables = [
            Sellable,
            Join(Product, Product.id == Sellable.id),
            LeftJoin(Storable, Product.id == Storable.id),
            LeftJoin(Image,
                     And(Sellable.id == Image.sellable_id, Eq(Image.is_main, True))),
            LeftJoin(SellableBranchOverride,
                     And(SellableBranchOverride.sellable_id == Sellable.id,
                         SellableBranchOverride.branch_id == station.branch.id)),
            LeftJoin(ProductStockItem,
                     And(ProductStockItem.storable_id == Sellable.id,
                         ProductStockItem.branch_id == station.branch.id))
        ]

        if api.sysparam.get_bool('REQUIRE_PRODUCT_BRANCH_OVERRIDE'):
            # For now, only display products that have a fiscal configuration for the
            # current branch. We should find a better way to ensure this in the future
            tables.append(
                Join(ProductBranchOverride,
                     And(ProductBranchOverride.product_id == Product.id,
                         ProductBranchOverride.branch_id == station.branch.id,
                         Ne(ProductBranchOverride.icms_template_id, None))))

        query = Eq(Coalesce(SellableBranchOverride.status, Sellable.status), "available")
        if station.type:
            # FIXME: We should be carefull since some keywords might overlap and that might lead to
            # false positives (like a product that has a `smart-pos` keyword, but the station type
            # is `pos`)
            query = And(query, Sellable.keywords.like('%{}%'.format(station.type.name)))

        return store.using(*tables).find(
            (Sellable, Product, Storable, Image.id,
             SellableBranchOverride, Sum(ProductStockItem.quantity)), query).group_by(
            Sellable.id, Product.id, Storable.id, Image.id, SellableBranchOverride.id)

    def _dump_sellable(self, category_prices, sellable, branch, image_id, storable, sbo, psi_qty):
        requires_kitchen_production = sbo and sbo.requires_kitchen_production
        if requires_kitchen_production is None:
            requires_kitchen_production = sellable.requires_kitchen_production

        return {
            'id': sellable.id,
            'code': sellable.code,
            'barcode': sellable.barcode,
            'description': sellable.description,
            'short_description': sellable.short_description,
            'price': str(sellable.get_price(branch)),
            'order': str(sellable.product.height),  # TODO: There is a sort_order now in the domain
            'color': sellable.product.part_number,
            'category_prices': category_prices,
            'requires_kitchen_production': requires_kitchen_production,
            'has_image': image_id is not None,
            'availability': {branch.id: str(psi_qty)} if storable else None,
        }

    def _get_categories(self, store, station):
        # Pre-create sellable category prices to avoid multiple queries inside the sellable loop
        sellable_category_prices = {}
        for item in store.find(ClientCategoryPrice):
            cat_prices = sellable_category_prices.setdefault(item.sellable_id, {})
            cat_prices[item.category_id] = str(item.price)

        categories_dict = {}  # type: Dict[str, Dict]
        sellable_data = self._get_sellable_data(store, station)
        # Build list of products inside each category
        for (sellable, product, storable, image, sbo, psi_qty) in sellable_data:
            category_prices = sellable_category_prices.get(sellable.id, {})

            categories_dict.setdefault(sellable.category_id, {'children': [], 'products': []})

            categories_dict[sellable.category_id]['products'].append(
                self._dump_sellable(category_prices, sellable, station.branch,
                                    image, storable, sbo, psi_qty))

        # Build tree of categories
        for c in store.find(SellableCategory):
            cat_dict = categories_dict.setdefault(c.id, {'children': [], 'products': []})
            cat_dict.update({'id': c.id, 'description': c.description, 'order': c.sort_order})

            parent = categories_dict.setdefault(c.category_id, {'children': [], 'products': []})
            parent['children'].append(cat_dict)

        # Get any extra categories plugins might want to add
        responses = signal('GetAdvancePaymentCategoryEvent').send(station)
        for response in responses:
            if response[1]:
                categories_dict[None]['children'].append(response[1])

        # FIXME: Remove categories that have no products inside them
        return categories_dict.get(None, {}).get('children', [])  # None is the root category

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

    def _get_card_providers(self, store):
        providers = []
        for i in CreditProvider.get_card_providers(store):
            providers.append({'short_name': i.short_name, 'provider_id': i.provider_id})

        return providers

    def _get_parameters(self):
        params = [
            ('INCLUDE_CASH_FUND_ON_TILL_CLOSING', bool, None, False),
            ('NFCE_CAN_SEND_DIGITAL_INVOICE', bool, 'nfce', False),
            ('NFE_SEFAZ_TIMEOUT', int, 'nfce', 10),
            ('PASSBOOK_FIDELITY', str, 'passbook', None),
            ('AUTOMATIC_LOGOUT', int, None, 0),
            ('SCALE_BARCODE_FORMAT', int, None, 0),
        ]

        retval = {}
        active_plugins = get_plugin_manager().active_plugins_names
        for param_name, param_type, plugin_name, fallback_value in params:
            # We fetch the param value if the param comes from stoq (plugin_name is None)
            # or the informed plugin is active
            if not plugin_name or plugin_name in active_plugins:
                retval[param_name] = api.sysparam.get(param_name, param_type)
            else:
                retval[param_name] = fallback_value
        return retval

    def _can_use_cnpj(self, store, branch, plugins):
        address = branch.person.get_main_address()
        state = address.city_location.state
        if state == 'SP' and 'nfce' in plugins:
            return False
        return True

    def _get_sale_contexts(self, store, branch):
        sale_context_list = []
        for context in store.find(Context, branch=branch):
            sale_context_list.append({
                'id': context.id,
                'name': context.name,
                'start_time': context.start_time,
                'end_time': context.end_time,
            })
        return sale_context_list

    def _get_payment_providers(self, config):
        def _get_setting(config, name):
            value = config.get('PaymentProviders', name)
            if not value:
                return None
            return [i.strip() for i in value.split(',')]

        return dict(
            credit=_get_setting(config, 'credit'),
            debit=_get_setting(config, 'debit'),
            voucher=_get_setting(config, 'voucher'),
            delivery=_get_setting(config, 'delivery'),
            digital_wallet=_get_setting(config, 'digital_wallet')
        )

    def _get_scrollable_items(self, config):
        payments_list = config.get("Payments", "credit_providers") or ''
        return [i.strip() for i in payments_list.split(',')]

    def get_data(self, store):
        """Returns all data the POS needs to run

        This includes:

        - Which branch and station he is operating for
        - Current loged in user
        - What categories it has
            - What sellables those categories have
                - The stock amount for each sellable (if it controls stock)
        """
        station = self.get_current_station(store)
        user = self.get_current_user(store)
        staff_category = store.find(ClientCategory, ClientCategory.name == 'Staff').one()
        branch = station.branch
        config = get_config()
        can_send_sms = config.get("Twilio", "sid") is not None
        iti_discount = config.get("Discounts", "iti") == '1'
        iti_discount_percentage = config.get("Discounts", "iti_discount_percentage") or '0.3'
        iti_discount_max_value = config.get("Discounts", "iti_discount_max_value") or '10'
        hotjar_id = config.get("Hotjar", "id")
        plugins = get_plugin_manager().active_plugins_names
        responses = signal('GetSettingsForFrontendEvent').send(station)
        enable_cash_operations = config.get("Till", "enable_cash_operations") == 'true'
        discount_percentage = config.get("Discounts", "discount_percentage") or '0'

        settings = {}
        for response in responses:
            settings.update(response[1])

        sat_status = pinpad_status = printer_status = True
        if not is_multiclient():
            try:
                sat_status = check_sat()
            except LockFailedException:
                sat_status = True

            try:
                pinpad_status = check_pinpad()
            except LockFailedException:
                pinpad_status = True

            printer_status = None if check_drawer(store) is None else True

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
                type=station.type.name if station.type else None,
                has_kps_enabled=station.has_kps_enabled,
            ),
            sale_context=self._get_sale_contexts(store, branch),
            user_id=user and user.id,
            user=user and user.username,
            user_object=user and dict(
                id=user.id,
                name=user.username,
                person_name=user.person.name,
                profile_id=user.profile_id,
            ),
            parameters=self._get_parameters(),
            categories=self._get_categories(store, station),
            payment_methods=self._get_payment_methods(store),
            providers=self._get_card_providers(store),
            payment_providers=self._get_payment_providers(config),
            # Keep this for a while for backward compatibility
            scrollable_list=self._get_scrollable_items(config),
            staff_id=staff_category.id if staff_category else None,
            can_send_sms=can_send_sms,
            can_use_cnpj=self._can_use_cnpj(store, branch, plugins),
            iti_discount=iti_discount,
            iti_discount_percentage=iti_discount_percentage,
            iti_discount_max_value=iti_discount_max_value,
            hotjar_id=hotjar_id,
            plugins=plugins,
            settings=settings,
            enable_cash_operations=enable_cash_operations,
            discount_percentage=discount_percentage,
            # Device statuses
            sat_status=sat_status,
            pinpad_status=pinpad_status,
            printer_status=printer_status,
        )

        return retval

    def get(self, store):
        return self.get_data(store)


class DrawerResource(BaseResource):
    """Drawer RESTful resource."""

    routes = ['/drawer']
    method_decorators = [login_required, store_provider]

    @lock_printer
    def get(self, store):
        """Get the current status of the drawer"""
        station = self.get_current_station(store)
        return self.ensure_printer(station)

    @lock_printer
    def post(self, store):
        """Send a signal to open the drawer"""
        if not api.device_manager.printer:
            raise UnhandledMisconfiguration('Printer not configured in this station')

        api.device_manager.printer.open_drawer()
        return 'success', 200


class PingResource(BaseResource):
    """Ping RESTful resource."""

    routes = ['/ping']

    def get(self):
        log.info('Got ping from client')
        return 'pong from stoqserver'


class TillClosingReceiptResource(BaseResource):
    routes = ['/till/<uuid:till_id>/closing_receipt']
    method_decorators = [login_required, store_provider]

    @classmethod
    def get_till_closing_receipt_image(cls, till):
        image = None
        responses = GenerateTillClosingReceiptImageEvent.send(till)
        if len(responses) == 1:  # Only nonfiscal plugin should answer this signal
            image = responses[0][1]

        return image

    def get(self, store, till_id):
        till = store.get(Till, till_id)

        if not till:
            abort(404)

        if till.status in [Till.STATUS_PENDING, Till.STATUS_OPEN]:
            return None

        return {
            'id': till.id,
            'image': self.get_till_closing_receipt_image(till)
        }


class TillResource(BaseResource):
    """Till RESTful resource."""
    routes = ['/till', '/till/<uuid:till_id>']
    method_decorators = [login_required]

    def _handle_open_till(self, store, last_till, initial_cash_amount=0):
        if not last_till or last_till.status != Till.STATUS_OPEN:
            # Create till and open
            station = self.get_current_station(store)
            till = Till(store=store, station=station, branch=station.branch)
            till.open_till(self.get_current_user(store))
            till.initial_cash_amount = decimal.Decimal(initial_cash_amount)
            return till
        return last_till

    def _close_till(self, store, till, till_summaries):
        # Create TillSummaries
        till.get_day_summary()

        # Find TillSummary and store the user_value
        for till_summary in till_summaries:
            method = PaymentMethod.get_by_name(store, till_summary['method'])

            if till_summary['provider']:
                provider = store.find(CreditProvider, short_name=till_summary['provider']).one()
                summary = TillSummary.get_or_create(store, till=till, method=method,
                                                    provider=provider,
                                                    card_type=till_summary['card_type'])
                summary.user_value = decimal.Decimal(till_summary['user_value'])

            # Money method has no card_data or provider
            else:
                summary = TillSummary.get_or_create(store, till=till, method=method)
                summary.user_value = decimal.Decimal(till_summary['user_value'])
                if api.sysparam.get_bool('INCLUDE_CASH_FUND_ON_TILL_CLOSING'):
                    if summary.user_value < till.initial_cash_amount:
                        raise TillError(_('You are declaring a value less than the initial amount'))
                    else:
                        summary.user_value -= till.initial_cash_amount

        balance = till.get_balance()
        if balance < 0:
            # This till is missing money!
            till.add_credit_entry(abs(balance), _('Blind till closing'))
        till.close_till(self.get_current_user(store))

    def _handle_close_till(self, store, till, till_summaries, include_receipt_image=False):
        station = self.get_current_station(store)
        if not include_receipt_image:
            self.ensure_printer(station)
        if till.status == Till.STATUS_OPEN:
            self._close_till(store, till, till_summaries)

    def _add_credit_or_debit_entry(self, store, till, data):
        # Here till object must exist
        user = self.get_current_user(store)

        # FIXME: Check balance when removing to prevent negative till.
        if data['operation'] == 'debit_entry':
            reason = _('The user %s removed cash from till') % user.username
            till_entry = till.add_debit_entry(decimal.Decimal(data['entry_value']), reason)
        elif data['operation'] == 'credit_entry':
            reason = _('The user %s supplied cash to the till') % user.username
            till_entry = till.add_credit_entry(decimal.Decimal(data['entry_value']), reason)

        return self._print_till_entry(till_entry, user.username)

    def _get_till_summary(self, store, till):
        payment_data = []
        for (method, provider, card_type), value in till.get_day_summary_data().items():
            payment_data.append({
                'method': method.method_name,
                'provider': provider.short_name if provider else None,
                'card_type': card_type,
                'system_value': str(value),
            })

        return payment_data

    def _get_till_data(self, store, till, include_receipt_image=False):
        # Checks the remaining time available for till to be open
        if till.needs_closing():
            expiration_time_in_seconds = 0
        else:
            # Till must be closed on the next day (midnight) + tolerance time
            opening_date = till.opening_date.replace(hour=0, minute=0, second=0, microsecond=0)
            tolerance = api.sysparam.get_int('TILL_TOLERANCE_FOR_CLOSING')
            next_close = opening_date + datetime.timedelta(days=1, hours=tolerance)
            expiration_time_in_seconds = (next_close - localnow()).seconds

        till_data = {
            'id': till.id,
            'status': till.status,
            'opening_date': till.opening_date.strftime('%Y-%m-%d'),
            'closing_date': (till.closing_date.strftime('%Y-%m-%d') if
                             till.closing_date else None),
            'initial_cash_amount': str(till.initial_cash_amount),
            'final_cash_amount': str(till.final_cash_amount),
            # Get payments data that will be used on 'close_till' action.
            'entry_types': till.status == 'open' and self._get_till_summary(store, till) or [],
            'expiration_time_in_seconds': expiration_time_in_seconds  # seconds
        }

        if include_receipt_image:
            till_data["image"] = TillClosingReceiptResource.get_till_closing_receipt_image(till)

        return till_data

    @staticmethod
    def _print_till_entry(till_entry, username):
        log.info('emitting event PrintTillEntryCouponEvent')
        responses = PrintTillEntryCouponEvent.send(till_entry, username=username)
        till_entry_image = responses[0][1] if len(responses) == 1 else None
        return till_entry_image

    @lock_printer
    def post(self):
        data = self.get_json()
        with api.new_store() as store:
            till = Till.get_last(store, self.get_current_station(store))

            # Provide responsible
            if data['operation'] == 'open_till':
                till = self._handle_open_till(store, till, data['initial_cash_amount'])
            elif data['operation'] == 'close_till':
                self._handle_close_till(store, till, data['till_summaries'],
                                        data['include_receipt_image'])
            elif data['operation'] in ['debit_entry', 'credit_entry']:
                till_entry_image = self._add_credit_or_debit_entry(store, till, data)

                return {
                    'till_entry_image': till_entry_image,
                }
            else:
                raise AssertionError('Unkown till operation %r' % data['operation'])

            return self._get_till_data(store, till, data.get('include_receipt_image'))

    def get(self, till_id=None):
        with api.new_store() as store:
            if not till_id:
                till = Till.get_last(store, self.get_current_station(store))
            else:
                till = store.get(Till, till_id)

            if not till:
                abort(404)

            return self._get_till_data(store, till)


class ExternalClientResource(BaseResource):
    """Information about a client from external services, such as Passbook"""
    routes = ['/extra_client_info/<doc>']
    method_decorators = [login_required, store_provider]

    def get(self, store, doc):
        # Extra precaution in case we ever send the cpf already formatted
        station = self.get_current_station(store)
        doc = format_cpf(raw_document(doc))
        responses = signal('GetClientInfoEvent').send(station, document=doc)

        data = dict()
        for response in responses:
            data.update(response[1])
        return data


class LoginResource(BaseResource):
    """Login RESTful resource."""

    routes = ['/login']
    method_decorators = [store_provider]

    def post(self, store):
        username = self.get_arg('user')
        pw_hash = self.get_arg('pw_hash')
        station_name = self.get_arg('station_name')

        station = store.find(BranchStation, name=station_name, is_active=True).one()
        global PDV_VERSION
        PDV_VERSION = request.args.get('pdv_version')
        if not station:
            log.info('Access denied: station not found: %s', station_name)
            abort(401)

        try:
            # FIXME: Respect the branch the user is in.
            user = LoginUser.authenticate(store, username, pw_hash, current_branch=None)
            provide_utility(ICurrentUser, user, replace=True)
        except LoginError as e:
            log.error('Login failed for user %s', username)
            abort(403, str(e))

        token = AccessToken.get_or_create(store, user, station).token
        return jsonify({
            "token": "JWT {}".format(token),
            "user": {"id": user.id},
        })


class LogoutResource(BaseResource):

    routes = ['/logout']
    method_decorators = [store_provider]

    def post(self, store):
        token = self.get_arg('token')
        token = token and token.split(' ')
        token = token[1] if len(token) == 2 else None

        if not token:
            abort(401)

        token = AccessToken.get_by_token(store=store, token=token)
        if not token:
            abort(403, "invalid token")
        token.revoke()

        return jsonify({"message": "successfully revoked token"})


class AuthResource(BaseResource):
    """Authenticate a user agasint the database.

    This will not replace the ICurrentUser. It will just validate if a login/password is valid.
    """

    routes = ['/auth']
    method_decorators = [login_required, store_provider]

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


class TefResource(BaseResource):
    routes = ['/tef/<signal_name>']
    method_decorators = [login_required, store_provider]

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

    def _message_callback(self, lib, message, can_abort=False, qrcode=None):
        with api.new_store() as store:
            station = self.get_current_station(store)
            EventStream.add_event({
                'type': 'TEF_DISPLAY_MESSAGE',
                'message': message,
                'can_abort': can_abort,
                'qrcode': qrcode,
            }, station=station)

        # tef library (ntk/sitef) has some blocking calls (specially pinpad comunication).
        # Before returning, we need to briefly hint gevent to let the EventStream co-rotine run,
        # so that the message above can be sent to the frontend.
        gevent.sleep(0.001)

    def _question_callback(self, lib, question):
        with api.new_store() as store:
            station = self.get_current_station(store)
            reply = EventStream.ask_question(station, question)

        if reply is STREAM_BROKEN:
            raise EventStreamBrokenException()
        return reply

    @lock_pinpad(block=True)
    def post(self, store, signal_name):
        station = self.get_current_station(store)
        if signal_name not in ['StartTefSaleSummaryEvent', 'StartTefAdminEvent']:
            till = Till.get_last(store, station)
            if not till or till.status != Till.STATUS_OPEN:
                raise TillError(_('There is no till open'))

        try:
            # Only lock printer in single client mode
            if not is_multiclient():
                with printer_lock:
                    self.ensure_printer(station)
        except Exception:
            EventStream.add_event({
                'type': 'TEF_OPERATION_FINISHED',
                'success': False,
                'message': 'Erro comunicando com a impressora',
            }, station=station)
            return

        # FIXME: If we fix sitef/ntk, we should be able to use only sender = station
        if is_multiclient():
            # When running in multi client mode, we want the callbacks to only get the signals
            # emmited for the current station.
            sender = station
        else:
            # In single client it doens't matter, since there can be only one client connected
            sender = ANY_SENDER

        signal('TefMessageEvent').connect(self._message_callback, sender=sender)
        signal('TefQuestionEvent').connect(self._question_callback, sender=sender)
        signal('TefPrintEvent').connect(self._print_callback, sender=sender)

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
            retval = operation_signal.send(station, **data)[0][1]
            message = retval['message']
        except EventStreamBrokenException:
            retval = False
            message = 'Falha na operação. Tente novamente'
        except Exception as e:
            retval = False
            log.info('Tef failed: %s', str(e))
            if len(e.args) == 2:
                message = e.args[1]
            else:
                message = 'Falha na operação'

        EventStream.add_event({
            'type': 'TEF_OPERATION_FINISHED',
            'success': retval,
            'message': message,
        }, station=station)


class TefReplyResource(BaseResource):
    routes = ['/tef/reply']
    method_decorators = [login_required, store_provider]

    def post(self, store):
        data = self.get_json()
        station = self.get_current_station(store)
        EventStream.add_event_reply(station.id, data['value'])


class TefCancelCurrentOperation(BaseResource):
    routes = ['/tef/abort']
    method_decorators = [login_required]

    def post(self):
        signal('TefAbortOperationEvent').send()


class ImageResource(BaseResource):
    """Image RESTful resource."""

    routes = ['/image/<id>']

    def get(self, id):
        is_main = bool(request.args.get('is_main', None))
        keyword_filter = request.args.get('keyword')
        # FIXME: The images should store tags so they could be requested by that tag and
        # product_id. At the moment, we simply check if the image is main or not and
        # return the first one.
        with api.new_store() as store:
            images = store.find(Image, sellable_id=id, is_main=is_main)
            if keyword_filter:
                images = images.find(Image.keywords.like('%{}%'.format(keyword_filter)))
            image = images.any()
            if image:
                return send_file(io.BytesIO(image.image), mimetype='image/png')
            else:
                response = make_response(_("Image not found."), 404)
                return response


class SaleResourceMixin:
    """Mixin class that provides common methods for sale/advance_payment

    This includes:

        - Payment creation
        - Client verification
        - Sale/Advance already saved checking
    """

    def _check_already_saved(self, store, klass, obj_id, should_print_receipts,
                             external_order_id=None, order_number=None):
        sale = store.get(klass, obj_id)
        if not sale:
            return

        log.info('Sale already saved: %s' % obj_id)
        log.info('send CheckCouponTransmittedEvent signal')
        # XXX: This might not really work for AdvancePayment, we need to test this. It might
        # need specific handling.
        is_coupon_transmitted = signal('CheckCouponTransmittedEvent').send(sale)[0][1]
        if is_coupon_transmitted and should_print_receipts:
            # This will return an print error and the user will be presented with a message to print
            # again
            return self._handle_coupon_printing_fail(sale)

        retval = signal('GetInvoiceDataEvent').send(sale)
        invoice_data = retval[0][1] if retval else {}
        kps_image = None
        if (sale.station.has_kps_enabled and sale.get_kitchen_items()
                and not external_order_id):
            kps_image = self._print_kps(sale, order_number)

        return {
            'id': sale.id,
            'client_id': sale.client_id,
            'invoice_data': invoice_data,
            'transmitted': is_coupon_transmitted,
            'kps_image': kps_image,
        }

    def _get_client_and_document(self, store, data):
        client_id = data.get('client_id')
        # We remove the format of the document and then add it just
        # as a precaution in case it comes not formatted
        coupon_document = raw_document(data.get('coupon_document', '') or '')
        if coupon_document:
            coupon_document = format_document(coupon_document)
        client_document = raw_document(data.get('client_document', '') or '')
        if client_document:
            client_document = format_document(client_document)

        client = None
        if client_id:
            client = store.get(Client, client_id)
        elif client_document:
            person = Person.get_by_document(store, client_document)
            if person and person.client:
                client = person.client
            elif person and not person.client:
                client = Client(store=store, person=person)

        client_name = data.get('client_name')
        address = data.get('address')
        # We should change the api callsite so that city_location is inside the address
        if address:
            address.setdefault('city_location', data.get('city_location'))

        if not client and client_document and client_name:
            client = ClientResource.create_client(store, client_name, client_document, address)

        if client and not client.person.address and address:
            ClientResource.create_address(client.person, address)

        return client, client_document, coupon_document

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
        if not name:
            name = _("UNKNOWN")
        received_name = name.strip()
        name = PROVIDER_MAP.get(received_name, received_name)
        provider = store.find(CreditProvider, provider_id=name).one()
        if not provider:
            provider = CreditProvider(store=store, short_name=name, provider_id=name)
            log.info('Could not find a provider named %s', name)
        else:
            log.info('Fixing card name from %s to %s', received_name, name)
        return provider

    def _create_payments(self, store, group, branch, station, sale_total, payment_data):
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

            payment_value = Decimal(p['value'])
            payments_total += payment_value

            p_list = method.create_payments(
                branch, station, Payment.TYPE_IN, group,
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
                    # This card_type does not exist in stoq. Change it to 'credit'.
                    if card_type not in CreditCardData.types:
                        log.info('Invalid card type %s. changing to credit', card_type)
                        card_type = 'credit'
                    # FIXME Stoq already have the voucher concept, but we should keep this for a
                    # little while for backwars compatibility
                    elif card_type == 'voucher':
                        card_type = 'debit'
                    provider = self._get_provider(store, p['provider'])

                    if tef_data:
                        card_data.nsu = tef_data['nsu']
                        card_data.auth = tef_data['auth']
                        card_data.card_bin = tef_data.get('card_bin')
                        card_data.holder_name = tef_data.get('holder_name')
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


class SaleResource(BaseResource, SaleResourceMixin):
    """Sellable category RESTful resource."""

    routes = ['/sale', '/sale/<string:sale_id>']
    method_decorators = [login_required, store_provider]

    def _handle_nfe_coupon_rejected(self, sale, reason):
        log.exception('NFC-e sale rejected: {}'.format(sale))
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

    def _nfe_progress_event(self, message):
        with api.new_store() as store:
            station = self.get_current_station(store)
            EventStream.add_event({'type': 'NFE_PROGRESS', 'message': message}, station=station)

    def _nfe_warning_event(self, message, details):
        with api.new_store() as store:
            station = self.get_current_station(store)
            EventStream.add_event({'type': 'NFE_WARNING', 'message': message, 'details': details},
                                  station=station)

    def _nfe_success_event(self, message, details=None):
        with api.new_store() as store:
            station = self.get_current_station(store)
            EventStream.add_event({'type': 'NFE_SUCCESS', 'message': message, 'details': details},
                                  station=station)

    def _remove_passbook_stamps(self, store, passbook_client, sale_id):
        data = {
            'value': passbook_client['stamps_limit'],
            'card_type': "credit",
            'provider': "",
            'user': self.get_current_user(store),
            'sale_ref': sale_id,
            'client': {
                'name': passbook_client['user']['name'],
                'doc': passbook_client['user']['uniqueId'],
                'passbook_client_info': passbook_client
            },
        }
        StartPassbookSaleEvent.send(self.get_current_station(store), **data)

    def _create_delivery(self, sale: Sale, client: Client, data) -> Optional[Delivery]:
        '''
        delivery: {
            freight_type: [cif|fob|3rdparty|None]
            price: 1.00,
            transporter: {
                cnpj: ''
                name: '',
                address: {
                    ...
                }
            }
            volumes: {
                kind: 'Volumes',
                quantity: 1.0,
                gross_weight: 1.0,
                net_weight: 1.0,
            }
        }
        '''
        if not data:
            return None

        transporter = None
        if data.get('transporter'):
            trans_data = data['transporter']
            cnpj = format_document(trans_data['cnpj'])
            person = Person.get_by_document(sale.store, cnpj)
            if not person:
                person = Person(store=sale.store, name=trans_data['name'])
                Company(store=sale.store, cnpj=cnpj, person=person)
                Transporter(store=sale.store, person=person)

            transporter = person.transporter
            if not transporter:
                transporter = Transporter(store=sale.store, person=person)

            if not transporter.person.address and 'address' in trans_data:
                ClientResource.create_address(transporter.person, trans_data['address'])
        else:
            # There is no transporter in the payload, but we still need one. Use the branch as
            # transporter
            transporter = sale.branch.person.transporter
            if not transporter:
                transporter = Transporter(store=sale.store, person=sale.branch.person)

        delivery = Delivery(store=sale.store, transporter=transporter)
        delivery.invoice = sale.invoice
        if client:
            delivery.address = client.person.address
        if not delivery.address:
            # FIXME: The client might be missing an address, or the payload might have come without
            # a client. Either way, a delivery needs an address, so fallback to the branch address
            # for now
            delivery.address = sale.branch.person.address

        delivery.freight_type = data.get('freight_type')  # This is optional
        if data.get('volumes'):
            delivery.volumes_kind = data['volumes'].get('kind')
            delivery.volumes_quantity = data['volumes'].get('quantity')
            delivery.volumes_gross_weight = data['volumes'].get('gross_weight')
            delivery.volumes_net_weight = data['volumes'].get('net_weight')

        # This is required by nfe, but we should fix that
        sale.transporter = transporter

        delivery_sellable = api.sysparam.get_object(sale.store, 'DELIVERY_SERVICE').sellable
        sale.add_sellable(delivery_sellable, price=data['price'], quantity=1)
        return delivery

    def _apply_ifood_discount_hack(self, store, data):
        config = get_config()
        discount = decimal.Decimal(config.get("Hacks", "ifood_promo_discount") or 0)
        sale_value = decimal.Decimal(config.get("Hacks", "ifood_promo_sale_value") or 0)
        if not discount or not sale_value:
            # Not configured
            return data

        branches = config.get("Hacks", "ifood_promo_branches")
        branch = self.get_current_branch(store)
        if branches and branch.acronym not in [i.strip() for i in branches.split(',')]:
            return data

        for p in data['payments']:
            payment_value = Decimal(p['value'])
            if p.get('provider') == 'IFOOD' and payment_value >= sale_value:
                p['value'] = str(payment_value - discount)
                data['discount_value'] = discount
                if 'passbook_client_info' in data:
                    # Set client points to zero, so that we don't end removing the clients points.
                    data['passbook_client_info']['points'] = 0
                break

        return data

    @staticmethod
    def _print_kps(sale, order_number):
        if order_number in {'0', '', None}:
            log.error('Invalid order number: %s', order_number)
            abort(400, "Invalid order number")

        log.info('emitting event PrintKitchenCouponEvent {}'.format(order_number))
        responses = PrintKitchenCouponEvent.send(sale, order_number=order_number)
        kps_image = responses[0][1] if len(responses) == 1 else None
        return kps_image

    @lock_printer
    @lock_sat(block=True)
    def post(self, store):
        # FIXME: Check branch state and force fail if no override for that product is present.
        data = self.get_json()
        products = data['products']
        client_category_id = data.get('price_table')
        should_print_receipts = data.get('print_receipts', True)
        postpone_emission = data.get('postpone_emission', False)
        external_order_id = data.get('external_order_id')
        order_number = data.get('order_number')

        log.debug("POST /sale station: %s payload: %s",
                  self.get_current_station(store), data)

        client, client_document, coupon_document = self._get_client_and_document(store, data)

        sale_id = data.get('sale_id')
        early_response = self._check_already_saved(store, Sale, sale_id, should_print_receipts,
                                                   external_order_id, order_number)
        if early_response:
            return early_response

        data = self._apply_ifood_discount_hack(store, data)

        # Print the receipts and confirm the transaction before anything else. If the sale fails
        # (either by a sat device error or a nfce conectivity/rejection issue), the tef receipts
        # will still be printed/confirmed and the user can finish the sale or the client.
        TefPrintReceiptsEvent.send(sale_id)

        # Create the sale
        branch = self.get_current_branch(store)
        station = self.get_current_station(store)
        user = self.get_current_user(store)
        group = PaymentGroup(store=store)
        discount_value = data.get('discount_value', 0) or 0
        passbook_client = data.get('passbook_client_info')
        if data.get('open_date'):
            open_date = datetime.datetime.strptime(data['open_date'], '%Y-%m-%d %H:%M:%S')
        else:
            open_date = localnow()

        sale = Sale(
            store=store,
            id=sale_id,
            branch=branch,
            station=station,
            salesperson=user.person.sales_person,
            client=client,
            client_category_id=client_category_id,
            group=group,
            open_date=open_date,
            coupon_id=None,
            discount_value=discount_value,
        )

        delivery = self._create_delivery(sale, client, data.get('delivery'))

        # Sale Context
        context_id = data.get('context_id')
        context = store.get(Context, context_id)
        if context_id and branch == context.branch:
            SaleContext(
                store=store,
                sale_id=sale_id,
                context_id=context_id,
            )

        # Add products
        for p in products:
            if not Decimal(p['price']):
                continue

            sellable = store.get(Sellable, p['id'])
            if sellable is None:
                config = get_config()
                if (config.get("Hacks", "create_sellable_on_sale") or "").lower() == 'true':
                    sellable = Sellable(store=store)
                    sellable.id = p['id']
                    sellable.notes = Sellable.NOTES_CREATED_VIA_SALE
                    product = Product(store=store, sellable=sellable)
                    storable = Storable(store=store, product=product)
                    storable.maximum_quantity = 1000
                    log.warning('Sellable %s created', sellable)
                else:
                    log.error('Sellable %s does not exist', p)
                    abort(400, 'Sellable {} doesn\'t exist'.format(p['id']))

            product = sellable.product
            if product and product.is_package:
                # External orders might send a different price for a package, and we must adjust the
                # children prices to make them match
                diff = decimal.Decimal(p['price']) - sellable.price

                parent = sale.add_sellable(sellable, price=0,
                                           quantity=decimal.Decimal(p['quantity']))
                parent.delivery = delivery
                # XXX: Maybe this should be done in sale.add_sellable automatically, but this would
                # require refactoring stoq as well.
                for child in product.get_components():
                    quantity = child.quantity * decimal.Decimal(p['quantity'])
                    price = child.price
                    if diff:
                        price = price + quantize(diff * price / sellable.price)

                    item = sale.add_sellable(child.component.sellable, price=price,
                                             quantity=quantity, parent=parent)
                    # FIXME: The same comment bellow applies
                    item.base_price = item.price
                    item.delivery = delivery
            else:
                item = sale.add_sellable(sellable, price=Decimal(p['price']),
                                         quantity=decimal.Decimal(p['quantity']))
                item.delivery = delivery

                # FIXME: There seems to be a parameter in the nfce plugin to handle exactly this. We
                # should duplicate the behaviour for the sat plugin and remove this code
                # XXX: bdil has requested that when there is a special discount, the discount does
                # not appear on the coupon. Instead, the item wil be sold using the discount price
                # as the base price. Maybe this should be a parameter somewhere
                item.base_price = item.price

        # Add payments
        self._create_payments(store, group, branch, station,
                              sale.get_total_sale_amount(), data['payments'])

        if (discount_value > 0 and passbook_client
                and 'points' in passbook_client and 'stamps_limit' in passbook_client
                and 'stamps' in passbook_client.get('type', [])
                and decimal.Decimal(passbook_client['points']) >= passbook_client['stamps_limit']):
            self._remove_passbook_stamps(store, passbook_client, sale_id)

        # Confirm the sale
        group.confirm()
        sale.order(user)

        if external_order_id:
            log.info("emitting event FinishExternalOrderEvent %s", external_order_id)
            try:
                FinishExternalOrderEvent.send(sale, external_order_id=external_order_id)
            except ExternalOrderError as exc:
                log.error('Event failed: %s', exc.reason)
                abort(409, exc.reason)

        till = Till.get_last(store, station)
        if station.is_api and not till:
            # Some may access /sale endpoint outside our PDV. In this case we may not have a
            # till to register the entry
            till = Till(store=store, branch=branch, station=station)
            till.open_till(user)
        elif till.status != Till.STATUS_OPEN:
            raise TillError(_('There is no till open'))

        sale.confirm(user, till)

        GrantLoyaltyPointsEvent.send(sale, document=(client_document or coupon_document))

        if has_nfe:
            NfeProgressEvent.connect(self._nfe_progress_event)
            NfeWarning.connect(self._nfe_warning_event)
            NfeSuccess.connect(self._nfe_success_event)

        if sale.has_pre_created_sellables:
            # Since sale has sellables pre-created via sale and therefore with tax information
            # missing, emission should be skipped to be made once its information is fulfilled
            invoice_data = None
            log.warning('Pre-created sellables without tax information found, '
                        'skipping emission for %s', sale)
        else:
            # Fiscal plugins will connect to this event and "do their job"
            # It's their responsibility to raise an exception in case of any error
            try:
                invoice_data = SaleConfirmedRemoteEvent.emit(
                    sale, coupon_document, should_print_receipts, postpone_emission)
            except (NfePrinterException, SatPrinterException):
                return self._handle_coupon_printing_fail(sale)
            except NfeRejectedException as e:
                return self._handle_nfe_coupon_rejected(sale, e.reason)

        kps_image = None
        if sale.station.has_kps_enabled and sale.get_kitchen_items() and not external_order_id:
            kps_image = self._print_kps(sale, order_number)

        transmitted = invoice_data.get('transmitted', False) if invoice_data else False

        retval = {
            'sale_id': sale.id,
            'client_id': client and client.id,
            'invoice_data': invoice_data,
            'kps_image': kps_image,
            'transmitted': transmitted,
        }
        return retval, 201

    def get(self, store, sale_id):
        sale = store.get(Sale, sale_id)
        if not sale:
            abort(404)
        retval = signal('GetInvoiceDataEvent').send(sale)
        invoice_data = retval[0][1] if retval else {}
        return {
            'id': sale.id,
            'confirm_date': str(sale.confirm_date),
            'items': self._encode_items(sale.get_items()),
            'total': str(sale.total_amount),
            'payments': self._encode_payments(sale.payments),
            'client': sale.get_client_name(),
            'status': sale.status_str,
            'transmitted': invoice_data.get('transmitted', False),
            'invoice_data': invoice_data,
        }, 200

    def delete(self, store, sale_id):
        # This is not really 'deleting' a sale, but informing us that a sale was never confirmed
        # this is necessary since we can create payments for a sale before it actually exists, those
        # paymenst might need to be canceled
        signal('SaleAbortedEvent').send(sale_id)


class AdvancePaymentResource(BaseResource, SaleResourceMixin):

    routes = ['/advance_payment']
    method_decorators = [login_required, store_provider]

    @lock_printer
    def post(self, store):
        # We need to delay this import since the plugin will only be in the path after stoqlib
        # initialization
        from stoqpassbook.domain import AdvancePayment
        data = self.get_json()
        client, client_document, coupon_document = self._get_client_and_document(store, data)

        advance_id = data.get('sale_id')
        should_print_receipts = data.get('print_receipts', True)
        early_response = self._check_already_saved(
            store, AdvancePayment, advance_id, should_print_receipts)
        if early_response:
            return early_response

        total = 0
        for p in data['products']:
            total += Decimal(p['price']) * decimal.Decimal(p['quantity'])

        # Print the receipts and confirm the transaction before anything else. If the sale fails
        # (either by a sat device error or a nfce conectivity/rejection issue), the tef receipts
        # will still be printed/confirmed and the user can finish the sale or the client.
        TefPrintReceiptsEvent.send(advance_id)

        branch = self.get_current_branch(store)
        station = self.get_current_station(store)
        user = self.get_current_user(store)
        group = PaymentGroup(store=store)
        advance = AdvancePayment(
            id=advance_id,
            store=store,
            client=client,
            total_value=total,
            branch=branch,
            station=station,
            group=group,
            responsible=user)

        # Add payments
        self._create_payments(store, group, branch, station, advance.total_value, data['payments'])
        till = Till.get_last(store, station)
        if not till or till.status != Till.STATUS_OPEN:
            raise TillError(_('There is no till open'))
        advance.confirm(till)

        GrantLoyaltyPointsEvent.send(advance, document=(client_document or coupon_document))

        # FIXME: We still need to implement the receipt in non-fiscal plugin
        try:
            PrintAdvancePaymentReceiptEvent.send(advance, document=coupon_document)
        except Exception:
            return self._handle_coupon_printing_fail(advance)

        return True


class AdvancePaymentCouponImageResource(BaseResource):

    routes = ['/advance_payment/<string:id>/coupon']
    method_decorators = [login_required, store_provider]

    def get(self, store, id):
        responses = GenerateAdvancePaymentReceiptPictureEvent.send(id)

        if len(responses) == 0:
            abort(400)

        return {
            'image': responses[0][1],
        }, 200


class PrintCouponResource(BaseResource):
    """Image RESTful resource."""

    routes = ['/sale/<sale_id>/print_coupon']
    method_decorators = [login_required, store_provider]

    @lock_printer
    def get(self, store, sale_id):
        self.ensure_printer(self.get_current_station(store))

        sale = store.get(Sale, sale_id)
        signal('PrintCouponCopyEvent').send(sale)


class SaleCouponImageResource(BaseResource):

    routes = ['/sale/<string:sale_id>/coupon']
    method_decorators = [login_required, store_provider]

    def get(self, store, sale_id):
        sale = store.get(Sale, sale_id)
        if not sale:
            abort(400)

        responses = GenerateInvoicePictureEvent.send(sale)
        try:
            image, mimetype = responses[0][1]
        except (TypeError, ValueError):
            image = responses[0][1]
            mimetype = None

        if request.args.get('download'):
            return self._get_danfe(image, mimetype)

        assert len(responses) >= 0
        return {
            'image': image,
            'mimetype': mimetype,
        }, 200

    def _get_danfe(self, image, mimetype):
        image_decoded = base64.b64decode(image)
        return send_file(io.BytesIO(image_decoded), mimetype=mimetype)


class SmsResource(BaseResource):
    """SMS RESTful resource."""
    routes = ['/sale/<sale_id>/send_coupon_sms']
    method_decorators = [login_required, store_provider]

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


class PassbookUsersResource(BaseResource):
    """Resource for fetching users given the beginning of a document (CPF)"""
    routes = ['/passbook/users']
    method_decorators = [login_required, store_provider]

    def get(self, store):
        partial_doc = request.args.get('partial_document')
        if not partial_doc:
            abort(400, 'Missing partial document')

        branch = self.get_current_branch(store)
        try:
            return SearchForPassbookUsersByDocumentEvent.send(branch,
                                                              partial_document=partial_doc)[0][1]
        except ValueError:
            abort(400, 'Invalid partial document')


class ExternalOrderResource(BaseResource):
    method_decorators = [login_required, store_provider]
    routes = ['/external_order/<external_order_id>/<action>']

    @lock_printer
    def _confirm_order(self, store, external_order_id):
        log.info("emitting event StartExternalOrderEvent %s", external_order_id)
        StartExternalOrderEvent.send(self.get_current_station(store),
                                     external_order_id=external_order_id)
        return 'External order confirmed'

    def _cancel_order(self, store, external_order_id):
        data = self.get_json()
        cancellation_code = data.get('code')
        cancellation_details = data.get('reason')
        log.info("emitting event CancelExternalOrderEvent %s", external_order_id)
        CancelExternalOrderEvent.send(self.get_current_station(store),
                                      external_order_id=external_order_id,
                                      cancellation_code=cancellation_code,
                                      cancellation_details=cancellation_details)
        return 'External order cancelled'

    def _ready_to_deliver(self, store, external_order_id):
        log.info("emitting event ReadyToDeliverExternalOrderEvent %s", external_order_id)
        ReadyToDeliverExternalOrderEvent.send(self.get_current_station(store),
                                              external_order_id=external_order_id)
        return 'External order ready to deliver'

    def _get_receipt_image(self, store, external_order_id):
        station = self.get_current_station(store)
        responses = GenerateExternalOrderReceiptImageEvent.send(station,
                                                                external_order_id=external_order_id)
        if len(responses) == 1:  # Only ifood plugin should answer this signal
            return responses[0][1]

        return None

    def _print_external_order(self, store, external_order_id):
        station = self.get_current_station(store)
        PrintExternalOrderEvent.send(station, external_order_id=external_order_id)
        return 'External order printed'

    def post(self, store, external_order_id, action):
        try:
            if action == 'confirm':
                success_msg = self._confirm_order(store, external_order_id)
            elif action == 'cancel':
                success_msg = self._cancel_order(store, external_order_id)
            elif action == 'ready_to_deliver':
                success_msg = self._ready_to_deliver(store, external_order_id)
        except ExternalOrderError as exc:
            abort(409, exc.reason)
        return {"msg": success_msg}, 201

    def get(self, store, external_order_id, action):
        if action == 'print':
            success_msg = self._print_external_order(store, external_order_id)
            return {'msg': success_msg}

        return {
            'id': external_order_id,
            'image': self._get_receipt_image(store, external_order_id)
        }


class LockerResource(BaseResource):
    method_decorators = [login_required]
    routes = ['/locker']

    def _open_locker(self, locker_number, locker_mac, timeout=1):
        locker_data = {"mac": locker_mac, "output": locker_number, "timeout": timeout}

        config = get_config()
        api_key = config.get("Condlink", "api_key")
        headers = {"x-api-key": api_key}
        response = requests.post('https://onii.condlink.com.br/accessDevice/v1/comm5',
                                 headers=headers, data=locker_data)
        return response.text

    @login_required
    def post(self):
        data = self.get_json()

        locker_number = data.get('lockerNumber')
        locker_mac = data.get('lockerMac')

        if not locker_number:
            return {'message': 'No locker_number provided'}, 400

        if not locker_mac:
            return {'message': 'No locker_mac provided'}, 400

        return self._open_locker(locker_number, locker_mac)
