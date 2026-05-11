"""Unit tests for the SolaX Pocket USB protocol codec."""

from __future__ import annotations

import pytest

from aiosolax_uart.const import ControlCode, Function, ResponseFunction
from aiosolax_uart.exceptions import SolaxProtocolError
from aiosolax_uart.protocol import (
    build_register_dongle,
    build_request_data,
    build_request_serial,
    decode_frame,
    decode_live_data,
    decode_serial_response,
    encode_frame,
    is_data_response,
    is_register_echo,
    is_serial_response,
    parse_stream,
)


def test_build_register_dongle_matches_user_known_good_bytes() -> None:
    """The user's hardcoded register frame from solax.yaml round-trips byte-for-byte."""
    # AA 55 11 02 01 [SWAMTLY4ZM] [1F 04]  -- captured from the user's ESPHome YAML
    assert (
        build_register_dongle("SWAMTLY4ZM") == b"\xaa\x55\x11\x02\x01" + b"SWAMTLY4ZM" + b"\x1f\x04"
    )


def test_build_request_data_matches_known_good_bytes() -> None:
    """`AA 55 07 01 0C 13 01` is the captured live-data request."""
    assert build_request_data() == bytes.fromhex("AA5507010C1301")


def test_build_request_serial_matches_known_good_bytes() -> None:
    """`AA 55 07 01 05 0C 01` is the captured device-info request."""
    assert build_request_serial() == bytes.fromhex("AA550701050C01")


def test_register_dongle_rejects_wrong_length() -> None:
    with pytest.raises(SolaxProtocolError, match="must be"):
        build_register_dongle("TOOSHORT")


def test_decode_frame_rejects_bad_header() -> None:
    bad = bytearray(build_request_data())
    bad[0] = 0xBB
    with pytest.raises(SolaxProtocolError, match="header"):
        decode_frame(bytes(bad))


def test_decode_frame_rejects_bad_checksum() -> None:
    bad = bytearray(build_request_data())
    bad[-1] ^= 0xFF
    with pytest.raises(SolaxProtocolError, match="checksum"):
        decode_frame(bytes(bad))


def test_decode_frame_rejects_truncated_header() -> None:
    with pytest.raises(SolaxProtocolError, match="too short"):
        decode_frame(b"\xaa\x55")


def test_decode_frame_rejects_length_mismatch() -> None:
    bad = bytearray(build_request_data())
    bad[2] = 0x99  # claim 0x99 bytes total but the frame is shorter
    with pytest.raises(SolaxProtocolError, match="Length mismatch"):
        decode_frame(bytes(bad))


def test_parse_stream_extracts_a_frame_and_remainder() -> None:
    a = build_request_data()
    b = build_request_serial()
    stream = b"\x00\x00\xff" + a + b[:5]
    extracted, remainder = parse_stream(stream)
    assert extracted == a
    assert remainder == b[:5]
    extracted2, remainder2 = parse_stream(remainder)
    assert extracted2 is None
    assert remainder2 == b[:5]


def test_parse_stream_empty() -> None:
    assert parse_stream(b"") == (None, b"")


def test_parse_stream_keeps_potential_header_byte() -> None:
    extracted, remainder = parse_stream(b"\x12\x34\xaa")
    assert extracted is None
    assert remainder == b"\xaa"


def test_parse_stream_two_byte_partial_header_returns_remainder_intact() -> None:
    """A buffer with just the header bytes but no length byte yet stays buffered."""
    extracted, remainder = parse_stream(b"\xaa\x55")
    assert extracted is None
    assert remainder == b"\xaa\x55"


def test_parse_stream_drops_bogus_header_with_too_small_size_byte() -> None:
    """If the size byte is below MIN_FRAME_LEN it can't be a valid frame — skip the header."""
    # AA 55 followed by size=3 (impossibly small) then noise — drop the bad AA 55.
    extracted, remainder = parse_stream(b"\xaa\x55\x03\xff\xff\xff")
    assert extracted is None
    # remainder keeps bytes from index 2 onwards (the bogus AA 55 header is dropped)
    assert remainder == b"\x03\xff\xff\xff"


def test_build_register_dongle_accepts_raw_bytes() -> None:
    """The function also accepts a pre-encoded bytes serial."""
    frame_str = build_register_dongle("SWAMTLY4ZM")
    frame_bytes = build_register_dongle(b"SWAMTLY4ZM")
    assert frame_str == frame_bytes


def _build_live_payload(
    *, signed_grid: int = -669, pv1_power: int = 0, pv2_power: int = 0
) -> bytes:
    """Reproduce a captured live-data payload from a real grid-tie inverter, with overrides."""
    payload = bytearray(200)
    # PV1/PV2 instantaneous power at offsets 14/16 (uint16 LE)
    payload[14:16] = pv1_power.to_bytes(2, "little")
    payload[16:18] = pv2_power.to_bytes(2, "little")
    # Total Generated Energy at offset 22 (uint32 LE) = 0x00055D9E = 351,134 → 35,113.4 kWh
    payload[22:26] = (351_134).to_bytes(4, "little")
    # Runtime Total at offset 82 (uint32 LE) = 0x000043BC = 17340 hours
    payload[82:86] = (17_340).to_bytes(4, "little")
    # CT-clamp signed grid power at offset 96 (int32 LE)
    payload[96:100] = signed_grid.to_bytes(4, "little", signed=True)
    # Total Export Energy at offset 100 (uint32 LE) = 2,564,450 → 25,644.50 kWh
    payload[100:104] = (2_564_450).to_bytes(4, "little")
    # Total Import Energy at offset 104 (uint32 LE) = 4,169,188 → 41,691.88 kWh
    payload[104:108] = (4_169_188).to_bytes(4, "little")
    return bytes(payload)


