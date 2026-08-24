# User Message Inventory

> Generated from the repository Python AST by `scripts/generate_user_message_inventory.py`.
> Line numbers describe the source revision at generation time; rerun the generator after migration.

## Scope and method

The scan covers every repository `*.py` file (including tests and the bundled SDK) and classifies visible Qt constructor/setter text, tooltips, status messages, QMessageBox calls, user-facing signal payloads, logger calls, `print`, and raised exception literals. The requested keyword audit (`錯誤`, `失敗`, `警告`, `無法`, `逾時`, `未連接`, `timeout`, `failed`, `error`, `warning`) is also represented where those literals occur in these call sites. Dynamic strings whose value is assembled outside the call are noted by the absence of a literal row and require call-path review during migration.

Inventory rows: **546**; user-facing rows: **118**; translation candidates: **0**.

Error-code values below are migration candidates, not registry definitions. Final codes are curated by failure condition so multiple call sites can share one stable code.

## Inventory

| File | Line / function | Current message | Type | User-facing? | Needs translation? | Needs Error Code? | Proposed translation key | Proposed error code | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| core/error_registry.py | 46 / `__init__` | Duplicate error code: {definition.code} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 48 / `__init__` | Invalid error code: {definition.code} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 50 / `__init__` | Invalid subsystem for {definition.code}: {definition.subsystem} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 52 / `__init__` | Invalid recoverable flag for {definition.code} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 56 / `__init__` | Critical error {definition.code} cannot be ignored | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 59 / `__init__` | Invalid action for {definition.code}: {sorted(unknown_actions)} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 63 / `__init__` | Error {definition.code} requires at least one solution | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_registry.py | 70 / `from_path` | Error registry must be a JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/error_reporter.py | 69 / `__init__` | history_limit must be positive | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/i18n.py | 60 / `load_catalog` | Invalid translation catalog: {path} | I. Exception / traceback | No | No | No | `—` | — | raise |
| core/i18n.py | 134 / `translate` | Invalid placeholders for translation key {key}: {exc} | I. Exception / traceback | No | No | No | `—` | — | raise |
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
| gui/camera_capture_bridge.py | 65 / `capture` | A camera capture request is already pending | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 78 / `capture` | Camera capture timeout at {exposure_ms} ms / Gain {gain_percent}% | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 84 / `capture` | Camera capture completed without a frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_capture_bridge.py | 105 / `_configure` | Camera Exposure/Gain readback mismatch: requested={exposure_us} us/{gain_percent}%, actual={actual_exposure} us/{actual_gain}% | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 245 / `open_device` | Nncam.Open | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 258 / `open_device` | MONO capability check | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 496 / `close_camera` | Failed to disable SDK AE while closing calibration | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 657 / `_validate_auto_exposure_roi` | AE ROI coordinates and dimensions must be integers | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 660 / `_validate_auto_exposure_roi` | AE ROI requires x/y >= 0 and width/height > 0 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 662 / `_validate_auto_exposure_roi` | AE ROI {roi} exceeds current image {self._width}x{self._height} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 747 / `_apply_auto_exposure_roi` | %s requested=%s readback=%s verified=True | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 790 / `_set_auto_exposure_roi_failure` | %s requested=%s readback=%s verified=False error=%s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/camera_controller.py | 832 / `switch_to_manual_exposure` | Failed to restore SDK AE after manual switch failure | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 1032 / `start_ae_calibration` | NNCAM_OPTION_AUTOEXP_POLICY must read back Exposure Preferred (1) | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1036 / `start_ae_calibration` | NNCAM_OPTION_AUTOEXPOSURE_PERCENT must read back full active AE ROI average (100) | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1168 / `_log_ae_calibration_point` | SDK_AE_CAL_POINT timestamp=%s camera_serial=%s resolution=%s sdk_target=%s target_readback=%s converged=%s exposure_us=%s gain_percent=%s mean_dn=%s dn_max=%s dn_percent=%s saturated=%s low_signal=%s convergence_source=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1208 / `_finish_ae_calibration` | SDK_AE_CAL_RESULT timestamp=%s camera_serial=%s resolution=%s profile_id=%s %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1222 / `_finish_ae_calibration` | Failed to restore prior AE profile after calibration failure | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 1243 / `_abort_ae_calibration` | Failed to leave SDK AE off after calibration abort | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 1314 / `_write_nonblocking_sdk_option` | %s readback mismatch: requested=%s actual=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1321 / `_write_nonblocking_sdk_option` | %s requested/readback=%s/%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1324 / `_write_nonblocking_sdk_option` | %s unsupported or unavailable: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1346 / `_write_sdk_auto_exposure_target_value` | SDK AutoExpoTarget readback mismatch: requested=%s actual=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1352 / `_write_sdk_auto_exposure_target_value` | SDK AutoExpoTarget requested/readback=%s/%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1357 / `_enable_sdk_auto_exposure` | Camera is not connected | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1359 / `_enable_sdk_auto_exposure` | SDK AE cannot be enabled until AEAuxRect readback is verified | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1363 / `_enable_sdk_auto_exposure` | SDK AE enable mode must be Continuous or Once | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1369 / `_enable_sdk_auto_exposure` | SDK AutoExpoEnable requested {enable_value}, read back {readback} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1389 / `_disable_sdk_auto_exposure` | SDK AutoExpoEnable requested 0, read back {readback} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1414 / `_log_sdk_ae_calibration` | SDK_AE_CALIBRATION timestamp=%s reason=%s UserTargetPercent=%s%% EffectiveDNTarget=%s/%s SDKAutoExposureTarget=%s SDKAutoExposureTargetReadback=%s SDKAutoExposureMode=%s AutoExposureCalibrationApplied=%s CalibrationProfileId=%s ExposureReadbackUs=%s GainReadback=%s MeanEffectiveDN=%s MeanEffectiveDNPercent=%s MeteringMeanEffectiveDN=%s MeteringMeanEffectiveDNPercent=%s AEROI=%s AEROIVerified=%s Alignment=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1621 / `read_temperature_c` | Camera temperature query must run in the camera owner thread | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1623 / `read_temperature_c` | NNCAM_FLAG_GETTEMPERATURE is not present for this camera | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1648 / `_query_optional` | RisingCam SDK query failed for %s: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1722 / `_log_camera_capabilities` | Camera Model: %s Camera Serial: %s Camera flags: 0x%X Mono: %s RAW10/11/12/14/16 flags: %s/%s/%s/%s/%s Resolution: %sx%s SDK version: %s MaxBitDepth: %s Sensor bit depth: %s BitDepthSource: %s ScientificPixelFormat: %s ScientificFormatNegotiation: %s BITDEPTH requested/readback: 1/%s RGB requested/readback/fallback: 4/%s/%s RGB option 4 supported: %s BYTEORDER diagnostic: readback=%s, IgnoredForMono=True LINEAR/CURVE/Gamma requested: 0/0/100 LINEAR/CURVE/Gamma readback: %s/%s/%s ScientificISPBypassed: %s RAW mode: %s ISP mode: %s Pull bits: %s StartPullMode status: %s ScientificContainer: %s ScientificChannels: %s ContainerBitDepth: 16 ScientificFrameValidated: %s ScientificMeasurementReady: %s PixelFormat diagnostic: %s (%s) RawValueAlignment/source: %s/%s EffectiveDNMax: %s Camera Exposure Hardware Range: min = %s us, max = %s us, default = %s us Camera Gain Hardware Range: min = %s %%, max = %s %%, default = %s %% Auto Exposure Range: min exposure = %s us, max exposure = %s us, min gain = %s %%, max gain = %s %% Auto Exposure Controller/mode/user target: RisingCamSDK/%s/%s %% SDK Auto Exposure target requested/readback: %s/%s SDK Auto Exposure policy/full-active-AE-ROI percent: %s/%s SDK Auto Exposure exposure/gain damping: %s/%s SDK Overexposure policy: %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1857 / `_read_sensor_bit_depth` | unexpected MaxBitDepth value: {bit_depth} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1858 / `_read_sensor_bit_depth` | Camera startup OK: MaxBitDepth() -> %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1863 / `_read_sensor_bit_depth` | RisingCam MaxBitDepth() failed (%s); using capability-flag fallback: %s bits | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1870 / `_read_sensor_bit_depth` | RisingCam MaxBitDepth() failed (%s) and no RAW10/11/12/14/16 capability flag is available; SensorBitDepth=Unknown | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1884 / `_apply_camera_startup_setting` | Camera startup OK: %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1886 / `_apply_camera_startup_setting` | Camera startup OK: %s -> %r | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 1889 / `_apply_camera_startup_setting` | Camera startup FAILED at %s: %s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 1908 / `_configure_mono16_bitdepth` | Camera startup FAILED at NNCAM_OPTION_BITDEPTH readback: %s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/camera_controller.py | 1912 / `_configure_mono16_bitdepth` | NNCAM_OPTION_BITDEPTH readback | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 1927 / `_negotiate_mono16_rgb_option` | RGB=4 negotiation failed at %s; using PullImageV4(bits=16): %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1943 / `_negotiate_mono16_rgb_option` | RGB=4 negotiation readback mismatch (requested=4, readback=%r); using PullImageV4(bits=16) | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1966 / `_configure_nonblocking_option` | Camera startup NON-BLOCKING setting failed at %s: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1979 / `_configure_nonblocking_option` | Camera startup NON-BLOCKING readback mismatch at %s: requested=%s, readback=%r | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 1998 / `_configure_nonblocking_gamma` | Camera startup NON-BLOCKING setting failed at %s: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2008 / `_configure_nonblocking_gamma` | Camera startup NON-BLOCKING readback mismatch at Gamma: requested=%s, readback=%r | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2023 / `_read_nonblocking_setting` | Camera startup diagnostic: %s -> %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 2026 / `_read_nonblocking_setting` | Camera startup diagnostic unavailable at %s: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2041 / `_start_stream` | Scientific format validation | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2080 / `_handle_sdk_event` | SDK AE convergence Exposure/Gain readback failed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2122 / `_handle_sdk_event` | Failed to disable SDK AE after convergence failure | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 2127 / `_handle_sdk_event` | RisingCam SDK reported auto exposure convergence failure | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_controller.py | 2143 / `_update_alignment_verification` | DN alignment runtime evidence: state=%s frames=%s sampled=%s nonzero=%s above_right_max=%s (%.6f) low_bits_zero_ratio=%.6f nonzero_low_bits=%s patterns=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 2171 / `_update_alignment_verification` | DN alignment runtime verified: alignment=%s source=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 2213 / `_pull_live_frame` | MONO16 buffer validation | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2225 / `_pull_live_frame` | PullImageV4(bits=16) | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2236 / `_pull_live_frame` | PullImageV4(bits=16) output validation | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_controller.py | 2247 / `_pull_live_frame` | Camera scientific frame validation: PullBits=16 PixelFormat=%s ContainerBitDepth=16 Scientific frame dtype=%s Scientific frame ndim=%s Scientific frame shape=%s Pitch=%s BufferSize=%s ScientificFormatNegotiation=%s ScientificFrameValidated=True ScientificMeasurementReady=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_controller.py | 2373 / `_pull_live_frame` | Camera scientific frame validation failed: %s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/camera_controller.py | 2470 / `_poll_camera_status` | RisingCam SDK failed to refresh current Exposure/Gain | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_temperature_monitor.py | 133 / `start` | Camera temperature monitor started path=%s model=%s identifier=%s interval_ms=%d | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_temperature_monitor.py | 157 / `stop` | Camera temperature monitor stopped path=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/camera_temperature_monitor.py | 169 / `poll_now` | camera temperature is unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_temperature_monitor.py | 172 / `poll_now` | invalid camera temperature value: {value} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/camera_temperature_monitor.py | 265 / `_mark_unsupported` | Camera temperature API unsupported: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/camera_temperature_monitor.py | 276 / `_log_read_failure` | Camera temperature read unavailable; polling will continue: %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/el_matrix_hardware.py | 16 / `relay_channel_id` | Unsupported logical channel: {logical_channel} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_hardware.py | 38 / `prepare_shared_dark` | White Light OFF could not be verified for Shared Dark | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_hardware.py | 62 / `verified_light_off` | White Light OFF verification failed after polarity | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_hardware.py | 84 / `prepare_channel_dark` | White Light OFF could not be verified for channel Dark I-V | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_hardware.py | 92 / `run_dark_iv` | Dark I-V step must be greater than zero | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_hardware.py | 105 / `run_dark_iv` | Dark I-V requires a confirmed polarity factor | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 182 / `__init__` | Measurement snapshot execution order does not match the runtime plan | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 207 / `check_cancel` | Runtime watchdog: max_recipe_time_s exceeded | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 212 / `check_cancel` | Runtime watchdog: max_output_time_s exceeded for electrical setpoint | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 252 / `run` | Safe shutdown did not satisfy every post-processing gate | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 254 / `run` | Hardware measurement ended without a result | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 276 / `_run_all_polarities` | {channel.channel} polarity could not be reliably determined | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/el_matrix_runner.py | 426 / `_save_dark_iv` | {channel.channel} Dark I-V polarity metadata is inconsistent | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/emergency_manager.py | 71 / `begin_operator_operation` | EMERGENCY reset by explicit operator operation generation=%d | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/emergency_manager.py | 97 / `trigger` | GLOBAL_EMERGENCY timestamp=%s workflow=%s generation=%d smu_before=%s white_light_before=%s | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/emergency_manager.py | 120 / `trigger` | GLOBAL_EMERGENCY SMU shutdown request failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/emergency_manager.py | 133 / `trigger` | GLOBAL_EMERGENCY White Light shutdown failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/emergency_manager.py | 157 / `trigger` | GLOBAL_EMERGENCY SMU routing shutdown failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/emergency_manager.py | 163 / `trigger` | GLOBAL_EMERGENCY action=%s success | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/emergency_manager.py | 167 / `trigger` | GLOBAL_EMERGENCY action=%s failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/emergency_manager.py | 178 / `trigger` | GLOBAL_EMERGENCY completed generation=%d actions=%s failures=%s final_smu=%s | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/error_center/error_detail_panel.py | 13 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/error_center/error_detail_panel.py | 14 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/error_center/error_detail_panel.py | 16 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/error_center/error_detail_panel.py | 17 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/error_center/error_detail_panel.py | 64 / `_retranslate` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/instrument_state_manager.py | 306 / `_publish` | SMU_UI_STATE %s -> %s owner=%s operation=%s output=%s confirmed_off=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/instrument_state_manager.py | 316 / `_publish` | SMU_UNEXPECTED_OUTPUT_ON owner=%s operation=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/keysight_b2900.py | 51 / `configure_zero_level_measurement` | Source and measurement functions must be different | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 62 / `configure_zero_level_measurement` | B2900_MEASUREMENT_CONFIG source_mode=%s measurement_mode=%s range=AUTO nplc_auto=OFF nplc=%g compliance=%g source_level=0 | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/keysight_b2900.py | 75 / `_source_function` | Source mode must be CURR or VOLT | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 83 / `_configure_source_mode` | OUTPUT OFF was not confirmed before source-mode change | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 86 / `_configure_source_mode` | B2900_SOURCE_MODE requested=%s readback=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/keysight_b2900.py | 93 / `_configure_source_mode` | B2900 source-mode verification failed: requested {requested}, read back {readback or 'UNKNOWN'}, system error {error} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 100 / `_configure_source_mode` | B2900_SOURCE_MODE_CONFIGURATION_FAILED requested=%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/keysight_b2900.py | 123 / `_set_and_verify_source_level` | B2900 {source} source-level verification failed: requested {numeric}, read back {readback} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 155 / `_nplc_function` | Measurement NPLC mode must be CURR or VOLT | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 175 / `set_measurement_nplc` | B2900 NPLC must be between 0.001 and 100 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/keysight_b2900.py | 210 / `safe_stop` | B2900_SAFE_STOP source-level zero failed after OUTPUT OFF command=%s error=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/main_window_close.py | 25 / `closeEvent` | Manual SMU settings flush failed during application close | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/main_window_close.py | 35 / `closeEvent` | FORCED_APPLICATION_EXIT_WITH_UNCONFIRMED_SMU_OUTPUT | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/main_window_close.py | 39 / `closeEvent` | Forced-exit emergency cleanup failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/main_window_devices.py | 245 / `on_camera_opened` | {width} × {height} | A. UI label / button / menu | Yes | No | No | `—` | — | addItem; canonical technical/value display |
| gui/main_window_devices.py | 334 / `on_camera_closed` | FPS — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 335 / `on_camera_closed` | N/A | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 338 / `on_camera_closed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 339 / `on_camera_closed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 342 / `on_camera_closed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 343 / `on_camera_closed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 344 / `on_camera_closed` | Unknown | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 414 / `on_exposure_changed` | {exposure_us / 1000.0} ms | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 415 / `on_exposure_changed` | {gain} % | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 424 / `on_exposure_status_changed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 425 / `on_exposure_status_changed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 429 / `on_exposure_status_changed` | {exposure_us / 1000.0} ms | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 430 / `on_exposure_status_changed` | {gain} % | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 467 / `on_effective_dn_status_changed` | Unknown | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 467 / `on_effective_dn_status_changed` | {sensor_bits}-bit | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 482 / `on_effective_dn_status_changed` | Unknown | A. UI label / button / menu | Yes | No | No | `—` | — | indirect presentation assignment alignment_text; canonical technical/value display |
| gui/main_window_devices.py | 484 / `on_effective_dn_status_changed` | {round(float(mean_dn))} /{int(maximum)} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 489 / `on_effective_dn_status_changed` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 489 / `on_effective_dn_status_changed` | {float(percent)} % | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 492 / `on_effective_dn_status_changed` | {target_percent} % | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 494 / `on_effective_dn_status_changed` | {int(target_dn)} /{int(maximum)} | A. UI label / button / menu | Yes | No | No | `—` | — | indirect presentation assignment target_text; canonical technical/value display |
| gui/main_window_devices.py | 519 / `on_frame_ready` | {image.width()} × {image.height()} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_devices.py | 638 / `_refresh_live_view_roi_dn` | EffectiveDNMax must be positive | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/main_window_devices.py | 868 / `on_temperature_availability_changed` | N/A | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_measurement.py | 62 / `start_background_measurement` | Measurement is already running | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/main_window_measurement.py | 508 / `run` | Pixel CSV blocked: safe shutdown was not fully verified | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/main_window_ui.py | 252 / `_build_central_ui` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 253 / `_build_central_ui` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 259 / `_build_central_ui` | {self.controller.auto_exposure_target_percent} % | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 282 / `_build_central_ui` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 283 / `_build_central_ui` | -- | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 284 / `_build_central_ui` | Unknown | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 301 / `_build_central_ui` | Sensor | A. UI label / button / menu | Yes | No | No | `—` | — | addRow; canonical technical/value display |
| gui/main_window_ui.py | 302 / `_build_central_ui` | Alignment | A. UI label / button / menu | Yes | No | No | `—` | — | addRow; canonical technical/value display |
| gui/main_window_ui.py | 309 / `_build_central_ui` | N/A | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 323 / `_build_central_ui` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 324 / `_build_central_ui` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 325 / `_build_central_ui` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/main_window_ui.py | 329 / `_build_central_ui` | SDK | A. UI label / button / menu | Yes | No | No | `—` | — | addRow; canonical technical/value display |
| gui/main_window_ui.py | 576 / `_retranslate_ui` | {self.last_image.width()} × {self.last_image.height()} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/main_window_ui.py | 658 / `_build_status_bar` | SMU — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/manual_smu_settings.py | 147 / `save` | Manual SMU settings readback verification failed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/manual_smu_settings.py | 151 / `save` | Manual SMU settings readback verification failed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/manual_smu_settings.py | 160 / `_raise_for_status` | Manual SMU settings {operation} failed: {status_name} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/manual_smu_settings.py | 204 / `_qsettings_factory` | settings_factory is required for non-QSettings persistence backends | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/manual_smu_settings.py | 217 / `_qsettings_factory` | QSettings persistence backend has no storage identity | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_control_bar.py | 46 / `__init__` | Recipe | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_control_bar.py | 70 / `retranslate` | Recipe | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_execution_plan.py | 102 / `_matrix_channel_steps` | Dark IV | A. UI label / button / menu | Yes | No | No | `—` | — | ExecutionStep; canonical technical/value display |
| gui/measurement_execution_plan.py | 113 / `_matrix_channel_steps` | EL Matrix | A. UI label / button / menu | Yes | No | No | `—` | — | ExecutionStep; canonical technical/value display |
| gui/measurement_execution_plan.py | 174 / `_output_steps` | Raw DN | A. UI label / button / menu | Yes | No | No | `—` | — | _leaf; canonical technical/value display |
| gui/measurement_execution_plan.py | 224 / `build_measurement_execution_plan` | Channels | A. UI label / button / menu | Yes | No | No | `—` | — | ExecutionStep; canonical technical/value display |
| gui/measurement_output.py | 133 / `write_mono_array_csv_atomic` | Scientific Pixel CSV requires an H×W mono array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 135 / `write_mono_array_csv_atomic` | Pixel CSV value header must identify the scientific value | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 164 / `save_pixel_csv_products` | Raw Pixel CSV requires a uint16 H×W scientific array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 167 / `save_pixel_csv_products` | Shared Dark must be a shape-matched uint16 H×W array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 176 / `save_pixel_csv_products` | Dark-corrected Pixel CSV requires a matching Shared Dark frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 182 / `save_pixel_csv_products` | Exposure-normalized Pixel CSV requires a matching Shared Dark frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 184 / `save_pixel_csv_products` | Exposure normalization requires exposure_ms > 0 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 204 / `scientific_to_visualization` | Scientific camera source must use a uint16 container | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 207 / `scientific_to_visualization` | SensorBitDepth must be between 1 and 16 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 231 / `scientific_to_visualization` | RawValueAlignment must be 'right', 'left', or 'unknown' | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 236 / `scientific_to_visualization` | Scientific image must be H×W or H×W×3 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 242 / `save_scientific_tiff` | TIFF scientific master requires uint16 source data | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 245 / `save_scientific_tiff` | Scientific image must be H×W or H×W×3 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 258 / `save_matrix_capture` | Scientific frame is unavailable; refusing to create TIFF from Live View | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 263 / `save_matrix_capture` | Camera acquisition must provide a uint16 scientific frame | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_output.py | 310 / `save_matrix_capture` | Derived output generation modified the scientific source buffer | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_progress_dialog.py | 40 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 41 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 42 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 43 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 44 / `__init__` | 0 / 0 | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 45 / `__init__` | 0.0% | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 46 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 47 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 48 / `__init__` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/measurement_progress_dialog.py | 77 / `update_progress` | {progress.channel_index} / {progress.channel_total} — {progress.channel} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 101 / `update_progress` | {progress.channel_completed} / {progress.channel_capture_total} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 101 / `update_progress` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 105 / `update_progress` | {progress.current} / {progress.total} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 107 / `update_progress` | {percent}% | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 110 / `update_progress` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 122 / `update_postprocess_progress` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 123 / `update_postprocess_progress` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 124 / `update_postprocess_progress` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 125 / `update_postprocess_progress` | {progress.current} / {progress.total} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 126 / `update_postprocess_progress` | {progress.percent}% | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 129 / `update_postprocess_progress` | — | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 151 / `set_complete` | {total} / {total} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_progress_dialog.py | 152 / `set_complete` | 100.0% | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/measurement_snapshot.py | 170 / `save_el_matrix_snapshot` | Measurement Snapshot SHA-256 verification failed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/measurement_worker.py | 78 / `report_progress` | current and total are required for text progress | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/numeric.py | 18 / `decimal_from_number` | Invalid numeric value: {value} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/numeric.py | 20 / `decimal_from_number` | Numeric value must be finite: {value} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/numeric.py | 46 / `normalize_json_numbers` | Recipe values must be finite | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/pixel_csv_postprocessor.py | 110 / `run` | Pixel CSV is blocked until safe shutdown is fully verified | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/pixel_csv_postprocessor.py | 291 / `_process_job` | Shared Dark shape {dark.shape} does not match source shape {source.shape}: {source_path} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/pixel_csv_postprocessor.py | 303 / `_process_job` | Exposure normalization requires Exposure > 0 ms | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/pixel_csv_postprocessor.py | 329 / `_validate_scientific_array` | Scientific TIFF must contain uint16 pixels, got {array.dtype}: {path} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/pixel_csv_postprocessor.py | 333 / `_validate_scientific_array` | Scientific TIFF must be H×W mono, got shape {array.shape}: {path} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 79 / `measure` | Device area must be greater than 0 cm² | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 122 / `measure` | POLARITY_JSC raw_current_a=%s sample_area_cm2=%g current_density_ma_cm2=%+.9g compliance_a=%g | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/polarity_measurement.py | 156 / `measure` | POLARITY_VOC samples_v=%s representative_v=%+.9g compliance_v=%g | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/polarity_measurement.py | 200 / `measure` | POLARITY_MEASUREMENT_FAILED reason=%s details=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/polarity_measurement.py | 203 / `measure` | POLARITY_MEASUREMENT_EXCEPTION partial_results=%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/polarity_measurement.py | 215 / `measure` | White Light OFF completed after polarity cancellation | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/polarity_measurement.py | 229 / `analyze` | {label} contains missing or invalid samples | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 235 / `analyze` | {label} sample signs are inconsistent | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 252 / `analyze` | {label} representative is below the configured minimum | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 257 / `analyze` | {label} variation {variation}% exceeds {maximum_variation_percent}% | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 274 / `_integration_context` | SMU driver does not support temporary NPLC; polarity sampling continues without changing integration | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/polarity_measurement.py | 303 / `_measurement_configuration` | POLARITY_MEASUREMENT_CONFIG source_mode=%s measurement_mode=%s nplc=%g nplc_auto=OFF range=AUTO driver_specific=false | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/polarity_measurement.py | 330 / `_sample_output` | Temporary measurement OUTPUT ON was not confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/polarity_measurement.py | 342 / `_sample_output` | Temporary measurement OUTPUT OFF was not confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_dialog.py | 53 / `__init__` | {width} × {height} | A. UI label / button / menu | Yes | No | No | `—` | — | addItem; canonical technical/value display |
| gui/recipe_dialog_logic.py | 40 / `_parse_finite_numbers` | {field_name} 必須是以逗號或分號分隔的有限數值 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_dialog_logic.py | 44 / `_parse_finite_numbers` | {field_name} 不可空白 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_dialog_logic.py | 46 / `_parse_finite_numbers` | {field_name} 不可包含 NaN 或 Inf | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_dialog_logic.py | 69 / `_show_recipe_operation_failure` | Recipe %s failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/recipe_dialog_logic.py | 133 / `_write_recipe_to_form` | {channel.area_cm2} | A. UI label / button / menu | Yes | No | No | `—` | — | setText; canonical technical/value display |
| gui/recipe_dialog_pages.py | 61 / `_build_basic_tab` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/recipe_dialog_pages.py | 62 / `_build_basic_tab` | — | A. UI label / button / menu | Yes | No | No | `—` | — | QLabel; canonical technical/value display |
| gui/recipe_store.py | 31 / `_dataclass_from_dict` | {cls.__name__} must be a JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 477 / `from_dict` | Recipe must be a JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 479 / `from_dict` | Legacy Recipe safety/SMU values were detected and ignored; they did not override application-wide safety settings | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/recipe_store.py | 484 / `from_dict` | Legacy HDR configuration was removed and ignored. | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/recipe_store.py | 589 / `from_dict` | Legacy voltage-driven EL points cannot be represented exactly by the current-density Matrix; default Matrix points were retained | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/recipe_store.py | 620 / `from_dict` | Legacy per-row EL points expanded into Matrix axes; Recipe was migrated as draft for operator review | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/recipe_store.py | 636 / `from_dict` | Legacy Recipe Sample IDs were ignored; enter them in the Main Window | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/recipe_store.py | 708 / `load` | Recipe repository root must be a JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 711 / `load` | schema_version must be an integer | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 713 / `load` | Recipe schema {schema} is newer than supported schema {self.schema_version} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 718 / `load` | recipes must be a JSON array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 721 / `load` | Every Recipe entry must be a JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 724 / `load` | 無法讀取 Recipe 檔案：{exc} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 730 / `import_payload` | 匯入檔案頂層必須是 JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 733 / `import_payload` | 匯入檔案必須包含有效的整數 schema_version | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 735 / `import_payload` | Recipe schema_version={schema} 高於目前支援版本 {self.schema_version}，拒絕匯入 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 740 / `import_payload` | 匯入檔案必須包含 recipe JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 766 / `import_payload` | Recipe.{section} 必須是 JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 775 / `import_payload` | Recipe.channels 必須是 JSON array | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/recipe_store.py | 779 / `import_payload` | Recipe.channels[{index}] 必須是 JSON object | I. Exception / traceback | No | No | No | `—` | — | raise |
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
| gui/relay_controller.py | 368 / `_record` | Relay \| %s \| %s \| %s \| %s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 385 / `_channel` | CH{channel} {requested} failed：{exc} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 404 / `_group_on_unlocked` | Relay controller state mismatch：mask=0x{state_mask}, expected ON mask=0x{group_mask} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 412 / `_group_on_unlocked` | Relay rollback failed for CH%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_controller.py | 414 / `_group_on_unlocked` | {selected.display_name} ON failed; rollback attempted：{exc} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 415 / `_group_on_unlocked` | %s relay controller state verified=ON \| mask=0x%02X | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 446 / `_group_off_unlocked` | %s relay controller state verified=OFF \| mask=0x%02X | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 461 / `_safe_white_light_off_unlocked` | White Light OFF skipped: USBRelay8 not connected \| source=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/relay_controller.py | 469 / `_safe_white_light_off_unlocked` | Relay controller state mismatch：mask=0x{state_mask}, expected 0x00 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 471 / `_safe_white_light_off_unlocked` | White Light relay controller OFF verification failed \| source=%s | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_controller.py | 473 / `_safe_white_light_off_unlocked` | White Light relay controller OFF verified \| mask=0x%02X source=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 490 / `select_smu_output_channel` | SMU OUTPUT OFF was not authoritatively confirmed; routing is blocked | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 501 / `select_smu_output_channel` | SMU_ROUTING REQUEST channel=%s mapped_relay=%d state_before=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 515 / `select_smu_output_channel` | SMU routing all-OFF verification failed: mask=0x{all_off_mask} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 518 / `select_smu_output_channel` | SMU_ROUTING BREAK verified_all_off mask=0x%02X | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 527 / `select_smu_output_channel` | SMU routing target verification failed: expected={channel_id}/Relay {target_relay}, actual={active or 'none'}, mask=0x{after_mask} | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 539 / `select_smu_output_channel` | SMU_ROUTING MAKE verified channel=%s relay=%d state_after=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 564 / `clear_smu_output_channels` | SMU_ROUTING all OFF verified mask=0x%02X source=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 573 / `_safe_smu_output_channels_off_unlocked` | SMU routing OFF skipped: USBRelay8 not connected \| source=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/relay_controller.py | 584 / `_safe_smu_output_channels_off_unlocked` | SMU routing OFF verification failed source=%s failures=%s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/relay_controller.py | 586 / `_safe_smu_output_channels_off_unlocked` | SMU routing OFF verified mask=0x%02X source=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/relay_controller.py | 598 / `active_smu_output_channel` | SMU routing state is unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 672 / `_assert_routing_mutual_exclusion_unlocked` | routing fault handler must raise | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/relay_controller.py | 677 / `_latch_routing_fault_unlocked` | %s source=%s | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/relay_controller.py | 685 / `_latch_routing_fault_unlocked` | SMU routing fault handler failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_controller.py | 695 / `shutdown` | SMU routing OFF failed during RelayService shutdown | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/relay_controller.py | 700 / `shutdown` | White Light OFF failed during RelayService shutdown | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
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
| gui/smu_base.py | 53 / `set_voltage` | This SMU driver does not support voltage-source control | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_base.py | 56 / `set_current` | This SMU driver does not support current-source control | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_base.py | 59 / `set_output_enabled` | This SMU driver does not support output control | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_base.py | 100 / `set_measurement_nplc` | This SMU driver does not support measurement NPLC | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_base.py | 112 / `set_measurement_nplc_auto` | This SMU driver does not support automatic measurement NPLC | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_base.py | 123 / `temporary_measurement_nplc` | Cannot safely change NPLC because its current value is unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_base.py | 128 / `temporary_measurement_nplc` | Cannot safely change NPLC because its automatic-mode state is unavailable | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 106 / `set_confirmed_factor` | Polarity factor must be +1 or -1 | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 127 / `validate` | Voltage setpoint {requested} V exceeds safety range {limits.minimum_voltage_v} to {limits.maximum_voltage_v} V | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 132 / `validate` | Current compliance must be > 0 and <= {limits.maximum_current_compliance_a * 1000} mA | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 139 / `validate` | Current setpoint {requested * 1000} mA exceeds safety range {limits.minimum_current_a * 1000} to {limits.maximum_current_a * 1000} mA | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 145 / `validate` | Voltage compliance must be > 0 and <= {limits.maximum_voltage_compliance_v} V | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 151 / `validate` | SMU mode must be CV or CC | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 153 / `validate` | Setpoint × compliance ({estimated_power * 1000} mW) exceeds the {limits.maximum_power_w * 1000} mW safety limit | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 361 / `confirm_output_off_for_routing` | SMU_ROUTING blocked: authoritative OUTPUT state=%s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/smu_control.py | 409 / `bind_driver` | Cannot replace SMU driver while output is owned | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 471 / `set_confirmed_polarity_factor` | Polarity cannot change while SMU is owned | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 473 / `set_confirmed_polarity_factor` | SMU_POLARITY confirmed factor=%+d | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 478 / `acquire` | Only MANUAL or RECIPE can acquire normal ownership | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 481 / `acquire` | No supported SMU is connected | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 486 / `acquire` | SMU is owned by {self._ownership.value}; {owner.value} is blocked | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 490 / `acquire` | SMU OUTPUT OFF has not been confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 499 / `acquire` | SMU_OWNERSHIP %s acquired | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 509 / `release` | Cannot release SMU ownership before OUTPUT OFF is confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 515 / `release` | SMU_OWNERSHIP %s released | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 528 / `request_manual_output` | No supported SMU is connected | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 531 / `request_manual_output` | SMU is owned by {self._ownership.value}; MANUAL is blocked | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 535 / `request_manual_output` | SMU OUTPUT OFF has not been confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 563 / `request_manual_output` | MANUAL_SMU PHYSICAL_REQUEST=%+.9g MODE=%s COMPLIANCE=%g | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 588 / `request_manual_output_sequence` | Device area must be greater than 0 cm² | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 597 / `request_manual_output_sequence` | Polarity Jsc current compliance exceeds the SMU safety limit: {polarity_current_compliance_a * 1000} mA > {limits.maximum_current_compliance_a * 1000} mA | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 603 / `request_manual_output_sequence` | Polarity Voc voltage compliance exceeds the SMU safety limit: {settings.voc_compliance_v} V > {limits.maximum_voltage_compliance_v} V | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 613 / `request_manual_output_sequence` | No supported SMU is connected | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 616 / `request_manual_output_sequence` | SMU is owned by {self._ownership.value}; MANUAL is blocked | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 620 / `request_manual_output_sequence` | SMU OUTPUT OFF has not been confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 636 / `request_manual_output_sequence` | MANUAL_SMU OUTPUT_ON_REQUEST channel=%s area_cm2=%g mode=%s requested=%+.9g compliance=%g generation=%d | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 660 / `operation` | SMU OUTPUT OFF must be authoritatively confirmed before Relay switching (observed {observed}) | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 676 / `operation` | Verified SMU routing relay does not match the selected channel | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 683 / `operation` | MANUAL_SMU ROUTING channel=%s mapped_relay=%d verified=true | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 692 / `verified_light_on` | SMU routing changed before White Light ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 731 / `operation` | MANUAL_SMU POLARITY JSC_A=%+.9g JSC_MA_CM2=%+.9g VOC_V=%+.9g result=%s factor=%s snapshot=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 751 / `operation` | SMU routing changed after polarity measurement | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 765 / `operation` | SMU routing changed before OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 772 / `operation` | SMU OUTPUT ON could not be confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 775 / `operation` | SMU routing changed after OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 797 / `operation` | Manual SMU sequence was cancelled immediately after OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 809 / `operation` | MANUAL_SMU OUTPUT_ON channel=%s relay=%d mode=%s requested=%+.9g physical=%+.9g compliance=%g factor=%+d | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 821 / `operation` | MANUAL_SMU OUTPUT_ON_CANCELLED generation=%d | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 850 / `operation` | MANUAL_SMU OUTPUT_ON_ABORT generation=%d | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/smu_control.py | 931 / `recover` | Safety recovery requires confirmed SMU OFF, routing all OFF, and White Light OFF | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 965 / `recover_safety_fault` | SMU_RECOVERY blocked: device or relay safety verifier unavailable | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/smu_control.py | 985 / `recover_safety_fault` | SMU_RECOVERY blocked: OUTPUT is %s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/smu_control.py | 994 / `recover_safety_fault` | SMU_RECOVERY routing OFF verification failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/smu_control.py | 999 / `recover_safety_fault` | SMU_RECOVERY White Light OFF verification failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
| gui/smu_control.py | 1001 / `recover_safety_fault` | SMU_RECOVERY blocked: routing_off=%s white_light_off=%s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/smu_control.py | 1025 / `recover_safety_fault` | SMU_RECOVERY complete: OUTPUT OFF, routing OFF, White Light OFF | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 1042 / `prepare_recipe_start` | Manual SMU ownership must be safely closed first | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1043 / `prepare_recipe_start` | SMU_HANDOVER MANUAL -> RECIPE: confirming OUTPUT OFF | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1048 / `prepare_recipe_start` | Manual SMU output could not be safely disabled | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1050 / `prepare_recipe_start` | SMU_HANDOVER -> RECIPE complete | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1062 / `request_recipe_handover_to_manual` | SMU_HANDOVER RECIPE -> MANUAL requested; Recipe output blocked | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1081 / `recipe_output` | Recipe does not own the SMU | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1084 / `recipe_output` | Recipe output is blocked by a handover request | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1114 / `recipe_output` | Recipe output ownership changed immediately after OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1118 / `recipe_output` | RECIPE_SMU DEVICE_REQUEST=%+.9g POLARITY_FACTOR=%+d PHYSICAL=%+.9g | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1131 / `set_recipe_polarity_factor` | Recipe does not own the SMU | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1133 / `set_recipe_polarity_factor` | Polarity can change only while Recipe OUTPUT is confirmed OFF | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1146 / `recipe_output_off` | Recipe does not own the SMU | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1179 / `recipe_output_off` | RECIPE_SMU OUTPUT OFF verified reason=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1190 / `recipe_readback` | Recipe does not own the SMU | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1196 / `recipe_readback` | Recipe formal image readback requires confirmed OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1201 / `recipe_readback` | SMU compliance tripped during EL Matrix capture | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1219 / `recipe_polarity_measurement` | Recipe does not own the SMU | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1221 / `recipe_polarity_measurement` | Recipe polarity requires confirmed OUTPUT OFF | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1288 / `safe_shutdown` | SMU_OUTPUT_OFF physical OFF recovered despite attempt diagnostics attempt=%d diagnostics=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 1302 / `safe_shutdown` | SMU_OUTPUT_OFF retrying after unconfirmed physical state reason=%s diagnostics=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 1329 / `safe_shutdown` | MANUAL_SMU STOP routing all OFF confirmed | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1399 / `safe_shutdown` | SMU_FAULT shutdown failed reason=%s: %s | H. Developer-only log | No | No | No | `—` | — | logger.error |
| gui/smu_control.py | 1426 / `safe_shutdown` | SMU_SAFE_SHUTDOWN OUTPUT OFF confirmed reason=%s previous_owner=%s | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1460 / `request_external_interlock` | SMU_EXTERNAL_INTERLOCK latched reason=%s | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/smu_control.py | 1497 / `request_emergency_off` | SMU_EMERGENCY safe: no SMU is connected | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1503 / `request_emergency_off` | SMU_EMERGENCY latched; output blocked; OFF queued behind active VISA I/O | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/smu_control.py | 1580 / `operation` | MANUAL_SMU COMPLIANCE_ACTIVE mode=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 1581 / `operation` | SMU_READBACK output=ON owner=MANUAL mode=MEASURE | H. Developer-only log | No | No | No | `—` | — | logger.debug |
| gui/smu_control.py | 1590 / `operation` | SMU_READBACK output=OFF mode=OUTPUT_ONLY | H. Developer-only log | No | No | No | `—` | — | logger.debug |
| gui/smu_control.py | 1592 / `operation` | SMU_UNEXPECTED_OUTPUT_ON detected during readback owner=%s operation=%s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 1599 / `operation` | SMU_READBACK output=UNKNOWN mode=OUTPUT_ONLY | H. Developer-only log | No | No | No | `—` | — | logger.debug |
| gui/smu_control.py | 1642 / `operation` | SMU readback OUTPUT state is UNKNOWN | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1706 / `_latch_output_unknown` | SMU_OUTPUT_UNKNOWN latched reason=%s | H. Developer-only log | No | No | No | `—` | — | logger.critical |
| gui/smu_control.py | 1716 / `_required_driver` | No supported SMU is connected | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1735 / `_ensure_normal_output_allowed_locked` | SMU Emergency OFF is latched; output is blocked | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1737 / `_ensure_normal_output_allowed_locked` | Previous SMU safety stop failed; run Emergency OFF or safe recovery | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1743 / `_raise_if_output_blocked` | SMU output cancelled by Emergency OFF | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1745 / `_raise_if_output_blocked` | SMU output cancelled by Recipe handover | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1747 / `_raise_if_output_blocked` | Manual SMU output was cancelled | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1759 / `_check_manual_generation` | Manual SMU sequence was cancelled | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1785 / `_measure_with_temporary_output` | SMU measurement OUTPUT ON could not be confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1798 / `_measure_with_temporary_output` | SMU measurement OUTPUT OFF could not be confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1828 / `_apply_output` | SMU OUTPUT ON could not be confirmed | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1859 / `_apply_output` | SMU ownership changed immediately after OUTPUT ON | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/smu_control.py | 1860 / `_apply_output` | %s_SMU OUTPUT=ON | H. Developer-only log | No | No | No | `—` | — | logger.info |
| gui/smu_control.py | 1932 / `done` | %s | H. Developer-only log | No | No | No | `—` | — | logger.warning |
| gui/smu_control.py | 1934 / `done` | SMU operation failed | I. Exception / traceback | No | No | No | `—` | — | logger.exception |
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
| gui/widgets.py | 119 / `set_roi` | Cannot set an ROI without an image | I. Exception / traceback | No | No | No | `—` | — | raise |
| gui/widgets.py | 131 / `set_roi` | ROI must be a non-empty rectangle inside the image | I. Exception / traceback | No | No | No | `—` | — | raise |
| relay_hardware_diagnostic.py | 23 / `main` | diagnostic failed: {exc} | H. Developer-only log | No | No | No | `—` | — | print |
| relay_hardware_diagnostic.py | 27 / `main` | Diagnostic completed: USBRelay8 controller logical state verified. | H. Developer-only log | No | No | No | `—` | — | print |
| relay_hardware_diagnostic.py | 28 / `main` | Confirm external 5 V Relay power separately; software cannot verify coil or COM-NO contacts. | H. Developer-only log | No | No | No | `—` | — | print |
| scripts/generate_error_code_reference.py | 66 / `main` | Wrote {OUTPUT_PATH} | H. Developer-only log | No | No | No | `—` | — | print |
| scripts/generate_user_message_inventory.py | 504 / `main` | Wrote {OUTPUT} with {len(entries)} rows | H. Developer-only log | No | No | No | `—` | — | print |
| tests/qt_test_utils.py | 23 / `ensure_qapplication` | Qt tests require QApplication, but a non-GUI application already exists | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_camera_ae_roi.py | 38 / `put_AEAuxRect` | AEAuxRect write after Close | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_camera_ae_roi.py | 46 / `get_AEAuxRect` | AEAuxRect read after Close | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_camera_temperature.py | 218 / `test_temperature_formatting_and_unavailable_gui` | old | A. UI label / button / menu | No | No | No | `—` | — | QLabel; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_camera_temperature.py | 219 / `test_temperature_formatting_and_unavailable_gui` | old | A. UI label / button / menu | No | No | No | `—` | — | QLabel; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_close_safety.py | 149 / `fail_flush` | settings backend unavailable | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 120 / `capture` | camera failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 349 / `test_dialog_mode_switch_preserves_both_lists_and_compliance_values` | 0.9, 1.2 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 388 / `test_dialog_inactive_invalid_values_are_ignored_but_active_values_fail` | 2, 4, 6 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 406 / `test_dialog_inactive_invalid_values_are_ignored_but_active_values_fail` | nan | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 412 / `test_dialog_inactive_invalid_values_are_ignored_but_active_values_fail` | inf | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 418 / `test_dialog_inactive_invalid_values_are_ignored_but_active_values_fail` | 0.9, 1.1 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 419 / `test_dialog_inactive_invalid_values_are_ignored_but_active_values_fail` | -inf | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_el_matrix.py | 1050 / `failed_shutdown` | safe shutdown verification failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_emergency_manager.py | 48 / `safe_smu_output_channels_off` | routing relay failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_emergency_manager.py | 63 / `fail` | worker failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_error_center.py | 29 / `test_search_subsystem_and_severity_filters` | SMU-203 | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_polarity_settings_and_measurement.py | 217 / `fail_light_on` | relay transport failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_polarity_settings_and_measurement.py | 273 / `check` | cancelled | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_store.py | 33 / `write_then_fail` | temporary write failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_store.py | 78 / `write_then_fail` | temporary write failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_workflow_refactor.py | 314 / `test_sample_id_inputs_follow_exact_active_channels_and_preserve_per_channel_values` | A | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_workflow_refactor.py | 315 / `test_sample_id_inputs_follow_exact_active_channels_and_preserve_per_channel_values` | B | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_workflow_refactor.py | 316 / `test_sample_id_inputs_follow_exact_active_channels_and_preserve_per_channel_values` | C | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_recipe_workflow_refactor.py | 333 / `test_start_is_blocked_with_exact_missing_active_channel_message` | A | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_relay.py | 47 / `send` | simulated HID feature-report failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_relay.py | 63 / `get_feature_report` | simulated feature-report failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_relay.py | 89 / `write` | Output Report write() must not be called | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_relay.py | 251 / `test_save_does_not_reset_runtime_or_change_hardware` | Saved name | A. UI label / button / menu | No | No | No | `—` | — | setText; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_relay.py | 403 / `check_cancel` | workflow generation changed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_relay.py | 468 / `test_settings_round_trip_and_channel_conflict` | Fixture | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation assignment display_name; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_sidebar_settings.py | 31 / `signal_receiver_count` | Qt signal not found: {type(obj).__name__}.{signal_name} | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_autoconnect.py | 43 / `query` | unexpected query: {command} | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_control.py | 69 / `configure_voltage_source` | configure failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_control.py | 82 / `configure_current_source` | configure failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_control.py | 132 / `query_output_enabled` | simulated VISA timeout | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_control.py | 260 / `test_recipe_cleanup_and_exception_style_finally_leave_output_off` | simulated Recipe failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_manual_sequence.py | 34 / `configure_voltage_source` | configuration failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_manual_sequence.py | 39 / `configure_current_source` | configuration failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_manual_sequence.py | 112 / `clear_channels` | routing clear failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_manual_sequence.py | 234 / `fail_light` | relay failed | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_safety.py | 18 / `write` | VISA failure | I. Exception / traceback | No | No | No | `—` | — | raise; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_ui_structure.py | 141 / `test_busy_state_immediately_disables_manual_editing` | 手動命令執行中 | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation field manual_lock_reason; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_ui_structure.py | 289 / `test_output_unknown_is_explicit_and_locks_every_manual_field` | ⚠ 無法確認 SMU 輸出狀態 請確認 SMU 前面板 OUTPUT 已關閉 | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation field manual_lock_reason; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_ui_structure.py | 319 / `ready_state` | B2901BL | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation field device_label; test fixture/vendor SDK, not application UI; test fixture/assertion |
| tests/test_smu_ui_structure.py | 328 / `ready_state` | B2901BL｜手動控制可用｜OUTPUT：OFF | A. UI label / button / menu | No | No | No | `—` | — | indirect presentation field status_text; test fixture/vendor SDK, not application UI; test fixture/assertion |

## Canonical-value audit

At the initial audit revision, `rg -n 'currentText\(|itemText\(' gui` returned no matches. Existing persisted ComboBox-backed values are read primarily through `currentData()` and written with explicit item data. This invariant is covered by regression tests during Phase 3.

## Migration notes

- User-entered Recipe names, sample IDs, notes, and paths remain untranslated.
- Technical constants such as CH1, SMU, VISA, SCPI, TIFF, JPG, RAW, HDR, ROI, DN, Gain, units, protocol strings, and file extensions remain canonical.
- Developer logs and exception literals are retained when they are not shown directly to users; expected failure conditions are migrated at the controller/presentation boundary.
- Safety call paths are mapped to shared registry conditions before replacing their presentation so OUTPUT OFF verification, routing protection, emergency handling, abort cleanup, and close safety are unchanged.
