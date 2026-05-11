"""Wire-protocol encoding and decoding for the SolaX Pocket USB protocol.

Frame format: ``AA 55 [size] [ctrl] [func] [payload...] [chk_lo chk_hi]``
- bytes 0-1: header ``AA 55``
- byte 2:    total frame size (header + ctrl + func + payload + checksum)
- byte 3:    control code
- byte 4:    function code
- bytes 5..(size-3): payload
- bytes (size-2)..(size-1): 16-bit little-endian additive checksum over all
  preceding bytes

Reverse-engineered by xdubx:
https://github.com/xdubx/Solax-Pocket-USB-reverse-engineering
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .const import (
    DONGLE_SERIAL_LENGTH,
    HEADER,
    INVERTER_MODES,
    ControlCode,
    Function,
    ResponseFunction,
)
from .exceptions import SolaxProtocolError
from .models import DeviceInfo, InverterFamily, LiveData, lookup_model

HEADER_LEN = 5  # AA 55 + size + ctrl + func
CHECKSUM_LEN = 2
MIN_FRAME_LEN = HEADER_LEN + CHECKSUM_LEN  # 7-byte minimum frame


def _checksum(data: bytes) -> int:
    """Compute the 16-bit little-endian additive checksum."""
    return sum(data) & 0xFFFF


def encode_frame(control: int, function: int, payload: bytes = b"") -> bytes:
    """Encode a frame with header, size byte, control, function, payload, checksum."""
    total_size = HEADER_LEN + len(payload) + CHECKSUM_LEN
    if total_size > 0xFF:
        raise SolaxProtocolError(f"Frame too large: {total_size} bytes")
    body = HEADER + bytes((total_size, int(control), int(function))) + payload
    checksum = _checksum(body)
    return body + struct.pack("<H", checksum)


@dataclass(frozen=True, slots=True)
class DecodedFrame:
    """A frame split into its component fields after decoding."""

    control: int
    function: int
    payload: bytes


def decode_frame(frame: bytes, *, verify_checksum: bool = True) -> DecodedFrame:
    """Decode and validate a complete frame.

    The register-dongle response is observed to omit the checksum on some
    inverters; pass ``verify_checksum=False`` for that one case.
    """
    if len(frame) < MIN_FRAME_LEN:
        raise SolaxProtocolError(f"Frame too short: {len(frame)} bytes")
    if frame[:2] != HEADER:
        raise SolaxProtocolError(f"Bad header: {frame[:2].hex()}")
    total_size = frame[2]
    if len(frame) != total_size:
        raise SolaxProtocolError(f"Length mismatch: header says {total_size}, got {len(frame)}")
    if verify_checksum:
        body = frame[: total_size - CHECKSUM_LEN]
        expected = _checksum(body)
        actual = struct.unpack("<H", frame[-CHECKSUM_LEN:])[0]
        if expected != actual:
            raise SolaxProtocolError(f"Bad checksum: expected 0x{expected:04x}, got 0x{actual:04x}")
    return DecodedFrame(
        control=frame[3],
        function=frame[4],
        payload=frame[HEADER_LEN : total_size - CHECKSUM_LEN],
    )


def parse_stream(buf: bytes) -> tuple[bytes | None, bytes]:
    """Try to extract the next complete frame from a streaming buffer.

    Returns ``(frame, remainder)`` where ``frame`` is None if no complete frame
    is yet available. Skips garbage bytes before the header.
    """
    idx = buf.find(HEADER)
    if idx == -1:
        return None, buf[-1:] if buf else b""
    if idx > 0:
        buf = buf[idx:]
    if len(buf) < 3:
        return None, buf
    total_size = buf[2]
    if total_size < MIN_FRAME_LEN:
        # Drop the bogus header and try again past it
        return None, buf[2:]
    if len(buf) < total_size:
        return None, buf
    return buf[:total_size], buf[total_size:]


# ----- request builders ---------------------------------------------------


def build_register_dongle(dongle_serial: str | bytes) -> bytes:
    """Frame that announces our dongle serial to the inverter.

    Most inverters accept any 10-character ASCII string as the dongle
    serial — it's an arbitrary identifier, not the inverter's serial.
    """
    if isinstance(dongle_serial, str):
        payload = dongle_serial.encode("ascii")
    else:
        payload = dongle_serial
    if len(payload) != DONGLE_SERIAL_LENGTH:
        raise SolaxProtocolError(
            f"Dongle serial must be {DONGLE_SERIAL_LENGTH} characters, got {len(payload)}"
        )
    return encode_frame(ControlCode.REGISTER, Function.REGISTER_DONGLE, payload)


def build_request_serial() -> bytes:
    """Request the inverter's serial number and model codes."""
    return encode_frame(ControlCode.QUERY, Function.REQUEST_SERIAL)


def build_request_data() -> bytes:
    """Request the live-data frame."""
    return encode_frame(ControlCode.QUERY, Function.REQUEST_DATA)


# ----- response decoders --------------------------------------------------


def is_register_echo(decoded: DecodedFrame) -> bool:
    """Return True if `decoded` is the inverter's echo of a register frame."""
    return decoded.control == ControlCode.REGISTER and decoded.function == Function.REGISTER_DONGLE


def is_data_response(decoded: DecodedFrame) -> bool:
    """Return True if `decoded` is a live-data response."""
    return decoded.control == ControlCode.QUERY and decoded.function == ResponseFunction.DATA


def is_serial_response(decoded: DecodedFrame) -> bool:
    """Return True if `decoded` is a serial-numbers response."""
    return decoded.control == ControlCode.QUERY and decoded.function == ResponseFunction.SERIAL


