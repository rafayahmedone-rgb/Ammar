from django.shortcuts import render


def home(request):
    """Show the landing page."""
    return render(request, "core/home.html")
