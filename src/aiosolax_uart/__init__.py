"""Async library to read SolaX inverters over UART using the Pocket USB protocol.

Supports inverters that accept the SolaX Pocket WiFi / Pocket USB dongle — see
the README for the verified-supported list and the framework for adding more.
"""

from .client import DEFAULT_DONGLE_SERIAL, SolaxClient
from .const import (
    BAUD_RATE,
    DONGLE_SERIAL_LENGTH,
    INVERTER_MODES,
)
from .exceptions import (
    SolaxConnectionError,
    SolaxError,
    SolaxProtocolError,
    SolaxRegistrationError,
)
from .models import (
    MODELS,
    DeviceInfo,
    InverterFamily,
    InverterModel,
    LiveData,
    lookup_model,
)

__all__ = [
    "BAUD_RATE",
    "DEFAULT_DONGLE_SERIAL",
    "DONGLE_SERIAL_LENGTH",
    "INVERTER_MODES",
    "MODELS",
    "DeviceInfo",
    "InverterFamily",
    "InverterModel",
    "LiveData",
    "SolaxClient",
    "SolaxConnectionError",
    "SolaxError",
    "SolaxProtocolError",
    "SolaxRegistrationError",
    "lookup_model",
]
