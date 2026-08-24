from __future__ import annotations

import unittest

from core.error_registry import (
    ALLOWED_ACTIONS,
    ERROR_CODE_PATTERN,
    VALID_SUBSYSTEMS,
    ErrorDefinition,
    ErrorRegistry,
    Severity,
    default_error_registry,
)
from core.i18n import Language, load_catalog


class ErrorRegistryTests(unittest.TestCase):
    def test_registry_definitions_are_unique_and_valid(self) -> None:
        definitions = default_error_registry.all()
        codes = [item.code for item in definitions]
        self.assertEqual(len(codes), len(set(codes)))
        for definition in definitions:
            self.assertRegex(definition.code, ERROR_CODE_PATTERN)
            self.assertIn(definition.subsystem, VALID_SUBSYSTEMS)
            self.assertIsInstance(definition.severity, Severity)
            self.assertIsInstance(definition.recoverable, bool)
            self.assertTrue(definition.solution_keys)

    def test_all_translation_keys_exist_in_both_languages(self) -> None:
        catalogs = {language: load_catalog(language) for language in Language}
        for definition in default_error_registry.all():
            keys = (
                definition.title_key,
                definition.message_key,
                *definition.cause_keys,
                *definition.solution_keys,
            )
            for key in keys:
                for language, catalog in catalogs.items():
                    self.assertIn(key, catalog, f"{definition.code} {language.value}")
                    self.assertTrue(catalog[key].strip())

    def test_critical_definition_rejects_ignore_or_continue(self) -> None:
        for action in ("ignore", "continue"):
            with self.assertRaisesRegex(ValueError, "cannot be ignored"):
                ErrorRegistry(
                    [
                        ErrorDefinition(
                            "SMU-999",
                            "smu",
                            Severity.CRITICAL,
                            False,
                            "title",
                            "message",
                            (),
                            ("solution",),
                            (action,),
                        )
                    ]
                )

    def test_unknown_action_is_rejected(self) -> None:
        self.assertEqual({"retry", "reconnect", "safe_shutdown"}, set(ALLOWED_ACTIONS))
        with self.assertRaisesRegex(ValueError, "Invalid action"):
            ErrorRegistry(
                [
                    ErrorDefinition(
                        "CAM-999", "camera", Severity.ERROR, True,
                        "title", "message", (), ("solution",), ("refresh_everything",),
                    )
                ]
            )

    def test_measurement_failure_has_no_automatic_retry(self) -> None:
        self.assertNotIn("retry", default_error_registry.require("MEAS-201").actions)


if __name__ == "__main__":
    unittest.main()
