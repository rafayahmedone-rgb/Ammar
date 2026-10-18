from django.conf import settings
from django.db import models


class Notification(models.Model):
    """
    A message to one user, e.g. "You have been outbid".

    It is shown on the user's Notifications page and also sent by email
    (by the send_notification_email Celery task).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    subject = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # Set once the email has been sent, so it is never sent twice.
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"To {self.user.username}: {self.subject}"
