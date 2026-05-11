# aiosolax-uart

[![PyPI version](https://img.shields.io/pypi/v/aiosolax-uart.svg)](https://pypi.org/project/aiosolax-uart/)
[![Python versions](https://img.shields.io/pypi/pyversions/aiosolax-uart.svg)](https://pypi.org/project/aiosolax-uart/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Test](https://github.com/jesserockz/aiosolax-uart/actions/workflows/test.yml/badge.svg)](https://github.com/jesserockz/aiosolax-uart/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/jesserockz/aiosolax-uart/graph/badge.svg)](https://codecov.io/gh/jesserockz/aiosolax-uart)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

Async Python library to read SolaX inverters over the **Pocket USB protocol** — the byte-level protocol that the SolaX Pocket WiFi / Pocket USB dongle speaks. Any inverter that accepts a Pocket dongle should be reachable with this library, whether the user connects a real dongle or replaces it with a USB-to-TTL adapter (CP2102, CH340, FT232, …) or an ESPHome serial proxy.

The wire protocol is `AA 55` framing at 9600 baud, 8N1. Originally reverse-engineered by [xdubx](https://github.com/xdubx/Solax-Pocket-USB-reverse-engineering); hybrid-inverter extensions contributed by [70p4z](https://github.com/xdubx/Solax-Pocket-USB-reverse-engineering/issues/4).

## Install

```bash
pip install aiosolax-uart
```

## Quickstart

```python
import asyncio
from aiosolax_uart import SolaxClient

async def main() -> None:
    async with SolaxClient("/dev/ttyUSB0") as client:
        info = await client.get_device_info()
        print(f"Connected: {info.model.name} (serial {info.inverter_serial})")

        live = await client.get_live_data()
        print(f"AC power: {live.grid_power} W, today: {live.energy_today} kWh")
        if live.import_power is not None:
            print(
                f"House grid: imp={live.import_power}W "
                f"exp={live.export_power}W self={live.self_consumption_power}W"
            )
        if live.battery_soc is not None:
            print(f"Battery: {live.battery_soc}% @ {live.battery_voltage}V")

asyncio.run(main())
```

The library also works against an [ESPHome serial proxy](https://esphome.io/components/serial_proxy.html) — pass an `esphome://host[:port]/?port_name=...&noise_psk=...` URL in place of `/dev/ttyUSB0`.

## Supported inverters

The library handles two payload families. Which fields are populated on a given inverter depends on what that inverter actually reports.

| Family | Models | Status |
|---|---|---|
| X1 grid-tie | X1 Mini (G2/G3), X1 Air, X1 Boost (G3.3/G4), X1 Smart | **Verified** (X1 with CT clamp, May 2026) |
| X1 Hybrid | X1 Hybrid G3 / G4.1+ | Decoder present, **unverified** — needs hardware testers |
| X3 grid-tie | X3 Mega G2, X3 Mic/Pro G2, X3 Forth | Same wire protocol, **unverified** |
| X3 Hybrid | X3 Hybrid G2 / G4.2+ | Decoder present, **unverified** — needs hardware testers |

If you can run `await client.get_device_info()` against your inverter and get a sensible response, please open an issue with the output so the model code can be added to the [`MODELS` registry](src/aiosolax_uart/models.py).

## API

### `SolaxClient`

- `SolaxClient(port: str, *, dongle_serial: str = "AIOSOLAX01", baudrate: int = 9600)`
- `async connect() -> None` — open serial, register with the inverter
- `async close() -> None`
- `async get_device_info() -> DeviceInfo` — inverter serial, model code, dongle serial. Cached for use by `get_live_data()`.
- `async get_live_data() -> LiveData` — instantaneous values + lifetime energy totals. Dispatches to the right decoder using the cached model code.
- Use as `async with SolaxClient(...) as client:` to handle setup/teardown.

### Data models

- [`DeviceInfo`](src/aiosolax_uart/models.py) — static device info plus a `.model` property that looks up the entry in `MODELS`.
- [`LiveData`](src/aiosolax_uart/models.py) — every field that any inverter family can report. Common fields (AC, PV, temperature, energy_total, energy_today, runtime) are always populated; CT, battery, EPS and RTC fields are `None` when not available.

### Model registry

```python
from aiosolax_uart import MODELS, lookup_model

MODELS[5000]  # InverterModel(code=5000, name='X1 (5kW)', family=InverterFamily.X1_GRID_TIE)
lookup_model(0xFFFF)  # InverterModel(code=65535, name='Unknown (65535)', family=InverterFamily.UNKNOWN)
```

## Protocol reference

Frame layout: `AA 55 [total_size] [ctrl] [func] [payload...] [chk_lo chk_hi]` with a 16-bit little-endian additive checksum over all preceding bytes.

| Direction | ctrl | func | Description |
|---|---|---|---|
| Host → | 0x02 | 0x01 | Register dongle (10-char ASCII serial) |
| Host → | 0x01 | 0x05 | Read inverter serial / model code |
| Inv ← | 0x01 | 0x85 | Serial response (40-byte payload) |
| Host → | 0x01 | 0x0C | Read live data |
| Inv ← | 0x01 | 0x8C | Live-data response (200 / 210+ bytes depending on family) |

The handshake is: open serial → broadcast register frame → wait for the inverter to echo it back → poll live data on a cadence.

## Development

```bash
uv sync
uv run pytest
```

## Contributing

If your inverter isn't in the `MODELS` registry yet:

1. Run a small script that prints `await client.get_device_info()` against your inverter.
2. Open an issue with the model code and the inverter's name (from the sticker).

If you have a hybrid inverter, the offsets in `_decode_hybrid_extras()` need verification. A 220-byte capture of `await client.get_live_data()` plus your battery's known voltage/SoC right when you took the capture would let us validate the offsets.

## License

Apache 2.0
