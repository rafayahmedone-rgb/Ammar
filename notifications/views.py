from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def notification_list(request):
    """Show the user's notifications and mark them all as read."""
    # list() runs the query now, so the page still shows which ones were
    # new before the update below marks them as read.
    notifications = list(request.user.notifications.all()[:50])
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return render(
        request,
        "notifications/notification_list.html",
        {"notifications": notifications},
    )
