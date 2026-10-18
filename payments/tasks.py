"""Celery tasks for the payments app (scheduled in settings.py)."""

from celery import shared_task

from . import services


@shared_task
def expire_overdue_payments_task():
    """Run by Celery Beat every 10 minutes."""
    return services.expire_overdue_payments()


@shared_task
def send_payment_reminders_task():
    """Run by Celery Beat every 10 minutes."""
    return services.send_payment_reminders()
