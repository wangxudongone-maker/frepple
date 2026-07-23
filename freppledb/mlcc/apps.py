from django.apps import AppConfig


class MlccConfig(AppConfig):
    name = "freppledb.mlcc"
    verbose_name = "MLCC"

    def ready(self):
        # Importing connects validation signals for dynamically injected fields.
        from . import signals  # noqa: F401
