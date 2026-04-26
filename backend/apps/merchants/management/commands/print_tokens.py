from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token

from apps.merchants.models import Merchant


class Command(BaseCommand):
    help = "Print API tokens for every merchant."

    def handle(self, *args, **options):
        for m in Merchant.objects.all().select_related("user"):
            try:
                token = Token.objects.get(user=m.user).key
            except Token.DoesNotExist:
                token = "(none)"
            self.stdout.write(f"{m.name:<20} {m.email:<25} token={token}")
