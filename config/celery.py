"""
Celery application for the project.

Start a worker with:   celery -A config worker -l info
Start the scheduler:   celery -A config beat -l info
"""

import os

from celery import Celery

# Tell Celery which Django settings module to use.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")

# Read every setting that starts with "CELERY_" from Django's settings.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Find tasks.py in every installed app automatically.
app.autodiscover_tasks()
