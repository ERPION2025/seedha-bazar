from django.apps import AppConfig


class ProfilesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "profiles"

    def ready(self):
        from django.db.models.signals import post_save

        from accounts.models import User

        from . import signals

        post_save.connect(signals.create_profile, sender=User, dispatch_uid="profiles_create_profile")
