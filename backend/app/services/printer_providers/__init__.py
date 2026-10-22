"""Printer provider adapters for Printbuddy.

Bambu support comes from the original foundation. Klipper and Mainsail use the Moonraker API
surface and are introduced behind this provider boundary so the rest of the app can
move away from hard-coded Bambu MQTT assumptions incrementally.
"""

__all__ = ["SUPPORTED_PROVIDERS", "create_printer_client"]


def __getattr__(name: str):
    if name in __all__:
        from backend.app.services.printer_providers import factory

        return getattr(factory, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
