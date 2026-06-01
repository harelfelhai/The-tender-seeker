"""Notification layer: alert companies when new matching tenders are found.

Adding a new channel (Slack, webhook, SMS):
  1. Create src/smarttender/notifications/slack.py
  2. Implement the Notifier Protocol
  3. Add it to the notifiers list in app.py lifespan

That's it — no other changes needed.
"""
from .base import NotificationEvent, Notifier
from .console_notifier import ConsoleNotifier
from .email_notifier import EmailNotifier

__all__ = ["NotificationEvent", "Notifier", "ConsoleNotifier", "EmailNotifier"]
