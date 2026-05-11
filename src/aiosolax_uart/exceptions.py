"""Exceptions raised by aiosolax_uart."""

from __future__ import annotations


class SolaxError(Exception):
    """Base exception for all aiosolax_uart errors."""


class SolaxConnectionError(SolaxError):
    """Raised when the underlying serial connection fails."""


class SolaxProtocolError(SolaxError):
    """Raised when a frame fails decoding (bad header, length, or checksum)."""


class SolaxRegistrationError(SolaxError):
    """Raised when the inverter does not acknowledge dongle registration."""
