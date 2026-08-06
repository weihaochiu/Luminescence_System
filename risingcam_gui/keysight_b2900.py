from __future__ import annotations

from typing import Any

from .smu_base import SMUDevice, SMUDriver


def is_keysight_b2900(manufacturer: str, model: str) -> bool:
    maker = manufacturer.strip().upper()
    normalized_model = model.strip().upper()
    return ("KEYSIGHT" in maker or "AGILENT" in maker) and normalized_model.startswith("B29")


class KeysightB2900Driver(SMUDriver):
    """Identity and safety-state support for Keysight B2900-series SMUs."""

    driver_name = "Keysight B2900"

    def __init__(self, resource: Any, device: SMUDevice) -> None:
        super().__init__(resource, device)

