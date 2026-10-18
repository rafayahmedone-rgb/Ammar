from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import NotificationSerializer


class NotificationListView(generics.ListAPIView):
    """Your notifications, newest first."""

    serializer_class = NotificationSerializer

    def get_queryset(self):
        return self.request.user.notifications.all()


class MarkAllReadView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        """Mark all of your notifications as read."""
        request.user.notifications.filter(is_read=False).update(is_read=True)
        return Response(status=204)
