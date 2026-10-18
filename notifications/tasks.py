"""Celery task that emails a notification."""

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import Notification


@shared_task
def send_notification_email(notification_id):
    """
    Email one Notification to its user. Returns True if an email was sent.

    In development the console email backend prints the email in the
    terminal where the Celery worker (or runserver, in eager mode) runs.
    """
    notification = Notification.objects.select_related("user").get(
        pk=notification_id
    )
    # Skip if already sent, or if the user has no email address.
    if notification.emailed_at or not notification.user.email:
        return False

    send_mail(
        subject=settings.EMAIL_SUBJECT_PREFIX + notification.subject,
        message=notification.message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[notification.user.email],
    )
    notification.emailed_at = timezone.now()
    notification.save(update_fields=["emailed_at"])
    return True
