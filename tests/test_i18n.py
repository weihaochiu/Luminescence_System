from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

from core.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_SETTINGS_KEY,
    Language,
    configure_i18n,
    i18n,
    load_catalog,
    placeholder_names,
    set_language,
    tr,
    validate_catalogs,
)


class FakeSettings:
    def __init__(self, initial: dict[str, object] | None = None) -> None:
        self.values = dict(initial or {})
        self.sync_count = 0

    def value(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def sync(self) -> None:
        self.sync_count += 1


class I18nTests(unittest.TestCase):
    maxDiff = None

    def tearDown(self) -> None:
        configure_i18n(None)

    def test_catalog_keys_and_placeholders_match(self) -> None:
        self.assertEqual([], validate_catalogs())
        self.assertEqual(set(load_catalog(Language.ZH_TW)), set(load_catalog(Language.EN_US)))
        for key, value in load_catalog(Language.ZH_TW).items():
            self.assertEqual(
                placeholder_names(value),
                placeholder_names(load_catalog(Language.EN_US)[key]),
                key,
            )

    def test_unknown_key_has_visible_fallback(self) -> None:
        configure_i18n(None)
        self.assertEqual("[missing.translation.key]", tr("missing.translation.key"))

    def test_all_literal_application_translation_keys_exist(self) -> None:
        catalogs = {
            language: load_catalog(language)
            for language in (Language.ZH_TW, Language.EN_US)
        }
        root = Path(__file__).resolve().parents[1]
        missing: list[str] = []
        paths = [
            *sorted((root / "core").rglob("*.py")),
            *sorted((root / "gui").rglob("*.py")),
        ]
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                name = node.func.id if isinstance(node.func, ast.Name) else ""
                first = node.args[0]
                if name != "tr" or not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                    continue
                for language, catalog in catalogs.items():
                    if first.value not in catalog:
                        missing.append(
                            f"{path.relative_to(root)}:{node.lineno}: {language.value} {first.value}"
                        )
        self.assertEqual([], missing)

    def test_runtime_language_switch(self) -> None:
        configure_i18n(None)
        self.assertEqual("關閉", tr("common.close"))
        self.assertTrue(set_language(Language.EN_US, persist=False))
        self.assertEqual("Close", tr("common.close"))
        self.assertFalse(set_language("en_US", persist=False))

    def test_language_persistence(self) -> None:
        settings = FakeSettings()
        configure_i18n(settings)
        set_language(Language.EN_US)
        self.assertEqual("en-US", settings.values[LANGUAGE_SETTINGS_KEY])
        self.assertEqual(1, settings.sync_count)
        configure_i18n(FakeSettings({LANGUAGE_SETTINGS_KEY: "en-US"}))
        self.assertEqual(Language.EN_US, i18n.language)

    def test_invalid_persisted_language_falls_back(self) -> None:
        selected = configure_i18n(FakeSettings({LANGUAGE_SETTINGS_KEY: "xx-YY"}))
        self.assertEqual(DEFAULT_LANGUAGE, selected)

    def test_placeholder_formatting_and_failure(self) -> None:
        configure_i18n(None)
        self.assertEqual(
            "EL 量測設備控制程式 v1.2.3",
            tr("app.title", version="1.2.3"),
        )
        with self.assertRaisesRegex(ValueError, "app.title"):
            tr("app.title")


if __name__ == "__main__":
    unittest.main()
