"""Tests for the inverter-model registry."""

from __future__ import annotations

from aiosolax_uart import (
    MODELS,
    DeviceInfo,
    InverterFamily,
    InverterModel,
    lookup_model,
)


def test_known_model_5000() -> None:
    """The verified inverter code 5000 maps to a grid-tie family."""
    assert 5000 in MODELS
    model = MODELS[5000]
    assert model.family is InverterFamily.X1_GRID_TIE


def test_lookup_unknown_model_returns_unknown_family() -> None:
    """An unregistered code resolves to a stub Unknown model rather than KeyError."""
    model = lookup_model(0x9999)
    assert isinstance(model, InverterModel)
    assert model.code == 0x9999
    assert model.family is InverterFamily.UNKNOWN
    assert "9999" in model.name or "Unknown" in model.name


def test_device_info_model_property() -> None:
    """DeviceInfo.model property looks up the registry."""
    info = DeviceInfo(
        inverter_serial="X" * 14,
        inverter_model_code=5000,
        inverter_model_type=4,
        pocket_dongle_serial="ABCDEFGH",
    )
    assert info.model.family is InverterFamily.X1_GRID_TIE
