"""Tests for SolaxClient using a mocked serialx transport."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest

from aiosolax_uart import (
    SolaxClient,
    SolaxConnectionError,
    SolaxRegistrationError,
)
from aiosolax_uart.const import ControlCode, ResponseFunction
from aiosolax_uart.protocol import decode_frame, encode_frame


def _serial_response_payload() -> bytes:
    payload = bytearray(40)
    payload[0:14] = b"XB3250H9107611"
    payload[14:28] = b" " * 14
    payload[28:30] = (5000).to_bytes(2, "little")
    payload[30:38] = b"AIOSOLAX"
    payload[38:40] = (4).to_bytes(2, "little")
    return bytes(payload)


def _live_data_payload() -> bytes:
    payload = bytearray(200)
    # AC 230.1V × 0.1 unit
    payload[0:2] = (2301).to_bytes(2, "little")
    # Mode 2 = normal
    payload[20:22] = (2).to_bytes(2, "little")
    # eTotal raw 0x00055D9E → 35113.4 kWh
    payload[22:26] = (351_134).to_bytes(4, "little")
    return bytes(payload)


class FakeWriter:
    """Minimal serialx.SerialStreamWriter substitute."""

    def __init__(self, sink: asyncio.Queue[bytes]) -> None:
        self._sink = sink

    def write(self, data: bytes) -> None:
        self._sink.put_nowait(data)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        await asyncio.sleep(0)


class FakeInverter:
    """Replays canned responses to client writes."""

    def __init__(self, reader: asyncio.StreamReader, sink: asyncio.Queue[bytes]) -> None:
        self._reader = reader
        self._sink = sink
        self._task: asyncio.Task[Any] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            data = await self._sink.get()
            decoded = decode_frame(data)
            if decoded.control == ControlCode.REGISTER:
                # Echo the registration frame back unchanged, no checksum
                # verification is done on the response side per the spec.
                self._reader.feed_data(data)
            elif decoded.control == ControlCode.QUERY and decoded.function == 0x05:
                self._reader.feed_data(
                    encode_frame(
                        ControlCode.QUERY, ResponseFunction.SERIAL, _serial_response_payload()
                    )
                )
            elif decoded.control == ControlCode.QUERY and decoded.function == 0x0C:
                self._reader.feed_data(
                    encode_frame(ControlCode.QUERY, ResponseFunction.DATA, _live_data_payload())
                )


@pytest.fixture
async def fake_serial() -> AsyncIterator[None]:
    reader = asyncio.StreamReader()
    sink: asyncio.Queue[bytes] = asyncio.Queue()
    writer = FakeWriter(sink)
    inverter = FakeInverter(reader, sink)

    async def fake_open(*_args: Any, **_kwargs: Any) -> tuple[asyncio.StreamReader, FakeWriter]:
        inverter.start()
        return reader, writer

    with patch("aiosolax_uart.client.serialx.open_serial_connection", side_effect=fake_open):
        yield

    await inverter.stop()


async def test_register_then_query(fake_serial: None) -> None:
    """The full register → device-info → live-data flow returns parsed values."""
    async with SolaxClient("/dev/null", dongle_serial="AIOSOLAX01") as client:
        info = await client.get_device_info()
        assert info.inverter_serial == "XB3250H9107611"
        assert info.pocket_dongle_serial == "AIOSOLAX"

        live = await client.get_live_data()
        assert live.mode_name == "normal"
        assert live.grid_voltage == pytest.approx(230.1)


async def test_connect_propagates_serial_open_failure() -> None:
    async def fake_open(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("device not found")

    with patch("aiosolax_uart.client.serialx.open_serial_connection", side_effect=fake_open):
        with pytest.raises(SolaxConnectionError):
            await SolaxClient("/dev/null", dongle_serial="AIOSOLAX01").connect()


async def test_register_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the inverter never echoes the register frame, raise SolaxRegistrationError."""
    reader = asyncio.StreamReader()
    sink: asyncio.Queue[bytes] = asyncio.Queue()
    writer = FakeWriter(sink)

    async def fake_open(*_args: Any, **_kwargs: Any) -> tuple[asyncio.StreamReader, FakeWriter]:
        return reader, writer

    monkeypatch.setattr("aiosolax_uart.client.REGISTRATION_TIMEOUT", 0.05)
    with patch("aiosolax_uart.client.serialx.open_serial_connection", side_effect=fake_open):
        with pytest.raises(SolaxRegistrationError):
            await SolaxClient("/dev/null", dongle_serial="AIOSOLAX01").connect()


