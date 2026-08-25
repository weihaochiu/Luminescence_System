from __future__ import annotations

import ast
import unittest

from scripts.generate_user_message_inventory import Collector, collect


class UserMessageInventoryScannerTests(unittest.TestCase):
    def _entries(self, source: str):
        collector = Collector("gui/example.py")
        collector.visit(ast.parse(source))
        return collector.entries

    def test_visible_if_expression_records_both_literals(self) -> None:
        entries = self._entries(
            'widget.setText("● 錯誤" if failed else "● 未連線")'
        )
        self.assertEqual({"● 錯誤", "● 未連線"}, {entry.message for entry in entries})
        self.assertTrue(all(entry.translation for entry in entries))

    def test_indirect_presentation_fields_are_flagged(self) -> None:
        entries = self._entries(
            'State(status_text="SMU 未連線", manual_lock_reason="請先連線")'
        )
        self.assertEqual(
            {"SMU 未連線", "請先連線"},
            {entry.message for entry in entries},
        )
        self.assertTrue(all("indirect presentation field" in entry.reason for entry in entries))

    def test_joined_tooltip_list_literals_are_flagged(self) -> None:
        entries = self._entries(
            '''
lines = [
    f"Requested: {requested}",
    f"Readback: {readback}",
]
lines.append(f"Error: {error}")
widget.setToolTip("\\n".join(lines))
'''
        )
        self.assertEqual(
            {"Requested: {requested}", "Readback: {readback}", "Error: {error}"},
            {entry.message for entry in entries},
        )
        self.assertTrue(all(entry.kind == "B. Tooltip" for entry in entries))
        self.assertTrue(all(entry.translation for entry in entries))

    def test_repository_audit_has_no_unresolved_translation_candidates(self) -> None:
        unresolved = [
            entry
            for entry in collect()
            if entry.user_facing and entry.translation
        ]
        self.assertEqual([], unresolved)


if __name__ == "__main__":
    unittest.main()