def test_decode_real_x1_live_frame() -> None:
    """Round-trip the captured live-data frame through encode + decode."""
    frame = encode_frame(ControlCode.QUERY, ResponseFunction.DATA, _build_live_payload())
    decoded = decode_frame(frame)
    assert decoded.control == ControlCode.QUERY
    assert decoded.function == ResponseFunction.DATA
    live = decode_live_data(decoded.payload)

    # Inverter at night — AC values all zero, but lifetime totals real.
    assert live.grid_voltage == 0
    assert live.grid_power == 0
    assert live.mode_name == "waiting"
    assert live.energy_total == pytest.approx(35113.4, rel=1e-4)
    assert live.runtime_total == 17340

    # Importing 669 W: imported_power=669, exported_power=0, self_consumed=0 (no PV).
    assert live.import_power == 669
    assert live.export_power == 0
    assert live.self_consumption_power == 0
    assert live.total_export_energy == pytest.approx(25_644.50, rel=1e-4)
    assert live.total_import_energy == pytest.approx(41_691.88, rel=1e-4)


def test_live_data_exporting_to_grid() -> None:
    """When exporting: export_power positive, import_power 0, self_consumption = pv - export."""
    # PV producing 2000 W, house using 1500 W → 500 W exported.
    payload = _build_live_payload(signed_grid=500, pv1_power=1200, pv2_power=800)
    live = decode_live_data(payload)
    assert live.export_power == 500
    assert live.import_power == 0
    assert live.self_consumption_power == 1500  # 1200 + 800 - 500


def test_live_data_self_consumption_clamps_at_zero() -> None:
    """If somehow exported > pv (rounding glitch), self_consumption clamps at 0."""
    payload = _build_live_payload(signed_grid=1000, pv1_power=400, pv2_power=300)
    live = decode_live_data(payload)
    # Math says 400+300-1000 = -300; clamped to 0.
    assert live.self_consumption_power == 0


def test_live_data_no_ct_clamp_short_payload() -> None:
    """A pre-CT firmware response leaves all CT-derived fields as None."""
    live = decode_live_data(bytes(100))
    assert live.import_power is None
    assert live.export_power is None
    assert live.self_consumption_power is None
    assert live.total_import_energy is None
    assert live.total_export_energy is None


def test_hybrid_decoder_runs_when_payload_long_enough() -> None:
    """A >=210-byte payload activates the hybrid decoder for battery / EPS / RTC."""
    payload = bytearray(220)
    # Offsets per xdubx/Solax-Pocket-USB-reverse-engineering issue #4:
    payload[33:35] = (4500).to_bytes(2, "little")  # battery 45.00 V
    payload[41:43] = (67).to_bytes(2, "little")  # SoC 67 %
    payload[51] = 95  # SoH ×0.1 = 9.5
    payload[61:63] = (250).to_bytes(2, "little")  # EPS power 250 W
    payload[63:65] = (2300).to_bytes(2, "little")  # EPS voltage 230.0 V
    # RTC (203-208: sec, min, hr, day, mo, yr-2000)
    payload[203] = 13
    payload[204] = 8
    payload[205] = 14
    payload[206] = 6
    payload[207] = 5
    payload[208] = 26  # → 2026
    live = decode_live_data(bytes(payload))
    assert live.battery_voltage == pytest.approx(45.0)
    assert live.battery_soc == 67
    assert live.battery_soh == pytest.approx(9.5)
    assert live.eps_power == 250
    assert live.eps_voltage == pytest.approx(230.0)
    assert live.inverter_rtc == (2026, 5, 6, 14, 8, 13)


def test_grid_tie_decoder_keeps_hybrid_fields_none() -> None:
    """A grid-tie 200-byte payload leaves all hybrid fields None."""
    live = decode_live_data(bytes(200))
    assert live.battery_voltage is None
    assert live.battery_soc is None
    assert live.eps_power is None
    assert live.inverter_rtc is None


def test_decode_live_data_too_short() -> None:
    with pytest.raises(SolaxProtocolError, match="at least 84"):
        decode_live_data(b"\x00" * 30)


def test_decode_serial_response() -> None:
    """The real captured serial response decodes the inverter + dongle fields."""
    payload = bytearray(40)
    payload[0:14] = b"XB3250H9107611"
    payload[14:28] = b" " * 14
    payload[28:30] = (5000).to_bytes(2, "little")  # model code 0x1388
    payload[30:38] = b"SWAMTLY4"
    payload[38:40] = (4).to_bytes(2, "little")
    info = decode_serial_response(bytes(payload))
    assert info.inverter_serial == "XB3250H9107611"
    assert info.inverter_model_code == 5000
    assert info.inverter_model_type == 4
    assert info.pocket_dongle_serial == "SWAMTLY4"


def test_decode_serial_response_too_short() -> None:
    with pytest.raises(SolaxProtocolError, match="40 bytes"):
        decode_serial_response(b"\x00" * 10)


def test_predicate_helpers() -> None:
    """Helper predicates classify decoded frames correctly."""
    register_echo = decode_frame(build_register_dongle("ABCDEFGHIJ"))
    assert is_register_echo(register_echo)
    assert not is_data_response(register_echo)
    assert not is_serial_response(register_echo)


def test_encode_frame_rejects_oversized() -> None:
    with pytest.raises(SolaxProtocolError, match="too large"):
        encode_frame(ControlCode.QUERY, Function.REQUEST_DATA, b"\x00" * 252)