def test_constructor_rejects_wrong_dongle_serial_length() -> None:
    with pytest.raises(ValueError, match="must be"):
        SolaxClient("/dev/null", dongle_serial="TOOSHORT")


async def test_close_swallows_wait_closed_exception(fake_serial: None) -> None:
    """If wait_closed() raises (e.g. socket already half-shut), close() recovers."""
    async with SolaxClient("/dev/null", dongle_serial="AIOSOLAX01") as client:
        assert client._writer is not None

        # Force wait_closed to raise — close() must swallow it.
        async def boom() -> None:
            raise RuntimeError("already gone")

        client._writer.wait_closed = boom  # type: ignore[assignment,method-assign]
        # No exception escapes close(); writer/reader are still cleared.
    assert client._writer is None
    assert client._reader is None


async def test_send_when_not_connected_raises() -> None:
    """Calling get_device_info() on a never-connected client raises ConnectionError."""
    client = SolaxClient("/dev/null", dongle_serial="AIOSOLAX01")
    with pytest.raises(SolaxConnectionError, match="Not connected"):
        await client.get_device_info()


async def test_send_serial_write_failure_raises(fake_serial: None) -> None:
    """If the writer's drain() raises, _send wraps it in SolaxConnectionError."""
    async with SolaxClient("/dev/null", dongle_serial="AIOSOLAX01") as client:

        async def boom() -> None:
            raise OSError("hung up")

        client._writer.drain = boom  # type: ignore[assignment,method-assign]
        with pytest.raises(SolaxConnectionError, match="write failed"):
            await client.get_device_info()


