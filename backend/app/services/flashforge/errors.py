"""Sanitized exceptions shared by FlashForge transports."""


class FlashForgeError(Exception):
    """Base class for safe, user-facing FlashForge protocol errors."""


class FlashForgeTransportError(FlashForgeError):
    """Network, HTTP, or malformed-response failure."""


class FlashForgeAuthenticationError(FlashForgeError):
    """The printer rejected the LAN credential or LAN API is disabled."""


class FlashForgeCommandBusyError(FlashForgeError):
    """The printer's exclusive TCP command channel is held elsewhere."""


class FlashForgeResponseTooLargeError(FlashForgeTransportError):
    """The peer exceeded the configured response size bound."""
