"""Constants for the SolaX Pocket USB protocol.

The inverter's USB port speaks a proprietary frame format originally consumed
by SolaX's "Pocket WiFi/USB" dongle. Reverse-engineered by xdubx:
https://github.com/xdubx/Solax-Pocket-USB-reverse-engineering
"""

from __future__ import annotations

from enum import IntEnum

BAUD_RATE = 9600

HEADER = b"\xaa\x55"

DONGLE_SERIAL_LENGTH = 10


class ControlCode(IntEnum):
    """Control byte values."""

    QUERY = 0x01
    REGISTER = 0x02
    SETTING_WRITE = 0x05
    SETTING_RESPONSE = 0x03


class Function(IntEnum):
    """Function byte values used by the host."""

    REQUEST_SERIAL = 0x05
    REGISTER_DONGLE = 0x01
    REQUEST_DATA = 0x0C
    REQUEST_ERRORS = 0x04
    REQUEST_SETTINGS = 0x16


class ResponseFunction(IntEnum):
    """Function byte values returned by the inverter (request | 0x80)."""

    SERIAL = 0x85
    DATA = 0x8C
    ERRORS = 0x84
    SETTINGS = 0x96


# Operating modes reported in the live-data frame, indexed by mode value.
INVERTER_MODES: tuple[str, ...] = (
    "waiting",
    "checking",
    "normal",
    "fault",
    "permanent_fault",
    "update",
    "off_grid_waiting",
    "off_grid",
    "self_test",
    "idle",
    "standby",
)