async def test_await_frame_timeout_inside_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once registered, a query with no response surfaces as TimeoutError."""
    reader = asyncio.StreamReader()
    sink: asyncio.Queue[bytes] = asyncio.Queue()
    writer = FakeWriter(sink)
    background_tasks: list[asyncio.Task[None]] = []

    consumed = asyncio.Event()

    async def fake_open(*_args: Any, **_kwargs: Any) -> tuple[asyncio.StreamReader, FakeWriter]:
        # Echo the register frame so connect() succeeds, then go silent.
        async def replay_register() -> None:
            data = await sink.get()
            reader.feed_data(data)  # register echo
            consumed.set()
            # Drain subsequent writes without responding
            while True:
                await sink.get()

        # Stash the task on the fixture's outer scope so it isn't GC'd.
        background_tasks.append(asyncio.create_task(replay_register()))
        return reader, writer

    monkeypatch.setattr("aiosolax_uart.client.QUERY_TIMEOUT", 0.05)
    with patch("aiosolax_uart.client.serialx.open_serial_connection", side_effect=fake_open):
        async with SolaxClient("/dev/null", dongle_serial="AIOSOLAX01") as client:
            await consumed.wait()
            with pytest.raises(TimeoutError):
                await client.get_device_info()


async def test_await_frame_skips_malformed_then_matches(fake_serial: None) -> None:
    """_await_frame discards a malformed frame and continues to the real response."""
    async with SolaxClient("/dev/null", dongle_serial="AIOSOLAX01") as client:
        assert client._reader is not None
        # Inject a malformed-checksum frame ahead of a real serial-response.
        bad = bytearray(
            encode_frame(ControlCode.QUERY, ResponseFunction.SERIAL, _serial_response_payload())
        )
        bad[-1] ^= 0xFF  # break checksum
        client._reader.feed_data(bytes(bad))
        # Real query → fake inverter responds with a valid serial frame.
        info = await client.get_device_info()
        assert info.inverter_serial == "XB3250H9107611"


async def test_await_frame_ignores_unrelated_frame(fake_serial: None) -> None:
    """_await_frame discards a valid but irrelevant frame and waits for the right one."""
    async with SolaxClient("/dev/null", dongle_serial="AIOSOLAX01") as client:
        assert client._reader is not None
        # Inject a valid data response BEFORE the request would normally arrive.
        client._reader.feed_data(
            encode_frame(ControlCode.QUERY, ResponseFunction.DATA, _live_data_payload())
        )
        # Now do a serial request — the data response gets discarded, fake inverter
        # responds with a serial response, which the client returns.
        info = await client.get_device_info()
        assert info.inverter_serial == "XB3250H9107611"


async def test_read_one_frame_handles_oserror(fake_serial: None) -> None:
    """A read() raising OSError surfaces as SolaxConnectionError."""
    async with SolaxClient("/dev/null", dongle_serial="AIOSOLAX01") as client:
        assert client._reader is not None

        async def boom(_n: int) -> bytes:
            raise OSError("USB unplugged")

        client._reader.read = boom  # type: ignore[assignment,method-assign]
        with pytest.raises(SolaxConnectionError, match="read failed"):
            await client.get_device_info()


async def test_await_frame_outer_timeout_burns_through_unrelated_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If predicate never matches, the outer deadline eventually fires."""
    reader = asyncio.StreamReader()
    sink: asyncio.Queue[bytes] = asyncio.Queue()
    writer = FakeWriter(sink)
    background_tasks: list[asyncio.Task[None]] = []

    async def fake_open(*_args: Any, **_kwargs: Any) -> tuple[asyncio.StreamReader, FakeWriter]:
        # Echo the register frame so connect() succeeds, then go silent for all
        # subsequent requests.
        async def echo_register_then_silent() -> None:
            data = await sink.get()
            reader.feed_data(data)
            while True:
                await sink.get()

        background_tasks.append(asyncio.create_task(echo_register_then_silent()))
        return reader, writer

    monkeypatch.setattr("aiosolax_uart.client.QUERY_TIMEOUT", 0.05)
    with patch("aiosolax_uart.client.serialx.open_serial_connection", side_effect=fake_open):
        async with SolaxClient("/dev/null", dongle_serial="AIOSOLAX01") as client:
            # Pre-load the reader buffer with valid-but-wrong frames so the
            # predicate-mismatch loop burns through them, eventually hitting
            # the outer deadline check in _await_frame.
            unrelated = encode_frame(ControlCode.QUERY, ResponseFunction.DATA, _live_data_payload())
            for _ in range(200):
                reader.feed_data(unrelated)
            with pytest.raises(TimeoutError):
                await client.get_device_info()


async def test_read_one_frame_empty_chunk_signals_close() -> None:
    """An empty read() return means the serial port closed — raise ConnectionError.

    Uses a hand-rolled reader (not the autouse fake_serial fixture) so we can
    feed EOF cleanly without a phantom FakeInverter task running concurrently.
    """
    reader = asyncio.StreamReader()
    sink: asyncio.Queue[bytes] = asyncio.Queue()
    writer = FakeWriter(sink)
    background_tasks: list[asyncio.Task[None]] = []

    async def fake_open(*_args: Any, **_kwargs: Any) -> tuple[asyncio.StreamReader, FakeWriter]:
        # Echo back register frames so connect() completes; otherwise stay silent.
        async def echo_register() -> None:
            data = await sink.get()
            reader.feed_data(data)

        background_tasks.append(asyncio.create_task(echo_register()))
        return reader, writer

    with patch("aiosolax_uart.client.serialx.open_serial_connection", side_effect=fake_open):
        async with SolaxClient("/dev/null", dongle_serial="AIOSOLAX01") as client:
            assert client._reader is not None
            reader.feed_eof()
            with pytest.raises(SolaxConnectionError, match="closed"):
                await client.get_device_info()
