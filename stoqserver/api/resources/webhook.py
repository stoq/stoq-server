import logging

from stoqserver.lib.baseresource import BaseResource
from stoqserver.api.decorators import login_required
from stoqserver.signals import WebhookEvent

log = logging.getLogger(__name__)


class WebhookEventResource(BaseResource):
    method_decorators = [login_required]
    routes = ['/v1/webhooks/event']

    def post(self):
        data = self.get_json()
        log.info('Webhook event: %s', data)

        # An event can have multiple replies
        replies = [i[1] for i in WebhookEvent.send(data) if [1]]

        # Get first non false response from the event
        reply = replies[0] if replies else None
        return reply, 200
