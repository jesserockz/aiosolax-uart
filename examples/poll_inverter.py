"""Minimal example: connect to a SolaX inverter and poll live data.

Run with:

    uv run examples/poll_inverter.py /dev/ttyUSB0

or against an ESPHome serial proxy:

    uv run examples/poll_inverter.py 'esphome://10.0.0.5/?port_name=UART%201&noise_psk=...'
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiosolax_uart import SolaxClient


async def main(port: str) -> None:
    """Open the inverter, print device info, and stream live data."""
    async with SolaxClient(port) as client:
        info = await client.get_device_info()
        print(f"Connected to {info.model.name} (serial {info.inverter_serial})")
        print(f"  Registered dongle:  {info.pocket_dongle_serial}")
        print(f"  Inverter model code: {info.inverter_model_code}")
        print()

        while True:
            live = await client.get_live_data()
            line = (
                f"mode={live.mode_name:<10}  "
                f"AC {live.grid_voltage:>5.1f}V {live.grid_power:>5d}W  "
                f"PV1 {live.pv1_voltage:>5.1f}V/{live.pv1_current:>4.1f}A  "
                f"PV2 {live.pv2_voltage:>5.1f}V/{live.pv2_current:>4.1f}A  "
                f"today={live.energy_today:>5.1f}kWh  total={live.energy_total:>7.1f}kWh"
            )
            if live.import_power is not None and live.export_power is not None:
                line += (
                    f"  imp={live.import_power:>4d}W  "
                    f"exp={live.export_power:>4d}W  "
                    f"self={live.self_consumption_power:>4d}W"
                )
            print(line, flush=True)
            await asyncio.sleep(2)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <serial-port-or-esphome-url>", file=sys.stderr)
        sys.exit(1)
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main(sys.argv[1]))
    except KeyboardInterrupt:
        pass
