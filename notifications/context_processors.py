def unread_notifications(request):
    """
    Adds "unread_notification_count" to every template, for the badge
    in the navbar. Listed in TEMPLATES in settings.py.
    """
    if not request.user.is_authenticated:
        return {}
    count = request.user.notifications.filter(is_read=False).count()
    return {"unread_notification_count": count}
