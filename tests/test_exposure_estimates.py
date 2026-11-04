from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.i18n import tr
from gui.el_matrix_plan import ELMatrixPlan, format_duration
from gui.el_matrix_runner import ELMatrixRunner, MatrixRuntimeProgress, _RuntimeETA
from gui.main_window_measurement import _measurement_summary
from gui.measurement_progress_dialog import MeasurementProgressDialog
from gui.recipe_dialog import RecipeManagerDialog
from gui.recipe_store import RecipeStore
from gui.smu_control import SMUSafetyLimits
from tests.qt_test_utils import ensure_qapplication
from tests.test_recipe_auto_exposure import auto_recipe, AutoHardware


def budget_recipe():
    recipe = auto_recipe()
    matrix = recipe.el_matrix
    matrix.estimated_capture_overhead_s = 0
    matrix.estimated_routing_transition_s = 0
    matrix.estimated_polarity_duration_s = 0
    matrix.estimated_shared_dark_overhead_s = 0
    return recipe


class ExposureEstimateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def test_auto_budget_ignores_hidden_manual_axes_and_gain_mode(self):
        recipe = budget_recipe()
        estimate = ELMatrixPlan(recipe).estimate()
        self.assertEqual(240, estimate.total_time_s)  # 2 AE * 60 + 8 frames * 15.
        self.assertEqual(120, estimate.auto_exposure_time_s)
        recipe.el_matrix.gains_percent = [100, 200, 500]
        recipe.el_matrix.exposures_ms = [100, 200, 500, 1000]
        recipe.el_matrix.auto_gain_mode = "fixed"
        recipe.el_matrix.auto_gain_percent = 200
        self.assertEqual(estimate.total_time_s, ELMatrixPlan(recipe).estimate().total_time_s)

    def test_budget_counts_channels_electrical_conditions_and_repeat_separately(self):
        recipe = budget_recipe()
        recipe.el_matrix.output_mode = "voltage"
        recipe.el_matrix.voltage_v = [0.8, 1, 1.1]
        recipe.channels[1].enabled = True
        recipe.el_matrix.repeat = 3
        estimate = ELMatrixPlan(recipe).estimate()
        self.assertEqual(6 * 60, estimate.auto_exposure_time_s)
        self.assertEqual(36, estimate.overall_captures)
        self.assertEqual(6 * 60 + 36 * 15, estimate.total_time_s)
        recipe.el_matrix.dark_frame_enabled = False
        self.assertEqual(6 * 60 + 18 * 15, ELMatrixPlan(recipe).estimate().total_time_s)

    def test_fixed_budget_counts_down_and_is_removed_when_phase_finishes(self):
        tick = [0.0]
        eta = _RuntimeETA(ELMatrixPlan(budget_recipe()), clock=lambda: tick[0])
        eta.begin_fixed(60)
        tick[0] = 3
        self.assertEqual(237, eta.remaining_s())
        eta.finish_fixed()
        self.assertEqual(180, eta.remaining_s())
        self.assertIsNone(eta.active_started)

    def test_convergence_updates_all_repeats_and_deduplicates_dark_immediately(self):
        eta = _RuntimeETA(ELMatrixPlan(budget_recipe()), clock=lambda: 0)
        eta.begin_fixed(60)
        eta.finish_fixed()
        eta.resolve_auto_exposure(0.5, {(200, 500.0): {}})
        self.assertEqual(122, eta.remaining_s())
        self.assertEqual("auto_upper_bound", eta.estimate_mode)
        for _ in range(2):
            eta.begin_capture(0.5)
            eta.complete_capture(0.5, 0.5)
        eta.begin_fixed(60)
        eta.finish_fixed()
        eta.resolve_auto_exposure(0.5, {(200, 500.0): {}})
        self.assertEqual(2, eta.remaining_s())
        self.assertEqual(4, eta.remaining_captures)
        self.assertEqual(6, eta.plan.capture_counts()["overall"])
        self.assertEqual("auto_resolved", eta.estimate_mode)
        for _ in range(4):
            eta.complete_capture(0.5, 0.5)
        self.assertEqual(0, eta.remaining_s())

    def test_distinct_gain_or_exposure_keeps_distinct_dark_budget(self):
        eta = _RuntimeETA(ELMatrixPlan(budget_recipe()), clock=lambda: 0)
        eta.resolve_auto_exposure(0.5, {(200, 500.0): {}})
        eta.resolve_auto_exposure(0.25, {(200, 500.0): {}, (300, 250.0): {}})
        self.assertEqual(4, eta.plan.capture_counts()["shared_dark"])
        self.assertEqual(3, eta.remaining_exposure_s)  # EL + Dark, two repeats each.

    def test_active_capture_counts_down_without_double_subtraction(self):
        tick = [0.0]
        eta = _RuntimeETA(ELMatrixPlan(budget_recipe()), clock=lambda: tick[0])
        eta.begin_capture(15)
        tick[0] = 10
        self.assertEqual(230, eta.remaining_s())
        eta.complete_capture(15, 15)
        self.assertEqual(225, eta.remaining_s())

    def test_slow_capture_can_move_estimated_finish_later(self):
        eta = _RuntimeETA(ELMatrixPlan(budget_recipe()), clock=lambda: 0)
        now = [datetime(2026, 11, 4, 12).astimezone()]
        owner = SimpleNamespace(_eta=eta, now=lambda: now[0])
        _, first_finish = ELMatrixRunner._progress_time(owner)
        now[0] += timedelta(seconds=100)
        eta.complete_capture(15, 45)  # 30 s observed overhead for remaining frames.
        remaining, later_finish = ELMatrixRunner._progress_time(owner)
        self.assertGreater(later_finish, first_finish)
        self.assertEqual(now[0] + timedelta(seconds=remaining), later_finish)

    def test_editor_recalculates_modes_and_active_parameters_and_clears_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RecipeStore(Path(directory) / "recipes.json")
            store.upsert(budget_recipe())
            dialog = RecipeManagerDialog(store)
            try:
                self.assertIn(tr("recipe.estimate_auto"), dialog.time_estimate_value.text())
                self.assertIn("04:00", dialog.time_estimate_value.text())
                dialog.matrix_gain_edit.setText("100, 200, 500")
                dialog.matrix_exposure_edit.setText("1, 2, 3, 1000")
                self.assertIn("04:00", dialog.time_estimate_value.text())
                dialog.auto_timeout_spin.setValue(30)
                self.assertIn("03:00", dialog.time_estimate_value.text())
                dialog.exposure_mode_combo.setCurrentIndex(0)
                self.assertIn(tr("recipe.estimate_manual"), dialog.time_estimate_value.text())
                self.assertNotIn(tr("recipe.estimate_auto"), dialog.time_estimate_value.text())
                dialog.matrix_exposure_edit.setText("")
                self.assertEqual(tr("recipe.estimate_unavailable"), dialog.time_estimate_value.text())
                dialog.exposure_mode_combo.setCurrentIndex(1)
                self.assertIn("03:00", dialog.time_estimate_value.text())
                store.recipes.clear()
                dialog._reload_list()
                self.assertEqual(tr("recipe.estimate_unavailable"), dialog.time_estimate_value.text())
            finally:
                dialog.close()

    def test_confirmation_explains_ae_budget_and_separate_csv_time(self):
        recipe = budget_recipe()
        owner = SimpleNamespace(smu_manager=SimpleNamespace(
            control=SimpleNamespace(safety=SimpleNamespace(limits=SMUSafetyLimits()))))
        text = _measurement_summary(owner, ELMatrixPlan(recipe))
        self.assertIn(tr("recipe.estimate_auto"), text)
        self.assertIn(tr("recipe.estimate_auto_budget", duration="02:00"), text)
        self.assertIn(tr("recipe.estimate_scope"), text)

    def test_progress_shows_pending_and_resolved_estimate_basis(self):
        dialog = MeasurementProgressDialog("AE")
        try:
            dialog.update_progress(MatrixRuntimeProgress("Auto Exposure", 0, 8,
                remaining_time_s=120, estimate_mode="auto_upper_bound", remaining_ae_conditions=2))
            self.assertEqual("02:00", dialog.remaining_time_value.text())
            self.assertEqual(tr("progress.estimate_auto_pending", count=2), dialog.estimate_basis_value.text())
            dialog.update_progress(MatrixRuntimeProgress("EL", 4, 6,
                remaining_time_s=1, estimate_mode="auto_resolved"))
            self.assertEqual("00:01", dialog.remaining_time_value.text())
            self.assertEqual(tr("progress.estimate_auto_resolved"), dialog.estimate_basis_value.text())
        finally:
            dialog.close()

    def test_runner_heartbeat_and_final_zero_use_resolved_conditions(self):
        tick = [1.0]
        progress = []
        hardware = AutoHardware(((500000, 200), (500000, 200)))
        original = hardware.auto_exposure
        def converge(settings, check_cancel):
            for _ in range(2):
                tick[0] += 1.1
                check_cancel()
            return original(settings, check_cancel)
        hardware.auto_exposure = converge
        with tempfile.TemporaryDirectory() as directory, patch(
            "gui.el_matrix_runner.monotonic", side_effect=lambda: tick[0],
        ):
            runner = ELMatrixRunner(budget_recipe(), hardware, directory,
                report_progress=progress.append, is_cancel_requested=lambda: False)
            result = runner.run()
            samples = [item for item in progress if isinstance(item, MatrixRuntimeProgress)]
            pending = [item for item in samples if item.phase == "Auto Exposure" and item.remaining_ae_conditions == 2]
            self.assertGreaterEqual(len(pending), 3)
            self.assertGreater(pending[0].remaining_time_s, pending[-1].remaining_time_s)
            self.assertEqual(6, result["captures"])
            self.assertEqual("auto_resolved", samples[-1].estimate_mode)
            self.assertAlmostEqual(0, samples[-1].remaining_time_s)


if __name__ == "__main__":
    unittest.main()
