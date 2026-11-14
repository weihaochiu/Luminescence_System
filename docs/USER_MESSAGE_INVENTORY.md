# User Message Inventory

> Generated from the repository Python AST by `scripts/generate_user_message_inventory.py`.
> Line numbers describe the source revision at generation time; rerun the generator after migration.

## Scope and method

The scan covers repository source `*.py` files (including tests and the bundled SDK), excluding local-only `local/`, `ruler/`, and `backup/` data, and classifies visible Qt constructor/setter text, tooltips, status messages, QMessageBox calls, user-facing signal payloads, logger calls, `print`, and raised exception literals. It follows common local list/tuple → `append()` → `join()` → tooltip flows, but it is not a complete Python data-flow engine. The requested keyword audit (`錯誤`, `失敗`, `警告`, `無法`, `逾時`, `未連接`, `timeout`, `failed`, `error`, `warning`) is also represented where those literals occur in these call sites.

Inventory rows: **1033**; user-facing rows: **166**; translation candidates: **0**.
Static scanner counts and the supplemental manual indirect-UI audit are reported separately in `I18N_ERROR_SYSTEM_MIGRATION.md`; a zero static count alone is not proof that every dynamic UI path is translated.

Error-code values below are migration candidates, not registry definitions. Final codes are curated by failure condition so multiple call sites can share one stable code.

## Inventory

