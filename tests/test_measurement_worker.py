from __future__ import annotations

import unittest

from tests.qt_test_utils import ensure_qapplication

from gui.measurement_worker import MeasurementCancelled, MeasurementWorker


class MeasurementWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_worker_reports_progress_and_result(self) -> None:
        events: list[object] = []

        def run(progress, cancelled):
            self.assertFalse(cancelled())
            progress("el", 1, 2, "capture")
            return {"ok": True}

        worker = MeasurementWorker(run)
        worker.progress_changed.connect(events.append)
        worker.finished.connect(events.append)
        worker.execute()
        self.assertEqual("el", events[0].phase)
        self.assertEqual({"ok": True}, events[1])

    def test_cancel_request_is_observable_by_measurement(self) -> None:
        worker = MeasurementWorker(lambda _progress, _cancelled: None)
        worker.request_cancel()
        self.assertTrue(worker.is_cancel_requested())
        with self.assertRaises(MeasurementCancelled):
            worker.check_cancelled()


if __name__ == "__main__":
    unittest.main()
