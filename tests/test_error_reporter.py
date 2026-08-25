from __future__ import annotations

import json
import unittest

from core.error_registry import Severity
from core.error_reporter import ErrorReporter, format_diagnostics
from core.i18n import Language, configure_i18n, set_language


class ErrorReporterTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure_i18n(None)

    def test_report_creates_structured_context_log_and_history(self) -> None:
        reporter = ErrorReporter(history_limit=3)
        error = RuntimeError("VI_ERROR_TMO")
        with self.assertLogs("luminescence.errors", level="ERROR") as captured:
            event = reporter.report(
                "SMU-201",
                context={
                    "channel": "CH1",
                    "resource": "USB0::1::INSTR",
                    "command": ":OUTP?",
                    "password": "must-not-appear",
                },
                exception=error,
                present=False,
            )
        self.assertEqual("SMU-201", event.code)
        self.assertEqual("CH1", event.context.channel)
        self.assertEqual("RuntimeError", event.context.exception_type)
        self.assertEqual("[REDACTED]", event.context.as_dict()["password"])
        self.assertEqual((event,), reporter.history())
        self.assertIn('"error_code": "SMU-201"', captured.output[0])
        self.assertIn('"subsystem": "smu"', captured.output[0])

    def test_history_is_bounded(self) -> None:
        reporter = ErrorReporter(history_limit=2)
        events = [
            reporter.report("CAM-203", context={"actual": index}, present=False)
            for index in range(3)
        ]
        self.assertEqual((events[1], events[2]), reporter.history())

    def test_unknown_code_maps_to_internal_error_with_requested_code(self) -> None:
        reporter = ErrorReporter()
        event = reporter.report("BOGUS-999", present=False)
        self.assertEqual("SYS-001", event.code)
        self.assertEqual("BOGUS-999", event.context.as_dict()["requested_error_code"])

    def test_critical_event_has_critical_severity_and_no_forbidden_actions(self) -> None:
        reporter = ErrorReporter()
        event = reporter.report("SMU-203", present=False)
        self.assertIs(Severity.CRITICAL, event.severity)
        self.assertNotIn("ignore", event.definition.actions)
        self.assertNotIn("continue", event.definition.actions)

    def test_event_text_follows_runtime_language(self) -> None:
        configure_i18n(None)
        reporter = ErrorReporter()
        event = reporter.report("SMU-203", present=False)
        self.assertEqual("無法確認 SMU 輸出已關閉", event.title)
        set_language(Language.EN_US, persist=False)
        self.assertEqual("Unable to Confirm SMU Output OFF", event.title)

    def test_diagnostics_are_plain_text_and_include_exception(self) -> None:
        reporter = ErrorReporter()
        event = reporter.report(
            "FILE-201",
            context={"operation": "save", "resource": "D:/output"},
            exception=OSError("disk full"),
            present=False,
        )
        diagnostics = format_diagnostics(event)
        self.assertIn("Error Code: FILE-201", diagnostics)
        self.assertIn("Operation: save", diagnostics)
        self.assertIn("Exception Message: disk full", diagnostics)

    def test_credentials_are_redacted_everywhere_but_normal_resources_survive(self) -> None:
        secrets = (
            "password=plain-password",
            '"password":"json-password"',
            "token: plain-token",
            '"token": "json-token"',
            "access_token=access-secret",
            "refresh_token=refresh-secret",
            "api-key=api-secret",
            "Authorization: Bearer bearer-secret",
            "Authorization: Basic dXNlcjpwYXNz",
            "Authorization=Token authorization-secret",
            "https://x.test?a=1&token=query-secret&mode=read",
        )
        secret = RuntimeError(" | ".join(secrets))
        with self.assertLogs("luminescence.errors", level="ERROR") as captured:
            event = ErrorReporter().report(
                "SMU-201",
                context={
                    "resource": "USB0::0x2A8D::0x9201::MY61390254::INSTR",
                    "command": "GET https://example.test/path?api_key=context-secret&mode=read",
                    "note": "credential: topsecret",
                    "api-key": "direct-key-secret",
                    "path": r"D:\Measurement\data",
                    "channel": "CH1",
                },
                exception=secret,
                present=False,
            )
        diagnostics = format_diagnostics(event)
        payload = captured.output[0]
        context_payload = json.dumps(event.context.as_dict(), ensure_ascii=False)
        for forbidden in (
            "plain-password",
            "json-password",
            "plain-token",
            "json-token",
            "access-secret",
            "refresh-secret",
            "api-secret",
            "bearer-secret",
            "dXNlcjpwYXNz",
            "authorization-secret",
            "query-secret",
            "context-secret",
            "topsecret",
            "direct-key-secret",
        ):
            self.assertNotIn(forbidden, context_payload)
            self.assertNotIn(forbidden, diagnostics)
            self.assertNotIn(forbidden, payload)
        self.assertIn("USB0::0x2A8D::0x9201::MY61390254::INSTR", diagnostics)
        self.assertIn(r"D:\Measurement\data", diagnostics)
        self.assertIn("CH1", diagnostics)
        self.assertIn("mode=read", diagnostics)


if __name__ == "__main__":
    unittest.main()
