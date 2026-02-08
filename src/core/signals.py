# src/core/signals.py
from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver
from django.core.management import call_command
import logging

logger = logging.getLogger(__name__)

@receiver(user_logged_out)
def reset_data_on_logout(sender, user, request, **kwargs):
    """
    Triggered when a user logs out.
    If the user was the guest visitor, we WIPE the database so the next
    person (real or demo) starts fresh.
    """
    if user and user.username == 'guest_visitor':
        try:
            print("🧹 Demo User logged out. Clearing all data...")
            # Use the new --clear-only flag to wipe without reseeding
            call_command('seed_data', clear_only=True)
            print("✅ Data wiped successfully.")
        except Exception as e:
            logger.error(f"Failed to clear data on logout: {e}")
