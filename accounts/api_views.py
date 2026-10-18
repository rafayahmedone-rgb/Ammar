from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import UserSerializer


class MeView(APIView):
    @extend_schema(responses={200: UserSerializer})
    def get(self, request):
        """The logged-in user's details, including their role."""
        return Response(UserSerializer(request.user).data)