| File | Line / function | Current message | Type | User-facing? | Needs translation? | Needs Error Code? | Proposed translation key | Proposed error code | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| core/calibration/acquisition_quality.py | 83 / `evaluate` | Ruler acquisition quality requires a uint16 HxW frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/acquisition_quality.py | 139 / `_effective_dn_frame` | EffectiveDNMax is invalid | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/acquisition_quality.py | 143 / `_effective_dn_frame` | Right-aligned frame exceeds EffectiveDNMax | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/acquisition_quality.py | 148 / `_effective_dn_frame` | Left alignment requires a 2^N-1 EffectiveDNMax | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/acquisition_quality.py | 153 / `_effective_dn_frame` | RawValueAlignment must be verified as right or left | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/image_utils.py | 17 / `normalize_to_uint8` | Unsupported channel count: {source.shape} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/image_utils.py | 19 / `normalize_to_uint8` | Expected a non-empty HxW or HxWxC image, got {source.shape} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/image_utils.py | 22 / `normalize_to_uint8` | Input image has no finite pixels | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/models.py | 101 / `<module>` | FAIL | A. UI label / button / menu | Yes | No | No | `—` | — | indirect presentation assignment quality_label; canonical technical/value display |
| core/calibration/scale_solver.py | 48 / `pixels_per_mm_to_um_per_pixel` | pixels_per_mm must be positive and finite | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/scale_solver.py | 56 / `scale_bar_pixels` | Scale bar length and um_per_pixel must be positive and finite | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/scale_solver.py | 69 / `select_scale_bar` | Image width and scale must define a positive physical width | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/scale_solver.py | 80 / `select_scale_bar` | {selected / 10000} cm | A. UI label / button / menu | Yes | No | No | `—` | — | indirect presentation assignment label; canonical technical/value display |
| core/calibration/scale_solver.py | 82 / `select_scale_bar` | {selected / 1000} mm | A. UI label / button / menu | Yes | No | No | `—` | — | indirect presentation assignment label; canonical technical/value display |
| core/calibration/scale_solver.py | 84 / `select_scale_bar` | {selected} µm | A. UI label / button / menu | Yes | No | No | `—` | — | indirect presentation assignment label; canonical technical/value display |
| core/calibration/scale_solver.py | 207 / `solve` | FAIL | A. UI label / button / menu | Yes | No | No | `—` | — | indirect presentation assignment quality_label; canonical technical/value display |
| core/calibration/scale_solver.py | 207 / `solve` | PASS | A. UI label / button / menu | Yes | No | No | `—` | — | indirect presentation assignment quality_label; canonical technical/value display |
| core/calibration/service.py | 71 / `analyze` | Ruler calibration analysis start source=%s resolution=%sx%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| core/calibration/service.py | 193 / `analyze` | Ruler calibration analysis failed source=%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| core/calibration/service.py | 215 / `save_debug_package` | Calibration result does not contain an exact raw input frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/service.py | 221 / `save_debug_package` | Failed to write debug image: {path} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/calibration/service.py | 229 / `save_debug_package` | Ruler calibration debug package saved path=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| core/calibration/service.py | 280 / `_finish_log` | Ruler calibration analysis end source=%s elapsed_ms=%.1f angle=%s candidate_count=%s selected_method=%s selected_score=%s tick_comb_angle=%s orientation_disagreement=%s rectified_resolution=%s tick_candidates=%s accepted_ticks=%s ocr_raw=%s ocr_accepted=%s major_ticks=%s minor_ticks=%s rejected_ticks=%s pixels_per_mm=%s um_per_pixel=%s fit_rmse_px=%s fit_error_percent=%s quality=%s failure_reasons=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| core/error_registry.py | 46 / `__init__` | Duplicate error code: {definition.code} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 48 / `__init__` | Invalid error code: {definition.code} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 50 / `__init__` | Invalid subsystem for {definition.code}: {definition.subsystem} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 52 / `__init__` | Invalid recoverable flag for {definition.code} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 56 / `__init__` | Critical error {definition.code} cannot be ignored | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 59 / `__init__` | Invalid action for {definition.code}: {sorted(unknown_actions)} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 63 / `__init__` | Error {definition.code} requires at least one solution | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 70 / `from_path` | Error registry must be a JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_reporter.py | 71 / `__init__` | history_limit must be positive | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/i18n.py | 60 / `load_catalog` | Invalid translation catalog: {path} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/i18n.py | 134 / `translate` | Invalid placeholders for translation key {key}: {exc} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/release_info.py | 14 / `version_tuple` | Expected a major.minor.patch version | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/release_info.py | 20 / `validate_history` | Unsupported release history | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/release_info.py | 23 / `validate_history` | Missing release history | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/release_info.py | 27 / `validate_history` | Invalid release entry | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/release_info.py | 30 / `validate_history` | Release versions must be unique and newest first | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/release_info.py | 35 / `validate_history` | Invalid release changes | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/release_info.py | 41 / `validate_history` | Every release needs nonempty bilingual changes | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 68 / `read_json` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 88 / `safe_relative` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 103 / `target_file` | local_changes | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 109 / `target_file` | local_changes | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 122 / `_json_url` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 125 / `_json_url` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 133 / `check_latest` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 141 / `download_archive` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 147 / `download_archive` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 152 / `download_archive` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 156 / `download_archive` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 168 / `extract_package` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 174 / `extract_package` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 176 / `extract_package` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 181 / `extract_package` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 191 / `extract_package` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 194 / `extract_package` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 201 / `extract_package` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 205 / `extract_package` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 217 / `install_conflicts` | unverified_install | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 224 / `install_conflicts` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 241 / `prepare_update` | development_checkout | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 243 / `prepare_update` | pending_update | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 245 / `prepare_update` | unverified_install | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 249 / `prepare_update` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 251 / `prepare_update` | disk_space | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 258 / `prepare_update` | local_changes | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 262 / `prepare_update` | disk_space | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 272 / `prepare_update` | dependencies | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 280 / `prepare_update` | dependencies | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/software_update.py | 287 / `prepare_update` | dependencies | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/update_launcher.py | 21 / `main` | Update recovery failed. Preserve files and see: {job.parent} | H. Developer-only log | No | No | No | `—` | — | print |
| core/update_launcher.py | 30 / `main` | The selected Python environment is missing. Restore the previous installation. | H. Developer-only log | No | No | No | `—` | — | print |
| core/update_runner.py | 125 / `apply_files` | local_changes | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/update_runner.py | 128 / `apply_files` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/update_runner.py | 185 / `finish_update` | startup_failed | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/update_runner.py | 187 / `finish_update` | startup_failed | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/update_runner.py | 189 / `finish_update` | Installation failed; restoring previous files | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| core/update_runner.py | 213 / `main` | development_checkout | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/update_runner.py | 216 / `main` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/update_runner.py | 220 / `main` | installer_running | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/update_runner.py | 233 / `main` | parent_running | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/update_runner.py | 237 / `main` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_ae_calibration.py | 52 / `calibration_candidates` | SDK AE target minimum must not exceed maximum | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_ae_calibration.py | 282 / `interpolate_sdk_target` | Calibration curve does not bracket {desired}% Effective DN | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_ae_calibration.py | 291 / `interpolate_sdk_target` | Calibration curve does not bracket {desired}% Effective DN | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_ae_calibration.py | 372 / `replace` | Invalid calibration profiles cannot be persisted | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_ae_calibration.py | 489 / `record_point` | Calibration point was not started | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_auto_exposure_settings.py | 45 / `target_effective_dn` | EffectiveDNMax must be positive | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_auto_exposure_settings_dialog.py | 43 / `__init__` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 44 / `__init__` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 46 / `__init__` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 47 / `__init__` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 48 / `__init__` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 49 / `__init__` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 50 / `__init__` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 92 / `_on_progress` | {point} /{total} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 100 / `_on_progress` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 100 / `_on_progress` | {float(exposure) / 1000.0} ms | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 103 / `_on_progress` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 103 / `_on_progress` | {gain} % | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 104 / `_on_progress` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 104 / `_on_progress` | {float(mean_dn)} /{maximum} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 109 / `_on_progress` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 109 / `_on_progress` | {float(percent)} % | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 112 / `_on_progress` | {status.get('estimated_remaining_seconds', 0)} s | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 147 / `__init__` | {percent} % | A. UI label / button / menu | Yes | No | No | `—` | — | addItem; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 162 / `__init__` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 163 / `__init__` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 164 / `__init__` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/camera_auto_exposure_settings_dialog.py | 219 / `refresh_calibration_status` | {camera} ({serial}) | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/camera_capture_bridge.py | 120 / `capture` | A camera capture request is already pending | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 146 / `capture` | Camera capture timeout at {exposure_ms} ms / Gain {gain_percent}% | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 152 / `capture` | Camera capture completed without a frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 167 / `capture` | {failure}; Camera cleanup failed: {cleanup} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 180 / `set_metering_roi` | A camera request is already pending | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 188 / `set_metering_roi` | Channel ROI setting timed out | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 204 / `_set_metering_roi` | Channel AE ROI readback verification failed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 219 / `auto_exposure` | A camera request is already pending | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 228 / `auto_exposure` | Recipe auto exposure did not converge before timeout | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 233 / `auto_exposure` | Recipe AE completed without Exposure/Gain readback | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 245 / `auto_exposure` | Recipe AE cleanup timed out | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 252 / `auto_exposure` | {failure}; Recipe AE cleanup failed: {cleanup} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 289 / `_on_auto_exposure_result` | Recipe AE result is outside verified limits | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 333 / `restore_state` | Camera state restoration timed out | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 342 / `_request_trigger_cleanup` | Camera trigger-mode cleanup timed out | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 398 / `_configure` | Camera controller does not support formal software-trigger capture | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 416 / `_configure` | Camera Exposure/Gain readback mismatch: requested={exposure_us} us/{gain_percent}%, actual={setting_exposure} us/{actual_gain}% | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 515 / `_accept_frame` | Triggered capture stream restart was not confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 525 / `_accept_frame` | Camera state changed during triggered capture: expected={expected}, actual={after} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 263 / `open_device` | Nncam.Open | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 276 / `open_device` | MONO capability check | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 520 / `close_camera` | Failed to disable SDK AE while closing calibration | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 686 / `_validate_auto_exposure_roi` | AE ROI coordinates and dimensions must be integers | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 689 / `_validate_auto_exposure_roi` | AE ROI requires x/y >= 0 and width/height > 0 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 691 / `_validate_auto_exposure_roi` | AE ROI {roi} exceeds current image {self._width}x{self._height} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 776 / `_apply_auto_exposure_roi` | %s requested=%s readback=%s verified=True | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 819 / `_set_auto_exposure_roi_failure` | %s requested=%s readback=%s verified=False error=%s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/camera_controller.py | 847 / `prepare_software_triggered_capture` | Camera is not connected | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 851 / `prepare_software_triggered_capture` | Camera does not report software-trigger support | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 862 / `prepare_software_triggered_capture` | Camera trigger mode requested 1, read back {trigger_mode} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 873 / `prepare_software_triggered_capture` | Invalid camera real exposure: {real_exposure_us} us | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 891 / `triggered_capture_readback` | Software-trigger capture is not active | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 902 / `trigger_single_frame` | Software-trigger capture is not prepared | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 919 / `finish_software_triggered_capture` | Camera video mode requested 0, read back {readback} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 925 / `finish_software_triggered_capture` | Trigger cleanup ROI verification failed: {self._auto_exposure_roi_error} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 950 / `switch_to_manual_exposure` | Failed to restore SDK AE after manual switch failure | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 1148 / `start_ae_calibration` | NNCAM_OPTION_AUTOEXP_POLICY must read back Exposure Preferred (1) | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1152 / `start_ae_calibration` | NNCAM_OPTION_AUTOEXPOSURE_PERCENT must read back full active AE ROI average (100) | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1284 / `_log_ae_calibration_point` | SDK_AE_CAL_POINT timestamp=%s camera_serial=%s resolution=%s sdk_target=%s target_readback=%s converged=%s exposure_us=%s gain_percent=%s mean_dn=%s dn_max=%s dn_percent=%s saturated=%s low_signal=%s convergence_source=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1324 / `_finish_ae_calibration` | SDK_AE_CAL_RESULT timestamp=%s camera_serial=%s resolution=%s profile_id=%s %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1338 / `_finish_ae_calibration` | Failed to restore prior AE profile after calibration failure | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 1359 / `_abort_ae_calibration` | Failed to leave SDK AE off after calibration abort | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 1430 / `_write_nonblocking_sdk_option` | %s readback mismatch: requested=%s actual=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1437 / `_write_nonblocking_sdk_option` | %s requested/readback=%s/%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1440 / `_write_nonblocking_sdk_option` | %s unsupported or unavailable: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1462 / `_write_sdk_auto_exposure_target_value` | SDK AutoExpoTarget readback mismatch: requested=%s actual=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1468 / `_write_sdk_auto_exposure_target_value` | SDK AutoExpoTarget requested/readback=%s/%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1476 / `_start_native_auto_exposure` | Camera is not connected | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1483 / `_enable_sdk_auto_exposure` | Camera is not connected | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1485 / `_enable_sdk_auto_exposure` | SDK AE cannot be enabled until AEAuxRect readback is verified | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1489 / `_enable_sdk_auto_exposure` | SDK AE enable mode must be Continuous or Once | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1496 / `_enable_sdk_auto_exposure` | SDK AutoExpoEnable requested {enable_value}, read back {readback} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1519 / `_disable_sdk_auto_exposure` | SDK AutoExpoEnable requested 0, read back {readback} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1544 / `_log_sdk_ae_calibration` | SDK_AE_CALIBRATION timestamp=%s reason=%s UserTargetPercent=%s%% EffectiveDNTarget=%s/%s SDKAutoExposureTarget=%s SDKAutoExposureTargetReadback=%s SDKAutoExposureMode=%s AutoExposureCalibrationApplied=%s CalibrationProfileId=%s ExposureReadbackUs=%s GainReadback=%s MeanEffectiveDN=%s MeanEffectiveDNPercent=%s MeteringMeanEffectiveDN=%s MeteringMeanEffectiveDNPercent=%s AEROI=%s AEROIVerified=%s Alignment=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1792 / `read_temperature_c` | Camera temperature query must run in the camera owner thread | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1794 / `read_temperature_c` | NNCAM_FLAG_GETTEMPERATURE is not present for this camera | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1819 / `_query_optional` | RisingCam SDK query failed for %s: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1893 / `_log_camera_capabilities` | Camera Model: %s Camera Serial: %s Camera flags: 0x%X Mono: %s RAW10/11/12/14/16 flags: %s/%s/%s/%s/%s Resolution: %sx%s SDK version: %s MaxBitDepth: %s Sensor bit depth: %s BitDepthSource: %s ScientificPixelFormat: %s ScientificFormatNegotiation: %s BITDEPTH requested/readback: 1/%s RGB requested/readback/fallback: 4/%s/%s RGB option 4 supported: %s BYTEORDER diagnostic: readback=%s, IgnoredForMono=True LINEAR/CURVE/Gamma requested: 0/0/100 LINEAR/CURVE/Gamma readback: %s/%s/%s ScientificISPBypassed: %s RAW mode: %s ISP mode: %s Pull bits: %s StartPullMode status: %s ScientificContainer: %s ScientificChannels: %s ContainerBitDepth: 16 ScientificFrameValidated: %s ScientificMeasurementReady: %s PixelFormat diagnostic: %s (%s) RawValueAlignment/source: %s/%s EffectiveDNMax: %s Camera Exposure Hardware Range: min = %s us, max = %s us, default = %s us Camera Gain Hardware Range: min = %s %%, max = %s %%, default = %s %% Auto Exposure Range: min exposure = %s us, max exposure = %s us, min gain = %s %%, max gain = %s %% Auto Exposure Controller/mode/user target: RisingCamSDK/%s/%s %% SDK Auto Exposure target requested/readback: %s/%s SDK Auto Exposure policy/full-active-AE-ROI percent: %s/%s SDK Auto Exposure exposure/gain damping: %s/%s SDK Overexposure policy: %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 2028 / `_read_sensor_bit_depth` | unexpected MaxBitDepth value: {bit_depth} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2029 / `_read_sensor_bit_depth` | Camera startup OK: MaxBitDepth() -> %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 2034 / `_read_sensor_bit_depth` | RisingCam MaxBitDepth() failed (%s); using capability-flag fallback: %s bits | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2041 / `_read_sensor_bit_depth` | RisingCam MaxBitDepth() failed (%s) and no RAW10/11/12/14/16 capability flag is available; SensorBitDepth=Unknown | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2055 / `_apply_camera_startup_setting` | Camera startup OK: %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 2057 / `_apply_camera_startup_setting` | Camera startup OK: %s -> %r | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 2060 / `_apply_camera_startup_setting` | Camera startup FAILED at %s: %s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 2079 / `_configure_mono16_bitdepth` | Camera startup FAILED at NNCAM_OPTION_BITDEPTH readback: %s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/camera_controller.py | 2083 / `_configure_mono16_bitdepth` | NNCAM_OPTION_BITDEPTH readback | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2098 / `_negotiate_mono16_rgb_option` | RGB=4 negotiation failed at %s; using PullImageV4(bits=16): %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2114 / `_negotiate_mono16_rgb_option` | RGB=4 negotiation readback mismatch (requested=4, readback=%r); using PullImageV4(bits=16) | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2137 / `_configure_nonblocking_option` | Camera startup NON-BLOCKING setting failed at %s: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2150 / `_configure_nonblocking_option` | Camera startup NON-BLOCKING readback mismatch at %s: requested=%s, readback=%r | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2169 / `_configure_nonblocking_gamma` | Camera startup NON-BLOCKING setting failed at %s: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2179 / `_configure_nonblocking_gamma` | Camera startup NON-BLOCKING readback mismatch at Gamma: requested=%s, readback=%r | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2194 / `_read_nonblocking_setting` | Camera startup diagnostic: %s -> %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 2197 / `_read_nonblocking_setting` | Camera startup diagnostic unavailable at %s: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2225 / `_verify_top_down_rows` | NNCAM_OPTION_UPSIDE_DOWN readback | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2234 / `_start_stream` | Scientific format validation | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2263 / `_start_stream` | {failure}; stream cleanup failed: {cleanup} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2318 / `_handle_sdk_event` | SDK AE convergence Exposure/Gain readback failed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2360 / `_handle_sdk_event` | Failed to disable SDK AE after convergence failure | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 2365 / `_handle_sdk_event` | RisingCam SDK reported auto exposure convergence failure | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2381 / `_update_alignment_verification` | DN alignment runtime evidence: state=%s frames=%s sampled=%s nonzero=%s above_right_max=%s (%.6f) low_bits_zero_ratio=%.6f nonzero_low_bits=%s patterns=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 2409 / `_update_alignment_verification` | DN alignment runtime verified: alignment=%s source=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 2451 / `_pull_live_frame` | MONO16 buffer validation | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2464 / `_pull_live_frame` | PullImageV4(bits=16) | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2475 / `_pull_live_frame` | PullImageV4(bits=16) output validation | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2486 / `_pull_live_frame` | Camera scientific frame validation: PullBits=16 PixelFormat=%s ContainerBitDepth=16 Scientific frame dtype=%s Scientific frame ndim=%s Scientific frame shape=%s Pitch=%s BufferSize=%s ScientificFormatNegotiation=%s ScientificFrameValidated=True ScientificMeasurementReady=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 2633 / `_pull_live_frame` | Camera scientific frame validation failed: %s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 2730 / `_poll_camera_status` | RisingCam SDK failed to refresh current Exposure/Gain | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_exposure.py | 22 / `validate_official_exposure_us` | Exposure must be within the official IUA8300KMB range {OFFICIAL_EXPOSURE_MIN_US}–{OFFICIAL_EXPOSURE_MAX_US} us; got {value} us | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 42 / `_reapply_recipe_roi` | {stage}: AE ROI verification failed; requested={requested}; readback={controller._auto_exposure_roi_readback}; {controller._auto_exposure_roi_error} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 86 / `verify_recipe_ae_configuration` | Recipe AE limits changed: expected={expected_range}, actual={actual_range} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 94 / `verify_recipe_ae_configuration` | Recipe AE option {option} changed: expected={expected}, actual={actual} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 97 / `verify_recipe_ae_configuration` | Recipe AE target changed: expected={metadata['RecipeAESDKTarget']}, actual={target} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 115 / `_seed_within_limits` | Recipe AE initial Exposure/Gain readback mismatch: requested={(requested_exposure, requested_gain)}, actual={actual} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 174 / `recipe_ae_failure_context` | RECIPE_AE_FAILURE_CONTEXT %s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/camera_recipe_ae.py | 184 / `_read_ae_range` | {stage}: Invalid AE limits {(max_time, min_time, max_gain, min_gain)} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 192 / `_write_ae_range` | {stage}: Requested limits exceed native SDK AE capabilities: {requested} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 207 / `_write_ae_range` | {stage}: AE range readback mismatch; requested={requested}, actual={actual} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 213 / `restore_recipe_ae` | Camera disconnected during Recipe AE cleanup | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 234 / `restore_recipe_ae` | Recipe AE option restoration readback mismatch | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 237 / `restore_recipe_ae` | Recipe AE target restoration readback mismatch | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 262 / `begin_recipe_ae` | Recipe AE requires Once or Continuous mode | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 265 / `begin_recipe_ae` | Recipe AE requires a connected, available camera | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 267 / `begin_recipe_ae` | Invalid Recipe AE gain mode | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 269 / `begin_recipe_ae` | Recipe AE requires a verified channel metering ROI | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 294 / `begin_recipe_ae` | Recipe AE exposure capabilities are unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 296 / `begin_recipe_ae` | Recipe AE maximum exposure is outside camera capabilities | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 306 / `begin_recipe_ae` | Recipe AE fixed Gain is outside camera capabilities | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 312 / `begin_recipe_ae` | Recipe AE Gain limits do not intersect hardware capabilities | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 331 / `begin_recipe_ae` | Recipe AE policy/metering readback mismatch | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_recipe_ae.py | 334 / `begin_recipe_ae` | Recipe AE target readback mismatch | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_sdk_diagnostics.py | 46 / `sdk_call` | CAMERA_SDK_CALL %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_sdk_diagnostics.py | 51 / `sdk_call` | CAMERA_SDK_FAILED %s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_temperature_monitor.py | 133 / `start` | Camera temperature monitor started path=%s model=%s identifier=%s interval_ms=%d | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_temperature_monitor.py | 157 / `stop` | Camera temperature monitor stopped path=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_temperature_monitor.py | 169 / `poll_now` | camera temperature is unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_temperature_monitor.py | 172 / `poll_now` | invalid camera temperature value: {value} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_temperature_monitor.py | 265 / `_mark_unsupported` | Camera temperature API unsupported: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_temperature_monitor.py | 276 / `_log_read_failure` | Camera temperature read unavailable; polling will continue: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/dark_iv_chart.py | 101 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/dark_iv_chart.py | 102 / `__init__` | 0 / 0 | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/dark_iv_chart.py | 103 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/dark_iv_chart.py | 104 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/dark_iv_chart.py | 157 / `reset` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/dark_iv_chart.py | 158 / `reset` | 0 / 0 | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/dark_iv_chart.py | 159 / `reset` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/dark_iv_chart.py | 160 / `reset` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/dark_iv_chart.py | 196 / `add_point` | {self._channel} — {self._sample_id} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/dark_iv_chart.py | 197 / `add_point` | {progress.current} / {progress.total} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/dark_iv_chart.py | 198 / `add_point` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/dark_iv_chart.py | 203 / `add_point` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/dark_iv_chart.py | 337 / `save_dark_iv_plot_png` | Could not save Dark I-V PNG: {output} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/dark_iv_chart.py | 339 / `save_dark_iv_plot_png` | Dark I-V PNG is empty: {output} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_hardware.py | 17 / `relay_channel_id` | Unsupported logical channel: {logical_channel} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_hardware.py | 40 / `_verify_gsp4h_dark` | GSP4H Light OFF could not be verified | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_hardware.py | 46 / `prepare_shared_dark` | White Light OFF could not be verified for Shared Dark | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_hardware.py | 70 / `verified_light_off` | White Light OFF verification failed after polarity | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_hardware.py | 93 / `prepare_channel_dark` | White Light OFF could not be verified for channel Dark I-V | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_hardware.py | 102 / `run_dark_iv` | Dark I-V step must be greater than zero | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_hardware.py | 119 / `run_dark_iv` | Dark I-V requires a confirmed polarity factor | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_plan.py | 202 / `captures` | Automatic exposure capture settings are resolved at runtime | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 278 / `__init__` | Measurement snapshot execution order does not match the runtime plan | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 305 / `check_cancel` | Runtime watchdog: max_recipe_time_s exceeded | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 310 / `check_cancel` | Runtime watchdog: max_output_time_s exceeded for electrical setpoint | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 367 / `run` | {failure}; Safe shutdown failed: {cleanup} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 376 / `run` | Safe shutdown did not satisfy every post-processing gate | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 378 / `run` | Hardware measurement ended without a result | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 399 / `_record_failure` | MEASUREMENT_FAILED %s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/el_matrix_runner.py | 405 / `_record_failure` | Could not save measurement failure diagnostics | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/el_matrix_runner.py | 425 / `_run_all_polarities` | {channel.channel} polarity could not be reliably determined | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 590 / `_run_channel` | Recipe AE returned invalid Exposure/Gain | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 596 / `_run_channel` | Recipe AE baseline cannot accommodate the requested Stop list | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 652 / `_run_channel` | {failure}; Channel cleanup failed: {cleanup} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 662 / `_save_dark_iv` | {channel.channel} Dark I-V polarity metadata is inconsistent | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 765 / `_capture_and_save` | Recipe ROI source resolution changed during measurement | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/emergency_manager.py | 72 / `begin_operator_operation` | EMERGENCY reset by explicit operator operation generation=%d | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/emergency_manager.py | 98 / `trigger` | GLOBAL_EMERGENCY timestamp=%s workflow=%s generation=%d smu_before=%s white_light_before=%s | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/emergency_manager.py | 121 / `trigger` | GLOBAL_EMERGENCY SMU shutdown request failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/emergency_manager.py | 134 / `trigger` | GLOBAL_EMERGENCY White Light shutdown failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/emergency_manager.py | 158 / `trigger` | GLOBAL_EMERGENCY SMU routing shutdown failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/emergency_manager.py | 168 / `trigger` | GLOBAL_EMERGENCY GSP4H shutdown failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/emergency_manager.py | 174 / `trigger` | GLOBAL_EMERGENCY action=%s success | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/emergency_manager.py | 178 / `trigger` | GLOBAL_EMERGENCY action=%s failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/emergency_manager.py | 189 / `trigger` | GLOBAL_EMERGENCY completed generation=%d actions=%s failures=%s final_smu=%s | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/error_center/error_detail_panel.py | 13 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/error_center/error_detail_panel.py | 14 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/error_center/error_detail_panel.py | 16 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/error_center/error_detail_panel.py | 17 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/error_center/error_detail_panel.py | 64 / `_retranslate` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/instrument_state_manager.py | 306 / `_publish` | SMU_UI_STATE %s -> %s owner=%s operation=%s output=%s confirmed_off=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/instrument_state_manager.py | 316 / `_publish` | SMU_UNEXPECTED_OUTPUT_ON owner=%s operation=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/keysight_b2900.py | 51 / `configure_zero_level_measurement` | Source and measurement functions must be different | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 63 / `configure_zero_level_measurement` | B2900_MEASUREMENT_CONFIG source_mode=%s measurement_mode=%s range=AUTO nplc_auto=%s nplc=%s compliance=%g source_level=0 | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/keysight_b2900.py | 77 / `_source_function` | Source mode must be CURR or VOLT | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 85 / `_configure_source_mode` | OUTPUT OFF was not confirmed before source-mode change | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 88 / `_configure_source_mode` | B2900_SOURCE_MODE requested=%s readback=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/keysight_b2900.py | 95 / `_configure_source_mode` | B2900 source-mode verification failed: requested {requested}, read back {readback or 'UNKNOWN'}, system error {error} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 102 / `_configure_source_mode` | B2900_SOURCE_MODE_CONFIGURATION_FAILED requested=%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/keysight_b2900.py | 125 / `_set_and_verify_source_level` | B2900 {source} source-level verification failed: requested {numeric}, read back {readback} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 167 / `_nplc_function` | Measurement NPLC mode must be CURR or VOLT | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 187 / `set_measurement_nplc` | B2900 NPLC must be between 0.001 and 100 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 222 / `safe_stop` | B2900_SAFE_STOP source-level zero failed after OUTPUT OFF command=%s error=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/light_panel.py | 253 / `_export` | FILE-201 | F. User-facing error | No | No | No | `—` | — | signal self.service.failed.emit |
| gui/light_service.py | 101 / `channel_name` | Channel must be an integer from 1 to 4 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/light_service.py | 106 / `set_channel_name` | Channel must be an integer from 1 to 4 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/light_service.py | 228 / `save` | CFG-101 | F. User-facing error | No | No | No | `—` | — | signal self.failed.emit |
| gui/light_service.py | 263 / `_completed` | COMM-203 \| COMM-201 | F. User-facing error | No | No | No | `—` | — | signal self.failed.emit |
| gui/light_service.py | 289 / `_connection_fault` | COMM-203 | F. User-facing error | No | No | No | `—` | — | signal self.failed.emit |
| gui/log_export.py | 41 / `create_log_zip` | The log archive must have a .zip extension | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/log_export.py | 113 / `run` | Log ZIP export failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/main_window_close.py | 32 / `closeEvent` | Manual SMU settings flush failed during application close | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/main_window_close.py | 50 / `closeEvent` | FORCED_APPLICATION_EXIT_WITH_UNCONFIRMED_SMU_OUTPUT | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/main_window_close.py | 54 / `closeEvent` | Forced-exit emergency cleanup failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/main_window_close.py | 91 / `closeEvent` | Software update handoff failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/main_window_devices.py | 303 / `on_camera_opened` | {width} × {height} | A. UI label / button / menu | Yes | No | No | `—` | — | addItem; canonical technical/value display |
| gui/main_window_devices.py | 393 / `on_camera_closed` | FPS — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 394 / `on_camera_closed` | N/A | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 397 / `on_camera_closed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 398 / `on_camera_closed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 401 / `on_camera_closed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 402 / `on_camera_closed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 403 / `on_camera_closed` | Unknown | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 473 / `on_exposure_changed` | {exposure_us / 1000.0} ms | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 474 / `on_exposure_changed` | {gain} % | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 483 / `on_exposure_status_changed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 484 / `on_exposure_status_changed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 488 / `on_exposure_status_changed` | {exposure_us / 1000.0} ms | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 489 / `on_exposure_status_changed` | {gain} % | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 526 / `on_effective_dn_status_changed` | Unknown | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 526 / `on_effective_dn_status_changed` | {sensor_bits}-bit | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 541 / `on_effective_dn_status_changed` | Unknown | A. UI label / button / menu | Yes | No | No | `—` | — | indirect presentation assignment alignment_text; canonical technical/value display |
| gui/main_window_devices.py | 543 / `on_effective_dn_status_changed` | {round(float(mean_dn))} /{int(maximum)} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 548 / `on_effective_dn_status_changed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 548 / `on_effective_dn_status_changed` | {float(percent)} % | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 551 / `on_effective_dn_status_changed` | {target_percent} % | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 553 / `on_effective_dn_status_changed` | {int(target_dn)} /{int(maximum)} | A. UI label / button / menu | Yes | No | No | `—` | — | indirect presentation assignment target_text; canonical technical/value display |
| gui/main_window_devices.py | 581 / `on_frame_ready` | {image.width()} × {image.height()} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 702 / `_refresh_live_view_roi_dn` | EffectiveDNMax must be positive | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/main_window_devices.py | 934 / `on_temperature_availability_changed` | N/A | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_measurement.py | 70 / `start_background_measurement` | Measurement is already running | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/main_window_measurement.py | 721 / `run` | Pixel CSV blocked: safe shutdown was not fully verified | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/main_window_ui.py | 268 / `_build_central_ui` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 269 / `_build_central_ui` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 275 / `_build_central_ui` | {self.controller.auto_exposure_target_percent} % | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 298 / `_build_central_ui` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 299 / `_build_central_ui` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 300 / `_build_central_ui` | Unknown | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 317 / `_build_central_ui` | Sensor | A. UI label / button / menu | Yes | No | No | `—` | — | addRow; canonical technical/value display |
| gui/main_window_ui.py | 318 / `_build_central_ui` | Alignment | A. UI label / button / menu | Yes | No | No | `—` | — | addRow; canonical technical/value display |
| gui/main_window_ui.py | 325 / `_build_central_ui` | N/A | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 339 / `_build_central_ui` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 340 / `_build_central_ui` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 341 / `_build_central_ui` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 345 / `_build_central_ui` | SDK | A. UI label / button / menu | Yes | No | No | `—` | — | addRow; canonical technical/value display |
| gui/main_window_ui.py | 597 / `_retranslate_ui` | {self.last_image.width()} × {self.last_image.height()} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_ui.py | 682 / `_build_status_bar` | SMU — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/manual_smu_settings.py | 147 / `save` | Manual SMU settings readback verification failed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/manual_smu_settings.py | 151 / `save` | Manual SMU settings readback verification failed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/manual_smu_settings.py | 160 / `_raise_for_status` | Manual SMU settings {operation} failed: {status_name} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/manual_smu_settings.py | 204 / `_qsettings_factory` | settings_factory is required for non-QSettings persistence backends | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/manual_smu_settings.py | 217 / `_qsettings_factory` | QSettings persistence backend has no storage identity | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_control_bar.py | 46 / `__init__` | Recipe | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_control_bar.py | 70 / `retranslate` | Recipe | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_execution_plan.py | 122 / `_matrix_channel_steps` | Dark IV | A. UI label / button / menu | Yes | No | No | `—` | — | ExecutionStep; canonical technical/value display |
| gui/measurement_execution_plan.py | 133 / `_matrix_channel_steps` | EL Matrix | A. UI label / button / menu | Yes | No | No | `—` | — | ExecutionStep; canonical technical/value display |
| gui/measurement_execution_plan.py | 194 / `_output_steps` | Raw DN | A. UI label / button / menu | Yes | No | No | `—` | — | _leaf; canonical technical/value display |
| gui/measurement_execution_plan.py | 244 / `build_measurement_execution_plan` | Channels | A. UI label / button / menu | Yes | No | No | `—` | — | ExecutionStep; canonical technical/value display |
| gui/measurement_output.py | 225 / `write_mono_array_csv_atomic` | Scientific Pixel CSV requires an H×W mono array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 227 / `write_mono_array_csv_atomic` | Pixel CSV value header must identify the scientific value | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 256 / `save_pixel_csv_products` | Raw Pixel CSV requires a uint16 H×W scientific array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 259 / `save_pixel_csv_products` | Shared Dark must be a shape-matched uint16 H×W array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 268 / `save_pixel_csv_products` | Dark-corrected Pixel CSV requires a matching Shared Dark frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 274 / `save_pixel_csv_products` | Exposure-normalized Pixel CSV requires a matching Shared Dark frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 276 / `save_pixel_csv_products` | Exposure normalization requires exposure_ms > 0 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 296 / `scientific_to_visualization` | Scientific camera source must use a uint16 container | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 299 / `scientific_to_visualization` | SensorBitDepth must be between 1 and 16 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 323 / `scientific_to_visualization` | RawValueAlignment must be 'right', 'left', or 'unknown' | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 328 / `scientific_to_visualization` | Scientific image must be H×W or H×W×3 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 334 / `save_scientific_tiff` | TIFF scientific master requires uint16 source data | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 337 / `save_scientific_tiff` | Scientific image must be H×W or H×W×3 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 350 / `save_matrix_capture` | Scientific frame is unavailable; refusing to create TIFF from Live View | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 355 / `save_matrix_capture` | Camera acquisition must provide a uint16 scientific frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 410 / `save_matrix_capture` | Derived output generation modified the scientific source buffer | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_progress_dialog.py | 57 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 58 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 59 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 60 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 61 / `__init__` | 0 / 0 | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 62 / `__init__` | 0.0% | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 63 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 64 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 65 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 162 / `update_progress` | {progress.channel_index} / {progress.channel_total} — {progress.channel} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 186 / `update_progress` | {progress.channel_completed} / {progress.channel_capture_total} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 186 / `update_progress` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 190 / `update_progress` | {progress.current} / {progress.total} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 192 / `update_progress` | {percent}% | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 195 / `update_progress` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 208 / `update_postprocess_progress` | {progress.current} / {progress.total} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 209 / `update_postprocess_progress` | {progress.percent}% | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 212 / `update_postprocess_progress` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 242 / `set_complete` | {total} / {total} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 243 / `set_complete` | 100.0% | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_snapshot.py | 170 / `save_el_matrix_snapshot` | Measurement Snapshot SHA-256 verification failed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_worker.py | 59 / `execute` | MEASUREMENT_WORKER_FAILED | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/measurement_worker.py | 66 / `execute` | {'; '.join(fields)}; {exc} | F. User-facing error | No | No | No | `—` | — | signal self.failed.emit |
| gui/measurement_worker.py | 91 / `report_progress` | current and total are required for text progress | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/numeric.py | 18 / `decimal_from_number` | Invalid numeric value: {value} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/numeric.py | 20 / `decimal_from_number` | Numeric value must be finite: {value} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/numeric.py | 46 / `normalize_json_numbers` | Recipe values must be finite | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/pixel_csv_postprocessor.py | 113 / `run` | Pixel CSV is blocked until safe shutdown is fully verified | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/pixel_csv_postprocessor.py | 296 / `_process_job` | Shared Dark shape {dark.shape} does not match source shape {source.shape}: {source_path} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/pixel_csv_postprocessor.py | 308 / `_process_job` | Exposure normalization requires Exposure > 0 ms | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/pixel_csv_postprocessor.py | 334 / `_validate_scientific_array` | Scientific TIFF must contain uint16 pixels, got {array.dtype}: {path} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/pixel_csv_postprocessor.py | 338 / `_validate_scientific_array` | Scientific TIFF must be H×W mono, got shape {array.shape}: {path} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 97 / `measure` | Device area must be greater than 0 cm² | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 141 / `measure` | POLARITY_JSC raw_current_a=%s sample_area_cm2=%g current_density_ma_cm2=%+.9g compliance_a=%g | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/polarity_measurement.py | 175 / `measure` | POLARITY_VOC samples_v=%s representative_v=%+.9g compliance_v=%g | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/polarity_measurement.py | 227 / `measure` | POLARITY_%s samples=%s representative=%s minimum=%s maximum=%s range=%s standard_deviation=%s variation_percent=%s maximum_variation_percent=%s nplc=%s aggregation=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/polarity_measurement.py | 243 / `measure` | POLARITY_MEASUREMENT_FAILED reason=%s details=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/polarity_measurement.py | 246 / `measure` | POLARITY_MEASUREMENT_EXCEPTION partial_results=%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/polarity_measurement.py | 258 / `measure` | White Light OFF completed after polarity cancellation | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/polarity_measurement.py | 272 / `analyze` | {label} contains missing or invalid samples | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 281 / `analyze` | {label} sample signs are inconsistent | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 301 / `analyze` | {label} representative is below the configured minimum | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 313 / `analyze` | {label} variation {variation}% exceeds {maximum_variation_percent}% | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 337 / `_integration_context` | SMU driver does not support temporary NPLC; polarity sampling continues without changing integration | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/polarity_measurement.py | 366 / `_measurement_configuration` | POLARITY_MEASUREMENT_CONFIG source_mode=%s measurement_mode=%s nplc=%g nplc_auto=OFF range=AUTO driver_specific=false | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/polarity_measurement.py | 393 / `_sample_output` | Temporary measurement OUTPUT ON was not confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 408 / `_sample_output` | Temporary measurement OUTPUT OFF was not confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_ae_stops.py | 19 / `stop_factors` | Stop list requires 1–33 unique finite numbers between -12 and +12 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_ae_stops.py | 31 / `baseline_range_us` | AE exposure ceiling is outside camera capabilities | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_ae_stops.py | 35 / `baseline_range_us` | Stop list leaves no valid AE baseline exposure range | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_ae_stops.py | 45 / `native_baseline_range_us` | Stop list leaves no valid baseline within native SDK AE limits | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_ae_stops.py | 52 / `bracket_exposures_us` | Stop entries resolve to duplicate exposures at camera microsecond precision | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_dialog.py | 53 / `__init__` | {width} × {height} | A. UI label / button / menu | Yes | No | No | `—` | — | addItem; canonical technical/value display |
| gui/recipe_dialog_logic.py | 41 / `_parse_finite_numbers` | {field_name} 必須是以逗號或分號分隔的有限數值 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_dialog_logic.py | 45 / `_parse_finite_numbers` | {field_name} 不可空白 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_dialog_logic.py | 47 / `_parse_finite_numbers` | {field_name} 不可包含 NaN 或 Inf | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_dialog_logic.py | 70 / `_show_recipe_operation_failure` | Recipe %s failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/recipe_dialog_logic.py | 136 / `_write_recipe_to_form` | {channel.area_cm2} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/recipe_dialog_pages.py | 64 / `_build_basic_tab` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/recipe_dialog_pages.py | 65 / `_build_basic_tab` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/recipe_dialog_pages.py | 202 / `_build_el_matrix_tab` | {value} % | A. UI label / button / menu | Yes | No | No | `—` | — | addItem; canonical technical/value display |
| gui/recipe_roi.py | 16 / `validate_roi` | ROI requires four integer image-pixel coordinates | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_roi.py | 19 / `validate_roi` | ROI {values} is outside source image {width}x{height} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_roi.py | 28 / `validate_channel_rois` | Recipe ROI channels must be CH1 through CH4 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_roi.py | 30 / `validate_channel_rois` | Every enabled channel must have its own ROI | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_roi.py | 36 / `crop_channel_frame` | Recipe ROI requires a uint16 H×W scientific frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_roi_excitation.py | 176 / `prepare` | RECIPE_EL_ROI_READY channel=%s details=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/recipe_roi_excitation.py | 198 / `run` | RECIPE_EL_ROI_FAILED | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/recipe_store.py | 36 / `_dataclass_from_dict` | {cls.__name__} must be a JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 566 / `from_dict` | Recipe must be a JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 568 / `from_dict` | Legacy Recipe safety/SMU values were detected and ignored; they did not override application-wide safety settings | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/recipe_store.py | 573 / `from_dict` | Legacy HDR configuration was removed and ignored. | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/recipe_store.py | 678 / `from_dict` | Legacy voltage-driven EL points cannot be represented exactly by the current-density Matrix; default Matrix points were retained | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/recipe_store.py | 709 / `from_dict` | Legacy per-row EL points expanded into Matrix axes; Recipe was migrated as draft for operator review | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/recipe_store.py | 725 / `from_dict` | Legacy Recipe Sample IDs were ignored; enter them in the Main Window | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/recipe_store.py | 797 / `load` | Recipe repository root must be a JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 800 / `load` | schema_version must be an integer | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 802 / `load` | Recipe schema {schema} is newer than supported schema {self.schema_version} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 807 / `load` | recipes must be a JSON array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 810 / `load` | Every Recipe entry must be a JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 813 / `load` | 無法讀取 Recipe 檔案：{exc} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 819 / `import_payload` | 匯入檔案頂層必須是 JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 822 / `import_payload` | 匯入檔案必須包含有效的整數 schema_version | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 824 / `import_payload` | Recipe schema_version={schema} 高於目前支援版本 {self.schema_version}，拒絕匯入 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 829 / `import_payload` | 匯入檔案必須包含 recipe JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 855 / `import_payload` | Recipe.{section} 必須是 JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 864 / `import_payload` | Recipe.channels 必須是 JSON array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 868 / `import_payload` | Recipe.channels[{index}] 必須是 JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 180 / `refresh_connection` | Relay HID open failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_controller.py | 193 / `disconnect` | Failed to close relay HID device | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_controller.py | 216 / `refresh_hardware_state` | R00 raw feature report (len=%s): %s \| %s | H. Developer-only log | No | No | No | `—` | — | logger.debug |
| gui/relay_controller.py | 221 / `refresh_hardware_state` | R00 state_mask=0x%02X (0b%s) | H. Developer-only log | No | No | No | `—` | — | logger.debug |
| gui/relay_controller.py | 226 / `refresh_hardware_state` | Relay hardware state read failed \| %s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_controller.py | 259 / `set_channel` | %s \| CH%s %s requested \| %s | H. Developer-only log | No | No | No | `—` | — | logger.debug |
| gui/relay_controller.py | 260 / `set_channel` | HID feature report: %s \| transport type=FEATURE_REPORT | H. Developer-only log | No | No | No | `—` | — | logger.debug |
| gui/relay_controller.py | 264 / `set_channel` | send_feature_report return value: %s | H. Developer-only log | No | No | No | `—` | — | logger.debug |
| gui/relay_controller.py | 267 / `set_channel` | send_feature_report failed: return=%s hid_error=%s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/relay_controller.py | 268 / `set_channel` | send_feature_report failed：return={sent}, hid_error={hid_error} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 271 / `set_channel` | CH%s %s command failed \| %s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_controller.py | 274 / `set_channel` | CH{channel} command send failed：{exc} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 282 / `set_channel` | command sent but state verification failed \| CH%s expected=%s reason=%s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/relay_controller.py | 283 / `set_channel` | CH{channel} command sent but state verification failed：{exc} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 289 / `set_channel` | command sent but state verification failed \| CH%s expected=%s actual=%s raw=%s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/relay_controller.py | 293 / `set_channel` | CH{channel} command sent but state verification failed：expected {requested.value}, actual {actual.value} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 297 / `set_channel` | Relay command verified \| CH%s state=%s | H. Developer-only log | No | No | No | `—` | — | logger.debug |
| gui/relay_controller.py | 369 / `_record` | Relay \| %s \| %s \| %s \| %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 392 / `_channel` | CH{channel} {requested} failed：{exc} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 415 / `_group_on_unlocked` | Relay controller state mismatch：mask=0x{state_mask}, expected ON mask=0x{group_mask} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 423 / `_group_on_unlocked` | Relay rollback failed for CH%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_controller.py | 425 / `_group_on_unlocked` | {selected.display_name} ON failed; rollback attempted：{exc} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 426 / `_group_on_unlocked` | %s relay controller state verified=ON \| mask=0x%02X | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 457 / `_group_off_unlocked` | %s relay controller state verified=OFF \| mask=0x%02X | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 485 / `_safe_white_light_off_unlocked` | White Light OFF skipped: USBRelay8 not connected \| source=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/relay_controller.py | 493 / `_safe_white_light_off_unlocked` | Relay controller state mismatch：mask=0x{state_mask}, expected 0x00 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 495 / `_safe_white_light_off_unlocked` | White Light relay controller OFF verification failed \| source=%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_controller.py | 497 / `_safe_white_light_off_unlocked` | White Light relay controller OFF verified \| mask=0x%02X source=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 514 / `select_smu_output_channel` | SMU OUTPUT OFF was not authoritatively confirmed; routing is blocked | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 525 / `select_smu_output_channel` | SMU_ROUTING REQUEST channel=%s mapped_relay=%d state_before=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 539 / `select_smu_output_channel` | SMU routing all-OFF verification failed: mask=0x{all_off_mask} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 542 / `select_smu_output_channel` | SMU_ROUTING BREAK verified_all_off mask=0x%02X | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 551 / `select_smu_output_channel` | SMU routing target verification failed: expected={channel_id}/Relay {target_relay}, actual={active or 'none'}, mask=0x{after_mask} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 563 / `select_smu_output_channel` | SMU_ROUTING MAKE verified channel=%s relay=%d state_after=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 588 / `clear_smu_output_channels` | SMU_ROUTING all OFF verified mask=0x%02X source=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 597 / `_safe_smu_output_channels_off_unlocked` | SMU routing OFF skipped: USBRelay8 not connected \| source=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/relay_controller.py | 608 / `_safe_smu_output_channels_off_unlocked` | SMU routing OFF verification failed source=%s failures=%s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/relay_controller.py | 610 / `_safe_smu_output_channels_off_unlocked` | SMU routing OFF verified mask=0x%02X source=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 622 / `active_smu_output_channel` | SMU routing state is unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 696 / `_assert_routing_mutual_exclusion_unlocked` | routing fault handler must raise | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 701 / `_latch_routing_fault_unlocked` | %s source=%s | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/relay_controller.py | 709 / `_latch_routing_fault_unlocked` | SMU routing fault handler failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_controller.py | 719 / `shutdown` | SMU routing OFF failed during RelayService shutdown | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_controller.py | 724 / `shutdown` | White Light OFF failed during RelayService shutdown | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_settings_dialog.py | 117 / `_build_ui` | Relay {relay_number} | A. UI label / button / menu | Yes | No | No | `—` | — | addItem; canonical technical/value display |
| gui/scientific_dn.py | 16 / `effective_dn_max` | SensorBitDepth must be between 1 and 16 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 31 / `_validated_source` | Scientific DN source must be a uint16 ndarray | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 33 / `_validated_source` | Scientific DN source must be an H×W array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 35 / `_validated_source` | Bit depths must satisfy 1 <= SensorBitDepth <= ContainerBitDepth <= 16 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 39 / `_validated_source` | RawValueAlignment must be 'right', 'left', or 'unknown' | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 41 / `_validated_source` | RawValueAlignment is unknown | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 65 / `scientific_to_effective_dn` | Scientific container contains values outside Effective DN range | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 84 / `mean_effective_dn` | Scientific DN source cannot be empty | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 88 / `mean_effective_dn` | Scientific container contains values outside Effective DN range | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 116 / `mean_effective_dn_roi` | Scientific DN source must be a uint16 ndarray | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 118 / `mean_effective_dn_roi` | Scientific DN source must be an H×W array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 121 / `mean_effective_dn_roi` | ROI coordinates must be non-negative | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 123 / `mean_effective_dn_roi` | ROI width and height must be positive | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 125 / `mean_effective_dn_roi` | ROI must stay inside the scientific frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 140 / `effective_dn_fraction` | EffectiveDNMax must be positive | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn.py | 161 / `effective_dn_to_uint8` | Scientific container contains values outside Effective DN range | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn_alignment.py | 49 / `__init__` | Runtime alignment verification requires 1 <= SensorBitDepth < ContainerBitDepth <= 16 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn_alignment.py | 54 / `__init__` | Frame limits must satisfy 1 <= min_frames <= max_frames | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn_alignment.py | 124 / `add_frame` | Scientific DN source must be a uint16 ndarray | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/scientific_dn_alignment.py | 126 / `add_frame` | Scientific DN source must be an H×W array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/sidebar/registry.py | 55 / `register` | Sidebar item ID must be non-empty and unique: {item.id} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/sidebar/registry.py | 82 / `load_states` | SIDEBAR settings loaded defaults | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/sidebar/registry.py | 89 / `load_states` | items must be a list | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/sidebar/registry.py | 91 / `load_states` | SIDEBAR settings invalid; using defaults: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/sidebar/registry.py | 98 / `load_states` | SIDEBAR settings ignored malformed item: %r | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/sidebar/registry.py | 102 / `load_states` | SIDEBAR settings ignored unknown id=%r | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/sidebar/registry.py | 105 / `load_states` | SIDEBAR settings ignored duplicate id=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/sidebar/registry.py | 114 / `load_states` | SIDEBAR settings loaded | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/sidebar/registry.py | 147 / `apply` | SIDEBAR item hidden id=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/sidebar/registry.py | 149 / `apply` | SIDEBAR layout applied | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/sidebar/settings_dialog.py | 97 / `reset_defaults` | SIDEBAR settings reset to defaults | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_base.py | 73 / `display_name` | {instrument} ({self.serial_number}) | A. UI label / button / menu | Yes | No | No | `—` | — | presentation helper display_name; canonical technical/value display |
| gui/smu_base.py | 139 / `set_voltage` | This SMU driver does not support voltage-source control | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_base.py | 142 / `set_current` | This SMU driver does not support current-source control | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_base.py | 155 / `set_output_enabled` | This SMU driver does not support output control | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_base.py | 196 / `set_measurement_nplc` | This SMU driver does not support measurement NPLC | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_base.py | 208 / `set_measurement_nplc_auto` | This SMU driver does not support automatic measurement NPLC | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_base.py | 219 / `temporary_measurement_nplc` | Cannot safely change NPLC because its current value is unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_base.py | 224 / `temporary_measurement_nplc` | Cannot safely change NPLC because its automatic-mode state is unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 127 / `set_confirmed_factor` | Polarity factor must be +1 or -1 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 148 / `validate` | Voltage setpoint {requested} V exceeds safety range {limits.minimum_voltage_v} to {limits.maximum_voltage_v} V | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 153 / `validate` | Current compliance must be > 0 and <= {limits.maximum_current_compliance_a * 1000} mA | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 160 / `validate` | Current setpoint {requested * 1000} mA exceeds safety range {limits.minimum_current_a * 1000} to {limits.maximum_current_a * 1000} mA | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 166 / `validate` | Voltage compliance must be > 0 and <= {limits.maximum_voltage_compliance_v} V | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 172 / `validate` | SMU mode must be CV or CC | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 174 / `validate` | Setpoint × compliance ({estimated_power * 1000} mW) exceeds the {limits.maximum_power_w * 1000} mW safety limit | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 391 / `confirm_output_off_for_routing` | SMU_ROUTING blocked: authoritative OUTPUT state=%s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/smu_control.py | 447 / `bind_driver` | Cannot bind a different physical SMU while a safety fault is unresolved | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 473 / `bind_driver` | Cannot replace SMU driver while output is owned | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 544 / `set_confirmed_polarity_factor` | Polarity cannot change while SMU is owned | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 546 / `set_confirmed_polarity_factor` | SMU_POLARITY confirmed factor=%+d | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 551 / `acquire` | Only MANUAL or RECIPE can acquire normal ownership | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 554 / `acquire` | No supported SMU is connected | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 559 / `acquire` | SMU is owned by {self._ownership.value}; {owner.value} is blocked | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 563 / `acquire` | SMU OUTPUT OFF has not been confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 572 / `acquire` | SMU_OWNERSHIP %s acquired | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 582 / `release` | Cannot release SMU ownership before OUTPUT OFF is confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 588 / `release` | SMU_OWNERSHIP %s released | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 601 / `request_manual_output` | No supported SMU is connected | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 604 / `request_manual_output` | SMU is owned by {self._ownership.value}; MANUAL is blocked | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 608 / `request_manual_output` | SMU OUTPUT OFF has not been confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 636 / `request_manual_output` | MANUAL_SMU PHYSICAL_REQUEST=%+.9g MODE=%s COMPLIANCE=%g | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 661 / `request_manual_output_sequence` | Device area must be greater than 0 cm² | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 670 / `request_manual_output_sequence` | Polarity Jsc current compliance exceeds the SMU safety limit: {polarity_current_compliance_a * 1000} mA > {limits.maximum_current_compliance_a * 1000} mA | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 676 / `request_manual_output_sequence` | Polarity Voc voltage compliance exceeds the SMU safety limit: {settings.voc_compliance_v} V > {limits.maximum_voltage_compliance_v} V | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 699 / `request_manual_output_sequence` | No supported SMU is connected | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 702 / `request_manual_output_sequence` | SMU is owned by {self._ownership.value}; MANUAL is blocked | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 706 / `request_manual_output_sequence` | SMU OUTPUT OFF has not been confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 722 / `request_manual_output_sequence` | MANUAL_SMU OUTPUT_ON_REQUEST channel=%s area_cm2=%g mode=%s requested=%+.9g compliance=%g generation=%d | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 746 / `operation` | SMU OUTPUT OFF must be authoritatively confirmed before Relay switching (observed {observed}) | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 762 / `operation` | Verified SMU routing relay does not match the selected channel | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 769 / `operation` | MANUAL_SMU ROUTING channel=%s mapped_relay=%d verified=true | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 782 / `verified_light_on` | SMU routing changed before White Light ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 829 / `operation` | MANUAL_SMU POLARITY JSC_A=%+.9g JSC_MA_CM2=%+.9g VOC_V=%+.9g result=%s factor=%s snapshot=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 853 / `operation` | SMU routing changed after polarity measurement | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 867 / `operation` | SMU routing changed before OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 874 / `operation` | SMU OUTPUT ON could not be confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 877 / `operation` | SMU routing changed after OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 899 / `operation` | Manual SMU sequence was cancelled immediately after OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 911 / `operation` | MANUAL_SMU OUTPUT_ON channel=%s relay=%d mode=%s requested=%+.9g physical=%+.9g compliance=%g factor=%+d | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 923 / `operation` | MANUAL_SMU OUTPUT_ON_CANCELLED generation=%d | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 952 / `operation` | MANUAL_SMU OUTPUT_ON_ABORT generation=%d | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/smu_control.py | 1053 / `recover` | Safety recovery requires confirmed SMU OFF, routing all OFF, and White Light OFF | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1088 / `recover_safety_fault` | SMU_RECOVERY blocked: device or relay safety verifier unavailable | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/smu_control.py | 1092 / `recover_safety_fault` | SMU_RECOVERY blocked: connected physical identity does not match fault target fault=%s connected=%s | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/smu_control.py | 1117 / `recover_safety_fault` | SMU_RECOVERY blocked: OUTPUT is %s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/smu_control.py | 1126 / `recover_safety_fault` | SMU_RECOVERY routing OFF verification failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/smu_control.py | 1131 / `recover_safety_fault` | SMU_RECOVERY White Light OFF verification failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/smu_control.py | 1133 / `recover_safety_fault` | SMU_RECOVERY blocked: routing_off=%s white_light_off=%s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/smu_control.py | 1158 / `recover_safety_fault` | SMU_RECOVERY complete: OUTPUT OFF, routing OFF, White Light OFF | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 1175 / `prepare_recipe_start` | Manual SMU ownership must be safely closed first | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1176 / `prepare_recipe_start` | SMU_HANDOVER MANUAL -> RECIPE: confirming OUTPUT OFF | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1181 / `prepare_recipe_start` | Manual SMU output could not be safely disabled | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1183 / `prepare_recipe_start` | SMU_HANDOVER -> RECIPE complete | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1198 / `request_recipe_handover_to_manual` | SMU_HANDOVER RECIPE -> MANUAL requested; Recipe output blocked | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1217 / `recipe_output` | Recipe does not own the SMU | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1220 / `recipe_output` | Recipe output is blocked by a handover request | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1250 / `recipe_output` | Recipe output ownership changed immediately after OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1254 / `recipe_output` | RECIPE_SMU DEVICE_REQUEST=%+.9g POLARITY_FACTOR=%+d PHYSICAL=%+.9g | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1270 / `recipe_update_output_level` | Recipe does not own the SMU | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1273 / `recipe_update_output_level` | Recipe output is blocked by a handover request | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1279 / `recipe_update_output_level` | Recipe source-level update requires the matching source mode with OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1292 / `recipe_update_output_level` | RECIPE_SMU LEVEL_UPDATE DEVICE_REQUEST=%+.9g POLARITY_FACTOR=%+d PHYSICAL=%+.9g | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1307 / `recipe_measurement_nplc` | Recipe does not own the SMU | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1310 / `recipe_measurement_nplc` | Recipe NPLC must be configured while OUTPUT is confirmed OFF | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1322 / `recipe_measurement_nplc` | Connected SMU does not support Recipe {mode} NPLC control | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1337 / `set_recipe_polarity_factor` | Recipe does not own the SMU | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1339 / `set_recipe_polarity_factor` | Polarity can change only while Recipe OUTPUT is confirmed OFF | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1352 / `recipe_output_off` | Recipe does not own the SMU | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1384 / `recipe_output_off` | RECIPE_SMU OUTPUT OFF verified reason=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1395 / `recipe_readback` | Recipe does not own the SMU | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1401 / `recipe_readback` | Recipe formal image readback requires confirmed OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1426 / `recipe_polarity_measurement` | Recipe does not own the SMU | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1428 / `recipe_polarity_measurement` | Recipe polarity requires confirmed OUTPUT OFF | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1495 / `safe_shutdown` | SMU_OUTPUT_OFF physical OFF recovered despite attempt diagnostics attempt=%d diagnostics=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 1509 / `safe_shutdown` | SMU_OUTPUT_OFF retrying after unconfirmed physical state reason=%s diagnostics=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 1536 / `safe_shutdown` | MANUAL_SMU STOP routing all OFF confirmed | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1607 / `safe_shutdown` | SMU_FAULT shutdown failed reason=%s: %s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/smu_control.py | 1637 / `safe_shutdown` | SMU_SAFE_SHUTDOWN OUTPUT OFF confirmed reason=%s previous_owner=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1664 / `request_external_interlock` | SMU_EXTERNAL_INTERLOCK latched reason=%s | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/smu_control.py | 1701 / `request_emergency_off` | SMU_EMERGENCY safe: no SMU is connected | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1707 / `request_emergency_off` | SMU_EMERGENCY latched; output blocked; OFF queued behind active VISA I/O | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/smu_control.py | 1784 / `operation` | MANUAL_SMU COMPLIANCE_ACTIVE mode=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 1796 / `operation` | SMU_READBACK output=ON owner=MANUAL mode=MEASURE | H. Developer-only log | No | No | No | `—` | — | logger.debug |
| gui/smu_control.py | 1805 / `operation` | SMU_READBACK output=OFF mode=OUTPUT_ONLY | H. Developer-only log | No | No | No | `—` | — | logger.debug |
| gui/smu_control.py | 1807 / `operation` | SMU_UNEXPECTED_OUTPUT_ON detected during readback owner=%s operation=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 1822 / `operation` | SMU_READBACK output=UNKNOWN mode=OUTPUT_ONLY | H. Developer-only log | No | No | No | `—` | — | logger.debug |
| gui/smu_control.py | 1868 / `operation` | SMU readback OUTPUT state is UNKNOWN | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1925 / `_latch_output_unknown` | SMU_OUTPUT_UNKNOWN latched reason=%s | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/smu_control.py | 1974 / `_required_driver` | No supported SMU is connected | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1993 / `_ensure_normal_output_allowed_locked` | SMU Emergency OFF is latched; output is blocked | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1995 / `_ensure_normal_output_allowed_locked` | Previous SMU safety stop failed; run Emergency OFF or safe recovery | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 2001 / `_raise_if_output_blocked` | SMU output cancelled by Emergency OFF | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 2003 / `_raise_if_output_blocked` | SMU output cancelled by Recipe handover | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 2005 / `_raise_if_output_blocked` | Manual SMU output was cancelled | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 2017 / `_check_manual_generation` | Manual SMU sequence was cancelled | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 2043 / `_measure_with_temporary_output` | SMU measurement OUTPUT ON could not be confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 2056 / `_measure_with_temporary_output` | SMU measurement OUTPUT OFF could not be confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 2086 / `_apply_output` | SMU OUTPUT ON could not be confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 2117 / `_apply_output` | SMU ownership changed immediately after OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 2118 / `_apply_output` | %s_SMU OUTPUT=ON | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 2191 / `done` | %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 2196 / `done` | Polarity measurement quality failure: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 2198 / `done` | SMU operation failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/smu_manual_panel.py | 108 / `__init__` | OFF | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/smu_manual_panel.py | 109 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/smu_manual_panel.py | 111 / `__init__` | — V | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/smu_manual_panel.py | 112 / `__init__` | — mA/cm² | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/smu_manual_panel.py | 113 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/smu_manual_panel.py | 241 / `update_polarity` | {result.voc_v} V | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 241 / `update_polarity` | — V | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 245 / `update_polarity` | — mA/cm² | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 248 / `update_polarity` | {density} mA/cm² | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 258 / `update_command` | MANUAL_SMU GUI_APPLIED mode=%s requested=%+.9g physical=%+.9g compliance=%g factor=%+d | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_manual_panel.py | 268 / `update_readback` | {reading.voltage_v} V | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 268 / `update_readback` | — V | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 272 / `update_readback` | — mA/cm² | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 275 / `update_readback` | {density} mA/cm² | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 280 / `update_readback` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 284 / `reset_for_output_off` | — V | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 285 / `reset_for_output_off` | — mA/cm² | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 286 / `reset_for_output_off` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 287 / `reset_for_output_off` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/smu_manual_panel.py | 472 / `_flush_persistent_settings_from_timer` | Manual SMU settings save failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/software_update.py | 60 / `run` | Software update task failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/software_update.py | 237 / `launch_installer` | invalid_package | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/software_update.py | 240 / `launch_installer` | settings | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/software_update.py | 247 / `launch_installer` | settings | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/software_update.py | 271 / `notify_update_startup` | startup_failed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/widgets.py | 119 / `set_roi` | Cannot set an ROI without an image | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/widgets.py | 131 / `set_roi` | ROI must be a non-empty rectangle inside the image | I. Exception / traceback | No | No | No | `—` | — | raise |
| relay_hardware_diagnostic.py | 23 / `main` | diagnostic failed: {exc} | H. Developer-only log | No | No | No | `—` | — | print |
| relay_hardware_diagnostic.py | 27 / `main` | Diagnostic completed: USBRelay8 controller logical state verified. | H. Developer-only log | No | No | No | `—` | — | print |
| relay_hardware_diagnostic.py | 28 / `main` | Confirm external 5 V Relay power separately; software cannot verify coil or COM-NO contacts. | H. Developer-only log | No | No | No | `—` | — | print |
| scripts/generate_error_code_reference.py | 66 / `main` | Wrote {OUTPUT_PATH} | H. Developer-only log | No | No | No | `—` | — | print |
| scripts/generate_user_message_inventory.py | 546 / `main` | Wrote {OUTPUT} with {len(entries)} rows | H. Developer-only log | No | No | No | `—` | — | print |
| standalone/hdr_viewer/batch.py | 39 / `generate_batch` | No selected groups | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/batch.py | 118 / `generate_batch` | Unsafe temporary output path | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/processing.py | 42 / `validate` | Display gamma must be 0.1–10 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/processing.py | 44 / `validate` | Display compression must be 1–10000 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/processing.py | 58 / `load_signal` | Input changed after scan; scan again | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/processing.py | 60 / `load_signal` | Metadata changed after scan; scan again | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/processing.py | 69 / `load_signal` | TIFF checksum differs from capture metadata | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/processing.py | 72 / `load_signal` | Input format changed after scan | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/processing.py | 75 / `load_signal` | RAW DN exceeds declared effective range | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/processing.py | 105 / `fuse` | Invalid correction output | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/processing.py | 125 / `fuse` | No usable pixels: all exposures are dark or near saturation | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/processing.py | 132 / `fuse` | No finite float32 HDR pixels | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 98 / `_number` | Invalid {field_name} | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 101 / `_number` | Invalid {field_name} | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 121 / `read_frame` | JSON metadata must be an object | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 130 / `read_frame` | Unsupported measurement type | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 132 / `read_frame` | Voltage-mode capture has no commanded current-density condition | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 140 / `read_frame` | Missing MeasurementRunID and identifiable original run folder | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 147 / `read_frame` | Missing sample or channel | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 153 / `read_frame` | Gain must be an integer percentage | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 156 / `read_frame` | Gain readback differs from requested Gain | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 172 / `read_frame` | Filename and metadata disagree: {field_name} | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 175 / `read_frame` | Filename and metadata disagree: sample/channel | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 181 / `read_frame` | Filename and metadata disagree: requested exposure | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 184 / `read_frame` | Only single-image TIFF captures are supported | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 187 / `read_frame` | Input must be a uint16 monochrome TIFF | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 197 / `read_frame` | Invalid or unknown sensor bit depth / RAW alignment | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 200 / `read_frame` | EffectiveDNMax disagrees with sensor bit depth | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 213 / `scan_folder` | Input folder does not exist | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/scan.py | 215 / `scan_folder` | Generated HDR output is not an original capture folder | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/hdr_viewer/window.py | 129 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| standalone/hdr_viewer/window.py | 243 / `tick` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| standalone/hdr_viewer/window.py | 284 / `worker_finished` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| standalone/hdr_viewer/window.py | 285 / `worker_finished` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| standalone/light_linearity_tester/analysis.py | 44 / `add_light` | Light 分析需要 matching Dark | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/analysis.py | 60 / `result` | 沒有 Light frames | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/analysis.py | 128 / `write_report` | 統計資料 SHA-256 不一致或未完成保存 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/analysis.py | 135 / `write_report` | 原始影像 SHA-256 不一致：{path} | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/analysis.py | 138 / `write_report` | 測試快照 SHA-256 不一致 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/analysis.py | 146 / `write_report` | Deferred LUX calibration hash/channel mismatch | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/automatic.py | 39 / `validate` | Invalid automatic Gain list | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/automatic.py | 41 / `validate` | Automatic coverage requires at least 5 points and a positive EV span | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/automatic.py | 43 / `validate` | Invalid automatic exposure bounds | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/automatic.py | 45 / `validate` | Invalid automatic search budget | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/automatic.py | 47 / `validate` | Invalid effective DN noise floor | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/automatic.py | 101 / `__init__` | Automatic capture requires matching Gain definitions and >=5 Light/Dark repeats | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/automatic.py | 124 / `probe` | Automatic probe budget exhausted; completed data retained | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/automatic.py | 157 / `probe` | Probe Light/Dark actual exposure mismatch | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/automatic.py | 321 / `save_frame` | Insufficient storage; automatic acquisition stopped with data retained | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/calibration.py | 30 / `validate` | 通道必須是 CH1～CH4 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/calibration.py | 32 / `validate` | 參考 PWM 等級必須是 1～255 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/calibration.py | 34 / `validate` | 請填寫單位與有限、非負的背景讀值 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/calibration.py | 37 / `validate` | PWM 等級必須是 0～255 的整數 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/calibration.py | 39 / `validate` | PWM {level} 的光強讀值必須是有限、非負數值 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/calibration.py | 53 / `require_levels` | 缺少有效實測光強：PWM {missing}；請確認參考等級與背景扣除 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/calibration.py | 65 / `from_dict` | 不支援的光強表格式版本 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/calibration.py | 101 / `import_csv` | CSV 需要 channel,pwm_level,measured_intensity,unit 欄位 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/calibration.py | 105 / `import_csv` | CSV 通道或單位與目前表格不同；請先選取相同通道與單位 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/calibration.py | 107 / `import_csv` | CSV 有重複或超出範圍的 PWM 等級 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 37 / `capture` | Verified camera capture timeout | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 42 / `capture` | Scientific MONO16 frame is unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 47 / `capture` | FrameSequence metadata is unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 59 / `__init__` | 量測表與拍攝通道不同 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 73 / `check_cancel` | 已要求安全停止 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 85 / `acquire` | 相機未確認為 Scientific MONO16 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 90 / `acquire` | 影像、有效位元深度或 RAW alignment 未驗證 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 93 / `acquire` | 相機曝光／Gain 讀回無效 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 95 / `acquire` | 曝光讀回超過容差：requested={exposure}, actual={actual_us / 1000} | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 97 / `acquire` | 重複／舊的 frame sequence | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 102 / `acquire` | RAW 有效 DN 超出範圍 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 111 / `verify_light` | GSP-4H 模式／四通道亮度讀回與目前條件不一致 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 200 / `capture_condition` | Dark repeats 實際曝光不一致 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/capture.py | 216 / `capture_condition` | Light 與 Dark 實際曝光不一致 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/lux_dialog.py | 178 / `_next` | {reading} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| standalone/light_linearity_tester/lux_reference.py | 22 / `load_capture` | Capture evidence checksum mismatch: {name} | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/lux_reference.py | 36 / `attach_lux` | Confirm unchanged optics and reproducible warmed-up illumination before attaching LUX | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/lux_reference.py | 38 / `attach_lux` | Deferred LUX requires a completed capture | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/lux_reference.py | 40 / `attach_lux` | LUX channel/unit does not match the capture | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/lux_reference.py | 43 / `attach_lux` | No usable PWM levels to measure | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/lux_reference.py | 64 / `read_lux` | Invalid deferred LUX record/checksum | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/lux_reference.py | 67 / `read_lux` | Deferred LUX record lacks reproducibility confirmation | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/lux_reference.py | 69 / `read_lux` | LUX record belongs to a different capture | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/plan.py | 33 / `validate` | 通道必須是 1～4 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/plan.py | 36 / `validate` | {label} 列表不可為空、重複或超出範圍；PWM 0 用於 Dark | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/plan.py | 38 / `validate` | 曝光必須是 0.03～15000 ms 的有限、不重複數值 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/plan.py | 40 / `validate` | Light／Dark 張數必須是 1～100 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/plan.py | 42 / `validate` | 丟棄幀數必須是 0～20 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/plan.py | 44 / `validate` | 等待時間必須是有限、非負數值 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/plan.py | 46 / `validate` | PWM 頻率必須大於 0，未知時留空 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/plan.py | 56 / `estimate` | 影像／ROI 尺寸無效 | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/window.py | 114 / `execute` | Invalid guided settling delay | I. Exception / traceback | No | No | No | `—` | — | raise |
| standalone/light_linearity_tester/window.py | 368 / `_load_editor` | {profile.background} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| standalone/light_linearity_tester/window.py | 381 / `_refresh_relative` | {relative} | A. UI label / button / menu | Yes | No | No | `—` | — | indirect presentation assignment text; canonical technical/value display |
| tests/calibration/test_capture_history.py | 48 / `analyze` | FAIL | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation field quality_label; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/calibration/test_capture_history.py | 48 / `analyze` | PASS | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation field quality_label; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/calibration/test_capture_history.py | 65 / `analyze` | intentional analysis failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/calibration/test_capture_history.py | 75 / `source` | RisingCam frame 4821 | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation field display_name; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/calibration/test_capture_history.py | 169 / `test_unavailable_camera_metadata_is_explicit_null` | Unknown camera | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation field display_name; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/calibration/test_ruler_auto_exposure.py | 186 / `analyze` | analysis failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/calibration/test_ruler_auto_exposure.py | 226 / `capture` | capture failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/calibration/test_tester_state.py | 98 / `blocked` | intentionally absent | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/qt_test_utils.py | 23 / `ensure_qapplication` | Qt tests require QApplication, but a non-GUI application already exists | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_camera_ae_roi.py | 38 / `put_AEAuxRect` | AEAuxRect write after Close | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_camera_ae_roi.py | 46 / `get_AEAuxRect` | AEAuxRect read after Close | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_camera_linearity_qualification.py | 46 / `capture` | cancelled | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_camera_temperature.py | 218 / `test_temperature_formatting_and_unavailable_gui` | old | A. UI label / button / menu | No | No | No | `—` | — | QLabel; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_camera_temperature.py | 219 / `test_temperature_formatting_and_unavailable_gui` | old | A. UI label / button / menu | No | No | No | `—` | — | QLabel; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_close_safety.py | 149 / `fail_flush` | settings backend unavailable | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 132 / `capture` | camera failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 430 / `test_dialog_mode_switch_preserves_both_lists_and_compliance_values` | 0.9, 1.2 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 469 / `test_dialog_inactive_invalid_values_are_ignored_but_active_values_fail` | 2, 4, 6 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 487 / `test_dialog_inactive_invalid_values_are_ignored_but_active_values_fail` | nan | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 493 / `test_dialog_inactive_invalid_values_are_ignored_but_active_values_fail` | inf | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 499 / `test_dialog_inactive_invalid_values_are_ignored_but_active_values_fail` | 0.9, 1.1 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 500 / `test_dialog_inactive_invalid_values_are_ignored_but_active_values_fail` | -inf | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 1311 / `failed_shutdown` | safe shutdown verification failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 1575 / `fail_cleanup` | test cleanup failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_emergency_manager.py | 48 / `safe_smu_output_channels_off` | routing relay failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_emergency_manager.py | 63 / `fail` | worker failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_error_center.py | 29 / `test_search_subsystem_and_severity_filters` | SMU-203 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_error_center.py | 50 / `test_polarity_measurement_code_is_searchable` | MEAS-202 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_exposure_estimates.py | 128 / `test_editor_recalculates_modes_and_active_parameters_and_clears_invalid` | 100, 200, 500 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_exposure_estimates.py | 129 / `test_editor_recalculates_modes_and_active_parameters_and_clears_invalid` | 1, 2, 3, 1000 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_gsp4h_controller.py | 93 / `open` | Unavailable fake port | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_gsp4h_controller.py | 100 / `exchange` | Disconnected fake device | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_gsp4h_controller.py | 107 / `exchange` | Fake test gate timed out | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_gsp4h_controller.py | 113 / `close` | Fake close failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_gsp4h_controller.py | 279 / `cancel` | cancelled | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_light_linearity_automatic.py | 39 / `capture` | cancelled during scout | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_light_linearity_automatic.py | 310 / `test_cancelling_lux_measurement_turns_off_light_through_worker` | 2 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_light_linearity_automatic.py | 338 / `test_one_click_mode_uses_editable_gain_defaults_without_resetting_custom_input` | 125, 750, 5000 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_light_linearity_automatic.py | 418 / `test_lux_step_requires_matching_readback_and_valid_value_before_advancing` | 2 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_light_linearity_automatic.py | 430 / `test_lux_step_requires_matching_readback_and_valid_value_before_advancing` | 10 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_light_linearity_automatic.py | 438 / `test_lux_step_requires_matching_readback_and_valid_value_before_advancing` | 5 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_light_linearity_automatic.py | 457 / `test_previous_step_reapplies_pwm_and_cancel_blocks_late_start` | 2 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_light_linearity_automatic.py | 460 / `test_previous_step_reapplies_pwm_and_cancel_blocks_late_start` | 3 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_light_linearity_qualification.py | 40 / `safe_off` | OFF readback failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_light_linearity_qualification.py | 74 / `capture` | cancel test | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_light_linearity_qualification.py | 376 / `test_channel_tables_and_shutdown_without_hardware` | 100 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_light_linearity_qualification.py | 377 / `test_channel_tables_and_shutdown_without_hardware` | 25 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_log_export.py | 134 / `setUp` | Settings | A. UI label / button / menu | No | No | No | `—` | — | addMenu; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_log_export.py | 166 / `delayed_export` | test worker was not released | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_measurement_sdk_recovery.py | 47 / `Stop` | restore Stop failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_measurement_sdk_recovery.py | 108 / `_set_limits` | Invalid intermediate AE limits: {raw} | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_measurement_sdk_recovery.py | 390 / `safe_shutdown` | shutdown connection lost | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_measurement_sdk_recovery.py | 411 / `write` | diagnostic write denied | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_measurement_sdk_recovery.py | 423 / `clear_routing` | channel relay cleanup failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_measurement_sdk_recovery.py | 440 / `run` | Recipe AE setup | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_polarity_settings_and_measurement.py | 217 / `fail_light_on` | relay transport failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_polarity_settings_and_measurement.py | 273 / `check` | cancelled | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_ae_boundaries.py | 38 / `put_AEAuxRect` | No active metering pipeline | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_ae_stops.py | 122 / `test_ui_list_recalculates_estimate_and_preserves_mode_values` | -1, 0, +1 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_ae_stops.py | 125 / `test_ui_list_recalculates_estimate_and_preserves_mode_values` | 0, 0 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_ae_stops.py | 128 / `test_ui_list_recalculates_estimate_and_preserves_mode_values` | invalid inactive field | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_ae_timeout.py | 162 / `auto_exposure` | Output watchdog did not stop AE | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_auto_exposure.py | 144 / `test_ui_dropdown_shows_only_selected_form_and_preserves_values` | 150, 250 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_auto_exposure.py | 145 / `test_ui_dropdown_shows_only_selected_form_and_preserves_values` | 100, 200 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_auto_exposure.py | 460 / `test_camera_error_aborts_without_waiting_for_timeout` | camera link failed | F. User-facing error | No | No | No | `—` | — | signal c.error_occurred.emit; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_channel_roi.py | 77 / `set_channel_roi` | ROI verification failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_channel_roi.py | 157 / `test_resolution_change_disconnect_error_and_cancel_reject` | camera failed | F. User-facing error | No | No | No | `—` | — | signal camera.error_occurred.emit; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_roi_excitation.py | 66 / `clear_routing` | Routing while output ON | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_roi_excitation.py | 72 / `route_channel` | Routing while output ON | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_roi_excitation.py | 78 / `run_polarity` | Polarity may use white light only before selection | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_roi_excitation.py | 86 / `apply_polarity_factor` | Polarity change while output ON | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_roi_excitation.py | 92 / `_on` | EL cannot turn ON until white light is inhibited and OFF | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_roi_excitation.py | 106 / `readback` | Compliance tripped | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_store.py | 33 / `write_then_fail` | temporary write failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_store.py | 78 / `write_then_fail` | temporary write failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_workflow_refactor.py | 314 / `test_sample_id_inputs_follow_exact_active_channels_and_preserve_per_channel_values` | A | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_workflow_refactor.py | 315 / `test_sample_id_inputs_follow_exact_active_channels_and_preserve_per_channel_values` | B | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_workflow_refactor.py | 316 / `test_sample_id_inputs_follow_exact_active_channels_and_preserve_per_channel_values` | C | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_workflow_refactor.py | 333 / `test_start_is_blocked_with_exact_missing_active_channel_message` | A | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_relay.py | 47 / `send` | simulated HID feature-report failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_relay.py | 63 / `get_feature_report` | simulated feature-report failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_relay.py | 89 / `write` | Output Report write() must not be called | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_relay.py | 277 / `test_save_does_not_reset_runtime_or_change_hardware` | Saved name | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_relay.py | 429 / `check_cancel` | workflow generation changed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_relay.py | 494 / `test_settings_round_trip_and_channel_conflict` | Fixture | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation assignment display_name; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_sidebar_settings.py | 31 / `signal_receiver_count` | Qt signal not found: {type(obj).__name__}.{signal_name} | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_autoconnect.py | 43 / `query` | unexpected query: {command} | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_control.py | 79 / `configure_voltage_source` | configure failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_control.py | 92 / `configure_current_source` | configure failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_control.py | 142 / `query_output_enabled` | simulated VISA timeout | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_control.py | 270 / `test_recipe_cleanup_and_exception_style_finally_leave_output_off` | simulated Recipe failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_manual_sequence.py | 49 / `configure_voltage_source` | configuration failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_manual_sequence.py | 54 / `configure_current_source` | configuration failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_manual_sequence.py | 78 / `measure_current` | VI_ERROR_TMO during current measurement | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_manual_sequence.py | 139 / `clear_channels` | routing clear failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_manual_sequence.py | 406 / `fail_light` | relay failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_safety.py | 18 / `write` | VISA failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_ui_structure.py | 141 / `test_busy_state_immediately_disables_manual_editing` | 手動命令執行中 | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation field manual_lock_reason; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_ui_structure.py | 289 / `test_output_unknown_is_explicit_and_locks_every_manual_field` | ⚠ 無法確認 SMU 輸出狀態 請確認 SMU 前面板 OUTPUT 已關閉 | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation field manual_lock_reason; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_ui_structure.py | 319 / `ready_state` | B2901BL | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation field device_label; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_ui_structure.py | 328 / `ready_state` | B2901BL｜手動控制可用｜OUTPUT：OFF | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation field status_text; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_software_update.py | 373 / `fail_once` | locked application file | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tools/camera_linearity_qualification/analysis.py | 96 / `analyze_frames` | Resolution inconsistency | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_plan.py | 38 / `build_capture_plan` | Capture plan requires at least one Gain and Exposure | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_plan.py | 40 / `build_capture_plan` | Gain values must be positive | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_plan.py | 42 / `build_capture_plan` | Exposure values must be positive | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_plan.py | 44 / `build_capture_plan` | Repeat and settling-frame counts are invalid | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 78 / `snapshot_state` | Camera state snapshot must be captured on the CameraController owner thread | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 88 / `capture` | Scientific MONO16 frame is unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 92 / `capture` | FrameSequence metadata is unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 162 / `check_cancel` | Safe stop requested | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 166 / `run` | Light phase was not confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 218 / `run` | No Light conditions were captured | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 220 / `run` | Dark phase was not confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 227 / `run` | Dark preview rejected | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 271 / `_capture_verified` | Stale/non-monotonic scientific frame rejected: sequence={acquired.sequence}, previous={self._last_sequence} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 277 / `_capture_verified` | Camera is not Scientific MONO16 measurement-ready | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 281 / `_capture_verified` | Critical EffectiveDNMax/bit-depth/alignment metadata is not verified | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 285 / `_capture_verified` | Camera setting/readback mismatch requested={condition.exposure_ms} ms/G{condition.gain_percent}, actual={actual_us / 1000} ms/G{actual_gain} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 291 / `_effective_roi` | Capture must be uint16 HxW MONO16 | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/capture_runner.py | 296 / `_effective_roi` | Capture contains invalid effective DN | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/image_loader.py | 80 / `effective_array` | Scientific input must be a uint16 HxW TIFF | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/image_loader.py | 82 / `effective_array` | SensorBitDepth and EffectiveDNMax are required | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/image_loader.py | 85 / `effective_array` | EffectiveDNMax is inconsistent with SensorBitDepth | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/image_loader.py | 91 / `effective_array` | RawValueAlignment must be verified as right or left | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/image_loader.py | 93 / `effective_array` | Invalid DN above EffectiveDNMax | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/models.py | 35 / `validate` | ROI must have non-negative origin and positive dimensions | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/models.py | 37 / `validate` | ROI extends beyond image bounds | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/profile.py | 82 / `load_profile` | Unsupported camera linearity profile schema | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/regression.py | 29 / `linear_regression` | Regression inputs must be equal-length one-dimensional arrays | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/regression.py | 31 / `linear_regression` | Regression requires at least two distinct x values | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/window.py | 146 / `run` | Camera qualification run failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| tools/camera_linearity_qualification/window.py | 184 / `_build_ui` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| tools/camera_linearity_qualification/window.py | 199 / `_build_ui` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| tools/camera_linearity_qualification/window.py | 214 / `_wire` | Camera: %s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| tools/camera_linearity_qualification/window.py | 228 / `refresh_cameras` | Found %d camera(s) | H. Developer-only log | No | No | No | `—` | — | logger.info |
| tools/camera_linearity_qualification/window.py | 246 / `_camera_closed` | N/A | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/camera_linearity_qualification/window.py | 254 / `_refresh_temperature` | N/A | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/camera_linearity_qualification/window.py | 255 / `_refresh_temperature` | N/A | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/camera_linearity_qualification/window.py | 290 / `_on_progress` | {payload.completed_frames} / {payload.total_frames} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/camera_linearity_qualification/window.py | 290 / `_on_progress` | {payload.median_dn} / {payload.p99_dn} / {payload.saturation_fraction} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/camera_linearity_qualification/window.py | 290 / `_on_progress` | {payload.phase} — {payload.condition} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/camera_linearity_qualification/window.py | 290 / `_on_progress` | {percent}% | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/camera_linearity_qualification/window.py | 290 / `_on_progress` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/camera_linearity_qualification/window.py | 386 / `_numbers` | List cannot be empty | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/camera_linearity_qualification/window.py | 393 / `_parse_roi` | ROI must be x,y,width,height | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/check_release.py | 23 / `source_version` | Missing __version__ | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/check_release.py | 38 / `validate_release` | GUI version and release history disagree | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/check_release.py | 44 / `validate_release` | Every delivery must increase the version above the baseline | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/check_release.py | 50 / `validate_release` | Published release notes must not be rewritten | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/check_release.py | 64 / `main` | Release manifest is stale; run --write-manifest before testing | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/check_release.py | 65 / `main` | Release {history[0]['version']}: version, notes and {len(payload['files'])} file hashes verified | H. Developer-only log | No | No | No | `—` | — | print |
| tools/gsp4h_controller/controller.py | 81 / `_exchange` | {command}: {exc} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 88 / `_require_open` | Serial port is not open | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 93 / `_require_ready` | Refresh all settings successfully before enabling light controls | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 97 / `connect` | Shut down and disconnect the current session first | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 99 / `connect` | Invalid serial port or parity | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 137 / `set_brightness` | CH{channel} readback mismatch: requested={value}, actual={actual} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 154 / `set_mode` | Global mode acknowledgement mismatch | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 157 / `set_mode` | Global mode readback mismatch: requested={mode}, actual={actual} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 167 / `turn_off` | No controller session to turn off | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 173 / `turn_off` | OFF acknowledgement mismatch | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 181 / `turn_off` | OFF mode L was not verified | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 197 / `enable` | Controller did not remain in mode L during configuration | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 202 / `enable` | Enabled light configuration readback mismatch | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 216 / `safe_off` | No controller session to shut down | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 229 / `safe_off` | OFF acknowledgement mismatch | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/controller.py | 261 / `disconnect` | Serial port did not close | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/protocol.py | 13 / `channel_letter` | Channel must be an integer from 1 to 4 | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/protocol.py | 22 / `brightness_command` | Brightness must be an integer from 0 to 255 | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/protocol.py | 30 / `mode_command` | Global mode must be H or L | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/protocol.py | 38 / `response_text` | Non-ASCII response: {raw} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/protocol.py | 45 / `parse_brightness` | Invalid brightness response: {raw} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/protocol.py | 47 / `parse_brightness` | Wrong response channel for CH{channel}: {raw} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/protocol.py | 50 / `parse_brightness` | Out-of-range brightness response: {raw} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/protocol.py | 58 / `parse_mode` | Invalid global mode response: {raw} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/protocol.py | 65 / `verify_brightness_ack` | Invalid CH{channel} acknowledgement: {raw} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/serial_transport.py | 29 / `open` | Serial port already open | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/serial_transport.py | 34 / `open` | USB adapter serial number changed; refusing to send commands | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/serial_transport.py | 47 / `open` | Cannot open {port}: {self.serial.errorString()} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/serial_transport.py | 61 / `exchange` | Serial port is not open | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/serial_transport.py | 74 / `exchange` | Cannot clear input: {self.serial.errorString()} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/serial_transport.py | 78 / `exchange` | Serial write did not accept the complete command | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/serial_transport.py | 82 / `exchange` | Serial write failed: {self.serial.errorString()} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/serial_transport.py | 87 / `exchange` | Oversized response: {bytes(raw)} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/serial_transport.py | 99 / `exchange` | Response timeout; partial RX={bytes(raw)} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/serial_transport.py | 109 / `reset_identity` | Disconnect before selecting another USB adapter | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/settings.py | 14 / `validate_levels` | Brightness settings must contain four integers from 0 to 255 | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/settings.py | 27 / `load` | Unsupported brightness settings schema | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/worker.py | 66 / `execute` | Disconnect the selected controller before scanning | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/worker.py | 90 / `check_cancel` | Enable cancelled by OFF/close request | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/gsp4h_controller/worker.py | 95 / `execute` | Unknown controller operation | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/analyze_real_dataset.py | 45 / `analyze_dataset` | Real dataset image=%s index=%s total=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| tools/ruler_scale_calibration_tester/analyze_real_dataset.py | 372 / `_save_debug_images` | Failed to write debug image: {target} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/analyze_real_dataset.py | 432 / `_write_contact_sheet` | Failed to write contact sheet: {path} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/batch.py | 35 / `run_batch` | Batch ruler calibration image=%s index=%s total=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| tools/ruler_scale_calibration_tester/batch.py | 70 / `_print_summary` | Images {summary['images']} | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/batch.py | 71 / `_print_summary` | Ruler detected {summary['ruler_detected']} | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/batch.py | 72 / `_print_summary` | OCR usable {summary['ocr_usable']} | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/batch.py | 73 / `_print_summary` | Calibration successful {summary['calibration_successful']} | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/batch.py | 75 / `_print_summary` | Mean px/mm {summary['mean_pixels_per_mm']} | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/batch.py | 76 / `_print_summary` | SD {summary['sd_pixels_per_mm']} | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/batch.py | 77 / `_print_summary` | CV % {summary['cv_percent']} | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/batch.py | 79 / `_print_summary` | Failure reasons: | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/batch.py | 83 / `_print_summary` | - {reason}: {count} | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/batch.py | 85 / `_print_summary` | - none | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/capture_history.py | 92 / `begin_capture` | Camera capture must be an HxW scientific frame, got {raw.shape} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/capture_history.py | 115 / `begin_capture` | Failed to write capture preview: {directory / 'preview.png'} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/capture_history.py | 153 / `finalize` | Failed to write debug image: {target} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/capture_history.py | 155 / `finalize` | Capture debug image persistence failed name=%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| tools/ruler_scale_calibration_tester/capture_history.py | 161 / `finalize` | Capture result JSON persistence failed capture_id=%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| tools/ruler_scale_calibration_tester/capture_history.py | 166 / `finalize` | Capture manifest append failed capture_id=%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| tools/ruler_scale_calibration_tester/capture_history.py | 210 / `_create_session_directory` | Could not allocate a unique capture directory below {day_root} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/capture_history.py | 336 / `analyze_camera_capture` | Calibration service returned an invalid result | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/capture_history.py | 338 / `analyze_camera_capture` | Camera capture analysis raised capture_id=%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| tools/ruler_scale_calibration_tester/exposure_sweep.py | 70 / `check_cancel` | controlled_exposure_sweep_cancelled | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/exposure_sweep_main.py | 56 / `main` | ERROR: requested RisingCam camera is unavailable | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/exposure_sweep_main.py | 84 / `done` | Controlled exposure sweep completed: {output} | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/exposure_sweep_main.py | 87 / `done` | ERROR: controlled exposure sweep failed: {error} | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/exposure_sweep_main.py | 95 / `main` | Camera error: {message} | H. Developer-only log | No | No | No | `—` | — | print |
| tools/ruler_scale_calibration_tester/image_loader.py | 18 / `load_image` | Unsupported image format: {source.suffix} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/image_loader.py | 35 / `load_image` | Expected one image, got shape {array.shape} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/repeatability.py | 44 / `from_result` | Only a successful physically verified calibration can be added | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/repeatability.py | 46 / `from_result` | Calibration result has no source identity | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/repeatability.py | 88 / `add_result` | This captured frame has already been added to this repeatability session. | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/ruler_auto_exposure.py | 300 / `check_cancel` | ruler_auto_exposure_cancelled | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/ruler_auto_exposure.py | 345 / `run` | Calibration service returned an invalid result | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/ruler_auto_exposure.py | 347 / `run` | [RULER_AE] calibration analysis failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| tools/ruler_scale_calibration_tester/ruler_auto_exposure.py | 385 / `run` | [RULER_AE] acquisition quality evaluation failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| tools/ruler_scale_calibration_tester/ruler_auto_exposure.py | 470 / `run` | [RULER_AE] attempt=%s exposure=%s gain=%s candidate_confidence=%.3f global_sat=%s ruler_sat=%s tick_sat=%s michelson=%s decision=%s reason=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| tools/ruler_scale_calibration_tester/ruler_auto_exposure.py | 495 / `run` | [RULER_AE] acquisition failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| tools/ruler_scale_calibration_tester/ruler_auto_exposure.py | 504 / `run` | [RULER_AE] failed to restore original camera state | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| tools/ruler_scale_calibration_tester/ruler_auto_exposure.py | 552 / `capture` | Ruler AE capture did not return a scientific frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/source.py | 35 / `update_live` | Expected a scientific HxW frame, got {array.shape} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/source.py | 47 / `capture_camera` | No camera frame is available | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/window.py | 85 / `set_array` | Unsupported display image shape: {array.shape} | I. Exception / traceback | No | No | No | `—` | — | raise |
| tools/ruler_scale_calibration_tester/window.py | 135 / `run` | Camera capture could not be persisted | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| tools/ruler_scale_calibration_tester/window.py | 294 / `_build_ui` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 311 / `_build_ui` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 416 / `_on_camera_opened` | Ruler tester camera connected model=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| tools/ruler_scale_calibration_tester/window.py | 425 / `_on_camera_closed` | Ruler tester camera disconnected | H. Developer-only log | No | No | No | `—` | — | logger.info |
| tools/ruler_scale_calibration_tester/window.py | 446 / `_on_camera_error` | Ruler tester camera error: %s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| tools/ruler_scale_calibration_tester/window.py | 534 / `_show_ruler_ae_attempt` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 540 / `_show_ruler_ae_attempt` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 550 / `_show_ruler_ae_attempt` | {attempt.michelson_tick_contrast} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 550 / `_show_ruler_ae_attempt` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 739 / `_show_result` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 753 / `_show_result` | {result.pixels_per_mm} px/mm | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 753 / `_show_result` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 754 / `_show_result` | {result.um_per_pixel} µm/px | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 754 / `_show_result` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 755 / `_show_result` | {result.calibration_span_mm} mm | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 756 / `_show_result` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 770 / `_show_result` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| tools/ruler_scale_calibration_tester/window.py | 898 / `closeEvent` | Failed to restore ruler AE state during close | I. Exception / traceback | No | No | No | `—` | — | logger.exception |

## Canonical-value audit

At the initial audit revision, `rg -n 'currentText\(|itemText\(' gui` returned no matches. Existing persisted ComboBox-backed values are read primarily through `currentData()` and written with explicit item data. This invariant is covered by regression tests during Phase 3.

## Migration notes

- User-entered Recipe names, sample IDs, notes, and paths remain untranslated.
- Technical constants such as CH1, SMU, VISA, SCPI, TIFF, JPG, RAW, HDR, ROI, DN, Gain, units, protocol strings, and file extensions remain canonical.
- Developer logs and exception literals are retained when they are not shown directly to users; expected failure conditions are migrated at the controller/presentation boundary.
- Safety call paths are mapped to shared registry conditions before replacing their presentation so OUTPUT OFF verification, routing protection, emergency handling, abort cleanup, and close safety are unchanged.
