from __future__ import annotations

import csv
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from core.i18n import tr
from gui.camera_recipe_ae import begin_recipe_ae, restore_recipe_ae
from gui.camera_controller import CameraController
from gui.el_matrix_plan import ELMatrixPlan
from gui.el_matrix_runner import ELMatrixRunner, _RuntimeETA
from gui.main_window_measurement import _validate_camera_matrix
from gui.pixel_csv_postprocessor import PixelCSVPostprocessor
from gui.recipe_ae_stops import baseline_range_us, bracket_exposures_us, native_baseline_range_us
from gui.recipe_dialog import RecipeManagerDialog
from gui.recipe_store import RecipeStore
from gui.smu_control import SMUSafetyLimits
from tests.test_recipe_auto_exposure import auto_recipe, AutoHardware, AutoCamera
from tests.test_exposure_estimates import budget_recipe
from tests.qt_test_utils import ensure_qapplication


class RecipeAEStopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def test_order_fractional_stops_and_optional_baseline(self):
        self.assertEqual((1000000, 125000, 500000),
                         bracket_exposures_us(500000, [1, -2, 0]))
        self.assertEqual((707107, 353553), bracket_exposures_us(500000, [0.5, -0.5]))
        self.assertEqual((250000,), bracket_exposures_us(500000, [-1]))

    def test_invalid_stop_lists_are_rejected_and_manual_is_independent(self):
        for stops in ([], [0, 0], [float('nan')], [float('inf')], ['1'], [True],
                      [13], [-13], None, [index / 10 for index in range(34)], [-12, 12]):
            with self.subTest(stops=stops):
                recipe = auto_recipe()
                recipe.el_matrix.auto_exposure_stops = stops
                self.assertIn(tr('recipe.validation.auto_stops'), recipe.validate())
                recipe.el_matrix.exposure_mode = 'manual'
                self.assertNotIn(tr('recipe.validation.auto_stops'), recipe.validate())

    def test_full_bracket_fits_cap_and_microsecond_resolution(self):
        self.assertEqual((120, 3750000), baseline_range_us([-2, 0, 2], 15000))
        self.assertEqual((4000, 3750000), baseline_range_us([-2, 0, 2], 15000, (1000, 15000000)))
        with self.assertRaises(ValueError):
            baseline_range_us([-2, 2], 0.1)
        with self.assertRaises(ValueError):
            bracket_exposures_us(30, [0, 0.000001])

    def test_native_baseline_respects_sdk_and_capture_caps_independently(self):
        self.assertEqual((30, 5000000), native_baseline_range_us([0], 15000))
        self.assertEqual((30, 1000000), native_baseline_range_us([0], 1000))
        self.assertEqual((120, 3750000), native_baseline_range_us([-2, 0, 2], 15000))
        low, high = native_baseline_range_us([0, 1], 15000)
        self.assertEqual((30, 5000000), (low, high))
        self.assertEqual((5000000, 10000000), bracket_exposures_us(high, [0, 1]))
        with self.assertRaisesRegex(ValueError, "native SDK AE"):
            native_baseline_range_us([-1], 15000, (3000000, 15000000))

    def test_native_baseline_rejected_before_measurement_if_camera_minimum_is_too_high(self):
        recipe = auto_recipe()
        recipe.el_matrix.auto_exposure_stops = [-1]
        owner = SimpleNamespace(selected_recipe=recipe,
            camera_info={'exposure_range_us': (3000000, 15000000), 'gain_range': (100, 800)},
            smu_manager=SimpleNamespace(control=SimpleNamespace(safety=SimpleNamespace(limits=SMUSafetyLimits()))))
        self.assertIn(tr('recipe.validation.auto_stops'), _validate_camera_matrix(owner))

    def test_native_gain_limit_does_not_limit_manual_capture_settings(self):
        recipe = auto_recipe()
        recipe.el_matrix.auto_gain_mode = "fixed"
        recipe.el_matrix.auto_gain_percent = 6000
        owner = SimpleNamespace(selected_recipe=recipe,
            camera_info={'exposure_range_us': (30, 15000000), 'gain_range': (100, 10000)},
            smu_manager=SimpleNamespace(control=SimpleNamespace(safety=SimpleNamespace(limits=SMUSafetyLimits()))))
        self.assertIn(tr('measurement.validation.gain_range', low=100, high=5000),
                      _validate_camera_matrix(owner))
        recipe.el_matrix.exposure_mode = "manual"
        recipe.el_matrix.gains_percent = [6000]
        recipe.el_matrix.exposures_ms = [15000]
        self.assertEqual([], _validate_camera_matrix(owner))

    def test_formal_stop_capture_can_exceed_native_ae_time_limit(self):
        recipe = auto_recipe()
        recipe.el_matrix.current_density_ma_cm2 = [2]
        recipe.el_matrix.auto_exposure_stops = [0, 1]
        recipe.el_matrix.repeat = 1
        recipe.el_matrix.dark_frame_enabled = False
        hardware = AutoHardware(((5000000, 200),))
        with tempfile.TemporaryDirectory() as directory:
            runner = ELMatrixRunner(recipe, hardware, directory,
                report_progress=lambda _: None, is_cancel_requested=lambda: False)
            result = runner.run()
            captures = [event for event in hardware.events
                        if isinstance(event, tuple) and event[0] == 'capture']
            self.assertEqual([5000, 10000], [event[1] for event in captures])
            self.assertEqual(2, result['captures'])
            self.assertTrue(hardware.safe)

    def test_v12_defaults_to_zero_and_v13_round_trip_preserves_custom_list(self):
        recipe = auto_recipe()
        with tempfile.TemporaryDirectory() as directory:
            store = RecipeStore(Path(directory) / 'recipes.json')
            legacy = recipe.to_dict()
            del legacy['el_matrix']['auto_exposure_stops']
            self.assertEqual([0.0], store.import_payload(
                {'schema_version': 12, 'recipe': legacy}).el_matrix.auto_exposure_stops)
            recipe.el_matrix.auto_exposure_stops = [-2, -0.5, 1]
            store.upsert(recipe)
            self.assertEqual([-2, -0.5, 1], RecipeStore(store.path).get(recipe.recipe_id).el_matrix.auto_exposure_stops)

    def test_ui_list_recalculates_estimate_and_preserves_mode_values(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RecipeStore(Path(directory) / 'recipes.json')
            store.upsert(budget_recipe())
            dialog = RecipeManagerDialog(store)
            try:
                dialog.auto_stops_edit.setText('-1, 0, +1')
                self.assertEqual([-1, 0, 1], dialog._read_form_to_recipe().el_matrix.auto_exposure_stops)
                self.assertIn('05:30', dialog.time_estimate_value.text())
                dialog.auto_stops_edit.setText('0, 0')
                self.assertEqual(tr('recipe.estimate_unavailable'), dialog.time_estimate_value.text())
                dialog.exposure_mode_combo.setCurrentIndex(0)
                dialog.auto_stops_edit.setText('invalid inactive field')
                self.assertFalse(dialog._read_form_to_recipe().validate())
                self.assertTrue(dialog.matrix_current_density_edit.isEnabled())
            finally:
                dialog.close()

    def test_stop_count_and_exposure_sum_budget_includes_repeat_and_dark(self):
        recipe = budget_recipe()
        recipe.el_matrix.auto_exposure_stops = [-1, 0, 1]
        plan = ELMatrixPlan(recipe)
        self.assertEqual({'shared_dark': 12, 'el_per_channel': 12, 'total_el': 12, 'overall': 24}, plan.capture_counts())
        self.assertEqual(plan.capture_counts(), recipe.matrix_capture_counts())
        self.assertEqual((3750, 7500, 15000), plan.exposures_ms)
        self.assertEqual(210, plan.estimate().exposure_time_s)
        self.assertEqual(330, plan.estimate().total_time_s)
        self.assertEqual(112.5, plan.estimate().output_on_per_setpoint_s)
        self.assertEqual(210, sum(plan.exposure_sequence_after(0)))

    def test_sdk_narrows_baseline_limits_and_restores_previous_range(self):
        controller = CameraController()
        controller._camera = AutoCamera()
        controller._width, controller._height = 4, 3
        controller._camera_is_mono = True
        controller._scientific_pull_bits = 16
        controller._auto_exposure_roi_readback = (0, 0, 4, 3)
        controller._auto_exposure_roi_verified = True
        settings = asdict(auto_recipe().el_matrix)
        settings['auto_exposure_stops'] = [-2, 0, 2]
        state = {}
        try:
            begin_recipe_ae(controller, settings, state)
            self.assertEqual((3750000, 120, 500, 100), controller._camera.auto_range)
            restore_recipe_ae(controller, state)
            self.assertEqual((350000, 30, 500, 100), controller._camera.auto_range)
        finally:
            controller.close_camera()

    def test_hardware_range_rejected_before_run_if_bracket_cannot_fit(self):
        recipe = auto_recipe()
        recipe.el_matrix.auto_exposure_stops = [-2, 2]
        recipe.el_matrix.auto_max_exposure_ms = 1
        owner = SimpleNamespace(selected_recipe=recipe,
            camera_info={'exposure_range_us': (100, 15000000), 'gain_range': (100, 800)},
            smu_manager=SimpleNamespace(control=SimpleNamespace(safety=SimpleNamespace(limits=SMUSafetyLimits()))))
        self.assertIn(tr('recipe.validation.auto_stops'), _validate_camera_matrix(owner))
        recipe.el_matrix.auto_exposure_stops = []
        self.assertIn(tr('recipe.validation.auto_stops'), _validate_camera_matrix(owner))

    def test_runner_captures_custom_order_repeat_and_matched_deduplicated_dark(self):
        recipe = budget_recipe()
        recipe.el_matrix.auto_exposure_stops = [1, -1, 0]
        recipe.output.export_pixel_csv = True
        recipe.output.pixel_csv_exposure_normalized = True
        hardware = AutoHardware(((500000, 200), (1000000, 200)))
        progress = []
        with tempfile.TemporaryDirectory() as directory:
            runner = ELMatrixRunner(recipe, hardware, directory,
                report_progress=progress.append, is_cancel_requested=lambda: False)
            result = runner.run()
            self.assertEqual(20, result['captures'])  # 12 EL + 4 unique Dark * 2.
            captures = [event for event in hardware.events if isinstance(event, tuple) and event[0] == 'capture']
            self.assertEqual([1000, 1000, 250, 250, 500, 500,
                              2000, 2000, 500, 500, 1000, 1000], [event[1] for event in captures[:12]])
            self.assertTrue(all(event[2] == 200 for event in captures))
            self.assertEqual(2, hardware.events.count(('ae', 'auto')))
            with (runner.run_directory / 'measurement_manifest.csv').open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([1, 1, -1, -1, 0, 0] * 2, [float(row['RecipeAEStop']) for row in rows[:12]])
            self.assertEqual([500000] * 6 + [1000000] * 6,
                             [int(row['RecipeAEBaselineExposureUs']) for row in rows[:12]])
            self.assertTrue(all(None not in row for row in rows))
            self.assertEqual('completed', PixelCSVPostprocessor(runner.run_directory, result['safe_shutdown']).run()['status'])
            self.assertAlmostEqual(0, progress[-1].remaining_time_s)

    def test_partial_resolution_replaces_stop_sum_and_deduplicates_dark(self):
        recipe = budget_recipe()
        recipe.el_matrix.auto_exposure_stops = [-1, 0, 1]
        eta = _RuntimeETA(ELMatrixPlan(recipe))
        profiles = {(200, 250): {}, (200, 500): {}, (200, 1000): {}}
        eta.resolve_auto_exposure(1.75, profiles)
        self.assertEqual(112, eta.remaining_exposure_s)  # unresolved 105 + resolved EL/Dark 7.
        profiles.update({(200, 2000): {}})
        eta.resolve_auto_exposure(3.5, profiles)
        self.assertEqual(18, eta.remaining_exposure_s)  # EL 10.5 + dedup Dark 7.5.
        self.assertEqual(20, eta.plan.capture_counts()['overall'])

    def test_out_of_range_baseline_fails_before_any_capture_and_shuts_down(self):
        recipe = auto_recipe()
        recipe.el_matrix.auto_exposure_stops = [0, 2]
        hardware = AutoHardware(((5000000, 200),))
        with tempfile.TemporaryDirectory() as directory:
            runner = ELMatrixRunner(recipe, hardware, directory,
                report_progress=lambda _p: None, is_cancel_requested=lambda: False)
            with self.assertRaisesRegex(RuntimeError, 'baseline'):
                runner.run()
            self.assertFalse(any(isinstance(event, tuple) and event[0] == 'capture' for event in hardware.events))
            self.assertIn('safe_shutdown', hardware.events)


if __name__ == '__main__':
    unittest.main()
