"""Typed models for SolaX Pocket USB protocol responses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InverterFamily(Enum):
    """Broad inverter category — controls which payload decoder we use."""

    X1_GRID_TIE = "x1_grid_tie"
    """X1 Mini / Air / Boost / Smart and similar grid-tie variants.

    Live-data payload is ~200 bytes. CT-clamp fields (offsets 96/100/104)
    are present when a clamp is wired. No battery, no EPS.
    """

    X1_HYBRID = "x1_hybrid"
    """X1 Hybrid (G3 / G4.1+) — adds battery + EPS + grid meter."""

    X3_GRID_TIE = "x3_grid_tie"
    """X3 Mega / Mic / Pro / Forth — three-phase grid-tie."""

    X3_HYBRID = "x3_hybrid"
    """X3 Hybrid (G2 / G4.2+) — three-phase with battery + EPS."""

    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class InverterModel:
    """A SolaX inverter model known to this library."""

    code: int
    name: str
    family: InverterFamily


# Registry of inverter model codes the library has been told about.
#
# The code is the 16-bit value returned in the device-info response at offset
# 28 (uint16 LE). Only entries that have been verified against real hardware
# should land here — if you have an inverter whose code is missing or wrong,
# please open an issue with the output of `get_device_info()`.
MODELS: dict[int, InverterModel] = {
    5000: InverterModel(5000, "X1 (5kW)", InverterFamily.X1_GRID_TIE),
}


def lookup_model(code: int) -> InverterModel:
    """Return the registered model for `code`, or a stub Unknown model."""
    if code in MODELS:
        return MODELS[code]
    return InverterModel(code, f"Unknown ({code})", InverterFamily.UNKNOWN)


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Static device information returned by the read-serial-numbers query."""

    inverter_serial: str
    inverter_model_code: int
    inverter_model_type: int
    pocket_dongle_serial: str

    @property
    def model(self) -> InverterModel:
        """Look up the registered model for this device."""
        return lookup_model(self.inverter_model_code)


@dataclass(frozen=True, slots=True)
class LiveData:
    """Live measurements returned by the data query.

    All fields are in human units already (V, A, W, kWh, Hz, °C, h) — values
    are scaled from the raw protocol units during decoding.

    The grid_voltage / grid_current / grid_power / grid_frequency block and
    the PV1/PV2 + temperature + energy/runtime block are reported by every
    SolaX inverter that speaks this protocol. The remaining fields are
    optional and only populated when the underlying inverter and firmware
    expose them.

    **CT-clamp fields** (X1 with CT clamp, X1-Hybrid, X3-Hybrid):
        ``import_power`` / ``export_power`` are always ≥ 0 and split the
        signed grid-feed power into two independently-integrable sensors.
        ``self_consumption_power = max(0, pv1_power + pv2_power - export_power)``
        is the PV share consumed on-site rather than exported.

    **Battery fields** (hybrid models only):
        battery_voltage, battery_power, battery_soc, battery_temperature,
        battery_max_voltage, battery_min_voltage,
        battery_max_charge_current, battery_max_discharge_current.

    **EPS fields** (hybrid models with off-grid backup):
        eps_voltage, eps_current, eps_power, eps_frequency.

    **Inverter clock** (hybrid models):
        inverter_rtc — datetime-aware tuple (year, month, day, h, m, s).
    """

    # Common — always populated
    grid_voltage: float
    grid_current: float
    grid_power: int
    pv1_voltage: float
    pv2_voltage: float
    pv1_current: float
    pv2_current: float
    pv1_power: int
    pv2_power: int
    grid_frequency: float
    mode: int
    mode_name: str
    energy_total: float
    energy_today: float
    temperature: int
    runtime_total: int

    # CT-clamp — populated when the inverter has a CT clamp connected
    import_power: int | None = None
    export_power: int | None = None
    self_consumption_power: int | None = None
    total_export_energy: float | None = None
    total_import_energy: float | None = None

    # Battery — hybrid inverters only
    battery_voltage: float | None = None
    battery_power: int | None = None
    battery_soc: int | None = None
    battery_soh: float | None = None
    battery_temperature: int | None = None
    battery_max_voltage: float | None = None
    battery_min_voltage: float | None = None
    battery_max_charge_current: float | None = None
    battery_max_discharge_current: float | None = None

    # EPS (Emergency Power Supply) — hybrid inverters with off-grid backup
    eps_voltage: float | None = None
    eps_current: float | None = None
    eps_power: int | None = None
    eps_frequency: float | None = None

    # Inverter wall-clock — hybrid inverters expose an RTC
    inverter_rtc: tuple[int, int, int, int, int, int] | None = None
