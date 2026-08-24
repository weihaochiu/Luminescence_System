from __future__ import annotations

import unittest

from core.i18n import Language, configure_i18n, set_language
from gui.manual_smu_settings import ManualSMUSettingsStore, MODE_KEY
from gui.recipe_store import Recipe


class DictSettings:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def value(self, key: str, default=None):
        return self.values.get(key, default)


class CanonicalPersistenceTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure_i18n(None)

    def test_legacy_chinese_recipe_values_migrate_to_canonical_values(self) -> None:
        recipe = Recipe.from_dict(
            {
                "state": "啟用",
                "geometry": {"forward_polarity": "正向為負"},
                "el_matrix": {"output_mode": "定電壓", "voltage_v": [1.2]},
                "dark_iv": {"direction": "雙向", "compliance_action": "立即中止"},
            }
        )
        payload = recipe.to_dict()
        self.assertEqual("active", payload["state"])
        self.assertEqual("negative", payload["geometry"]["forward_polarity"])
        self.assertEqual("voltage", payload["el_matrix"]["output_mode"])
        self.assertEqual("bidirectional", payload["dark_iv"]["direction"])
        self.assertEqual("abort", payload["dark_iv"]["compliance_action"])

    def test_recipe_values_do_not_change_between_languages(self) -> None:
        configure_i18n(None)
        source = Recipe.from_dict({"el_matrix": {"output_mode": "current_density"}})
        zh_payload = source.to_dict()
        set_language(Language.EN_US, persist=False)
        en_loaded = Recipe.from_dict(zh_payload)
        self.assertEqual(zh_payload["el_matrix"], en_loaded.to_dict()["el_matrix"])
        set_language(Language.ZH_TW, persist=False)
        zh_loaded = Recipe.from_dict(en_loaded.to_dict())
        self.assertEqual(en_loaded.to_dict()["el_matrix"], zh_loaded.to_dict()["el_matrix"])

    def test_manual_smu_legacy_display_values_migrate(self) -> None:
        for legacy, expected in (("定電流密度", "CC"), ("定電壓", "CV"), ("constant_voltage", "CV")):
            settings = DictSettings({MODE_KEY: legacy})
            self.assertEqual(expected, ManualSMUSettingsStore._load_from(settings).mode)


if __name__ == "__main__":
    unittest.main()
