"""
Run the periodic jobs once, without Celery or Redis.

Handy for manual testing:  python manage.py run_periodic_tasks
In normal use Celery Beat runs these jobs on a schedule instead.
"""

from django.core.management.base import BaseCommand

from auctions.services import close_ended_auctions
from payments.services import expire_overdue_payments


class Command(BaseCommand):
    help = "Close ended auctions and expire overdue payments."

    def handle(self, *args, **options):
        closed = close_ended_auctions()
        expired = expire_overdue_payments()
        self.stdout.write(
            self.style.SUCCESS(
                f"Closed {closed} auction(s), "
                f"expired {expired} payment(s)."
            )
        )
