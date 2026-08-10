from __future__ import annotations

import unittest

from gui.keysight_b2900 import KeysightB2900Driver
from gui.numeric import format_scpi_number
from gui.recipe_store import ELPoint, Recipe
from gui.smu_base import SMUDevice


class FakeResource:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def write(self, command: str) -> None:
        self.commands.append(command)


class NumericTests(unittest.TestCase):
    def test_scpi_formatter_removes_binary_float_artifacts(self) -> None:
        self.assertEqual("0.3", format_scpi_number(0.1 + 0.2))
        self.assertEqual("0.0000001", format_scpi_number("0.0000001"))

    def test_b2900_uses_canonical_scpi_number_formatting(self) -> None:
        resource = FakeResource()
        driver = KeysightB2900Driver(resource, SMUDevice("USB0::test"))
        driver.set_voltage(0.1 + 0.2)
        driver.set_current(0.0000001)
        self.assertEqual([":SOUR:VOLT 0.3", ":SOUR:CURR 0.0000001"], resource.commands)

    def test_recipe_json_and_current_density_are_normalized(self) -> None:
        recipe = Recipe()
        recipe.geometry.active_area_cm2 = 0.1
        point = ELPoint(setpoint=0.1 + 0.2)
        self.assertEqual(0.03, recipe.actual_current_ma(point))
        recipe.el_sweep.points = [point]
        self.assertEqual(0.3, recipe.to_dict()["el_sweep"]["points"][0]["setpoint"])


if __name__ == "__main__":
    unittest.main()
