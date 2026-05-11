"""Async client for SolaX inverters via the Pocket USB protocol."""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import Self

import serialx

from .const import (
    BAUD_RATE,
    DONGLE_SERIAL_LENGTH,
)
from .exceptions import (
    SolaxConnectionError,
    SolaxProtocolError,
    SolaxRegistrationError,
)
from .models import DeviceInfo, LiveData
from .protocol import (
    DecodedFrame,
    build_register_dongle,
    build_request_data,
    build_request_serial,
    decode_frame,
    decode_live_data,
    decode_serial_response,
    is_data_response,
    is_register_echo,
    is_serial_response,
    parse_stream,
)

_LOGGER = logging.getLogger(__name__)

REGISTRATION_TIMEOUT = 5.0
QUERY_TIMEOUT = 5.0
DEFAULT_DONGLE_SERIAL = "AIOSOLAX01"


class SolaxClient:
    """Async client for a SolaX inverter speaking the Pocket USB protocol.

    Use as an async context manager. On entry the client opens the serial
    port and registers itself with the inverter using `dongle_serial`.
    """

    def __init__(
        self,
        port: str,
        *,
        dongle_serial: str = DEFAULT_DONGLE_SERIAL,
        baudrate: int = BAUD_RATE,
    ) -> None:
        """Initialise the client.

        Args:
            port: Serial device path or `esphome://...` URL.
            dongle_serial: 10-character ASCII identifier we register as.
            baudrate: Serial baud rate; defaults to the protocol's 9600.
        """
        if len(dongle_serial) != DONGLE_SERIAL_LENGTH:
            raise ValueError(f"dongle_serial must be {DONGLE_SERIAL_LENGTH} characters")
        self._port = port
        self._dongle_serial = dongle_serial
        self._baudrate = baudrate
        self._reader: asyncio.StreamReader | None = None
        self._writer: serialx.SerialStreamWriter | None = None
        self._buf = b""
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        """Open the serial port and register with the inverter."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the serial port on context-manager exit."""
        await self.close()

    async def connect(self) -> None:
        """Open the serial port and register the dongle with the inverter."""
        try:
            self._reader, self._writer = await serialx.open_serial_connection(
                url=self._port,
                baudrate=self._baudrate,
            )
        except (OSError, serialx.SerialException) as err:
            raise SolaxConnectionError(f"Could not open serial port {self._port}: {err}") from err

        try:
            await self._register()
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        """Close the serial port. Safe to call multiple times."""
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                _LOGGER.debug("Error during serial close", exc_info=True)
        self._writer = None
        self._reader = None
        self._buf = b""

    async def get_device_info(self) -> DeviceInfo:
        """Query the inverter for its serial number and model codes."""
        async with self._lock:
            await self._send(build_request_serial())
            decoded = await self._await_frame(is_serial_response, timeout=QUERY_TIMEOUT)
            return decode_serial_response(decoded.payload)

    async def get_live_data(self) -> LiveData:
        """Query the inverter for its current live measurements."""
        async with self._lock:
            await self._send(build_request_data())
            decoded = await self._await_frame(is_data_response, timeout=QUERY_TIMEOUT)
            return decode_live_data(decoded.payload)

    # ----- internals ------------------------------------------------------

    async def _register(self) -> None:
        async with self._lock:
            frame = build_register_dongle(self._dongle_serial)
            await self._send(frame)
            try:
                await self._await_frame(
                    is_register_echo,
                    timeout=REGISTRATION_TIMEOUT,
                    verify_checksum=False,
                )
            except TimeoutError as err:
                raise SolaxRegistrationError(
                    f"Inverter did not acknowledge registration on {self._port}"
                ) from err

    async def _send(self, frame: bytes) -> None:
        if self._writer is None:
            raise SolaxConnectionError("Not connected")
        try:
            self._writer.write(frame)
            await self._writer.drain()
        except (OSError, serialx.SerialException) as err:
            raise SolaxConnectionError(f"Serial write failed: {err}") from err

    async def _await_frame(
        self,
        predicate,  # type: ignore[no-untyped-def]
        *,
        timeout: float,
        verify_checksum: bool = True,
    ) -> DecodedFrame:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if (
                remaining <= 0
            ):  # pragma: no cover - asyncio.wait_for in _read_one_frame races us to the deadline
                raise TimeoutError("Timed out waiting for SolaX frame")
            frame_bytes = await self._read_one_frame(timeout=remaining)
            try:
                decoded = decode_frame(frame_bytes, verify_checksum=verify_checksum)
            except SolaxProtocolError:
                _LOGGER.debug("Discarding malformed frame: %s", frame_bytes.hex())
                continue
            if predicate(decoded):
                return decoded
            _LOGGER.debug(
                "Ignoring frame ctrl=0x%02x func=0x%02x", decoded.control, decoded.function
            )

    async def _read_one_frame(self, *, timeout: float) -> bytes:
        if (
            self._reader is None
        ):  # pragma: no cover - defensive; _send() is checked first under the lock
            raise SolaxConnectionError("Not connected")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            frame, self._buf = parse_stream(self._buf)
            if frame is not None:
                return frame
            remaining = deadline - loop.time()
            if remaining <= 0:  # pragma: no cover - asyncio.wait_for below races us to the timeout
                raise TimeoutError("Timed out reading frame")
            try:
                chunk = await asyncio.wait_for(self._reader.read(256), timeout=remaining)
            except TimeoutError:
                raise
            except (OSError, serialx.SerialException) as err:
                raise SolaxConnectionError(f"Serial read failed: {err}") from err
            if not chunk:
                raise SolaxConnectionError("Serial connection closed")
            self._buf += chunk
