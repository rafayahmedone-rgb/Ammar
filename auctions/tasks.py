"""Celery tasks for the auctions app (scheduled in settings.py)."""

from celery import shared_task

from . import services


@shared_task
def close_ended_auctions_task():
    """Run by Celery Beat every minute."""
    return services.close_ended_auctions()