def decode_serial_response(payload: bytes) -> DeviceInfo:
    """Decode the 40-byte serial-numbers response payload."""
    if len(payload) < 40:
        raise SolaxProtocolError(f"Serial-response payload must be 40 bytes, got {len(payload)}")

    def _ascii(start: int, length: int) -> str:
        return payload[start : start + length].decode("ascii", errors="replace").strip()

    return DeviceInfo(
        inverter_serial=_ascii(0, 14),
        # offset 14..28 is reserved/padding
        inverter_model_code=_u16(payload, 28),
        pocket_dongle_serial=_ascii(30, 8),
        inverter_model_type=_u16(payload, 38),
    )


def _u16(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<H", payload, offset)[0]


def _i32(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<i", payload, offset)[0]


def _u32(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<I", payload, offset)[0]


def decode_live_data(payload: bytes, *, model_code: int | None = None) -> LiveData:
    """Decode the live-data response payload.

    Dispatches to a per-family decoder. If ``model_code`` resolves to a hybrid
    family the hybrid decoder is used; otherwise the grid-tie decoder runs.
    Heuristic fallback: any payload >= 210 bytes is treated as a hybrid
    response (it cannot fit the 200-byte grid-tie layout).
    """
    if len(payload) < 84:
        raise SolaxProtocolError(f"Live-data payload must be at least 84 bytes, got {len(payload)}")

    family = lookup_model(model_code).family if model_code is not None else None
    use_hybrid_extras = (
        family in (InverterFamily.X1_HYBRID, InverterFamily.X3_HYBRID) or len(payload) >= 210
    )

    mode = _u16(payload, 20)
    raw_runtime = _u32(payload, 82) if len(payload) >= 86 else 0
    pv1_power = _u16(payload, 14)
    pv2_power = _u16(payload, 16)

    extras: dict[str, object] = {}
    if len(payload) >= 108:
        # CT-clamp: signed grid-feed. Positive = exporting, negative = importing.
        # Split into two non-negative sensors so each can be cleanly integrated.
        signed_grid = _i32(payload, 96)
        export_power = max(0, signed_grid)
        import_power = max(0, -signed_grid)
        extras["export_power"] = export_power
        extras["import_power"] = import_power
        extras["self_consumption_power"] = max(0, pv1_power + pv2_power - export_power)
        # Lifetime totals are 0.01 kWh per count. Verified against the HTTP
        # integration's reading on the same inverter — offset 104 is import,
        # 100 is export (opposite of what you'd guess from the field order).
        extras["total_export_energy"] = _u32(payload, 100) * 0.01
        extras["total_import_energy"] = _u32(payload, 104) * 0.01

    if use_hybrid_extras:
        extras.update(_decode_hybrid_extras(payload))

    return LiveData(
        grid_voltage=_u16(payload, 0) * 0.1,
        grid_current=_u16(payload, 2) * 0.1,
        grid_power=_u16(payload, 4),
        pv1_voltage=_u16(payload, 6) * 0.1,
        pv2_voltage=_u16(payload, 8) * 0.1,
        pv1_current=_u16(payload, 10) * 0.1,
        pv2_current=_u16(payload, 12) * 0.1,
        pv1_power=pv1_power,
        pv2_power=pv2_power,
        grid_frequency=_u16(payload, 18) * 0.01,
        mode=mode,
        mode_name=INVERTER_MODES[mode] if mode < len(INVERTER_MODES) else "unknown",
        energy_total=_u32(payload, 22) * 0.1,
        energy_today=_u16(payload, 26) * 0.1,
        temperature=_u16(payload, 78),
        runtime_total=raw_runtime,
        **extras,  # type: ignore[arg-type]
    )


def _decode_hybrid_extras(payload: bytes) -> dict[str, object]:
    """Best-effort decode of hybrid-only fields.

    Offsets sourced from xdubx/Solax-Pocket-USB-reverse-engineering issue #4
    (March 2023, contributor 70p4z). **Not verified against real hardware**
    by this library's authors — treat all hybrid output as preliminary, and
    please open an issue if you can confirm or correct offsets against your
    own inverter.
    """
    out: dict[str, object] = {}

    if len(payload) >= 43:
        # Battery block: 33 voltage*0.01V, 37 power int16 W, 39 BMS temp, 41 SoC %
        out["battery_voltage"] = _u16(payload, 33) * 0.01
        out["battery_power"] = struct.unpack_from("<h", payload, 37)[0]
        out["battery_temperature"] = _u16(payload, 39)
        out["battery_soc"] = _u16(payload, 41)

    if len(payload) >= 69:
        # EPS block: 61 power W, 63 voltage*0.1V, 65 current*0.1A, 67 freq*0.01Hz
        out["eps_power"] = _u16(payload, 61)
        out["eps_voltage"] = _u16(payload, 63) * 0.1
        out["eps_current"] = _u16(payload, 65) * 0.1
        out["eps_frequency"] = _u16(payload, 67) * 0.01

    if len(payload) >= 95:
        out["battery_max_voltage"] = _u16(payload, 87) * 0.1
        out["battery_min_voltage"] = _u16(payload, 89) * 0.1
        out["battery_max_charge_current"] = _u16(payload, 91) * 0.1
        out["battery_max_discharge_current"] = _u16(payload, 93) * 0.1

    if len(payload) >= 52:
        # SoH is uint8 at offset 51, ×0.1 per the contributor.
        out["battery_soh"] = payload[51] / 10.0

    if len(payload) >= 209:
        # RTC block: 203 sec, 204 min, 205 hr, 206 day, 207 mo, 208 yr-2000.
        out["inverter_rtc"] = (
            2000 + payload[208],
            payload[207],
            payload[206],
            payload[205],
            payload[204],
            payload[203],
        )

    return out
