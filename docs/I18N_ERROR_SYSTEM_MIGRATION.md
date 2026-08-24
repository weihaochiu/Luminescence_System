# i18n and Error System Migration

## Scope

This migration introduces supported `zh-TW` and `en-US` presentation without changing measurement order, SMU commands, relay protocol, camera acquisition, Scientific DN algorithms, or output schemas. Machine values, user-entered data, protocol strings, units, and technical names remain canonical.

## Architecture

- `core/i18n.py` owns catalog loading, visible fallback, placeholder validation, language persistence (`ui/language`), and the runtime `language_changed` signal.
- `resources/locales/zh_TW.json` and `en_US.json` are the only translation catalogs. Namespaced keys are used at call sites; language conditionals are not distributed through GUI modules.
- ComboBox logic and persistence use `itemData()` / `currentData()`. Legacy Chinese Recipe and Manual SMU values are normalized on read; new writes remain canonical.
- `core/error_registry.py`, `error_context.py`, and `error_reporter.py` form a GUI-independent error boundary. Registry definitions reference translation keys but contain no bilingual prose.
- `gui/error_reporting.py` is the presentation adapter. MainWindow owns the session reporter and modal presentation; isolated test widgets keep structured logging without a blocking dialog.
- `gui/dialogs/error_dialog.py` renders condition-specific actions and technical details. Critical errors never expose Ignore or Continue.
- `gui/error_center/` provides code/search/subsystem/severity views, bounded session history (500 by default), and exact-code deep links.

Error actions use an explicit capability contract: the registry may declare only `retry`, `reconnect`, or `safe_shutdown`, and the dialog renders an action only when its owner supplies a real handler for that specific event. Actions are disabled once started and remain unresolved until the existing state machine confirms recovery. There is no generic Retry fallback. Camera, Relay, and SMU reconnects have separate dispatch paths; SMU reconnect always targets the explicitly selected resource and preserves an OUTPUT-unknown latch until the existing verified OUTPUT OFF recovery succeeds.

## Safety preservation

The migration records and presents existing safety failures after the established safe-stop path runs. It does not replace output-off verification, Break-Before-Make routing, emergency handling, measurement abort cleanup, or close-event fail-closed decisions. The close-safety confirmation remains a specialized non-ignorable decision dialog because it must preserve retry/cancel/explicit forced-close semantics; it also records `SMU-203` through the central reporter.

## Persistent compatibility

- Recipe schema stays unchanged. Legacy `定電流密度`, `定電壓`, Chinese state/polarity/direction/compliance labels, and historical matrix mode labels are mapped to canonical values when read.
- Manual SMU settings map legacy Chinese mode/channel labels to `CC` / `CV` and `Ch1`–`Ch4`.
- User Recipe names, Sample IDs, notes, folders, and filenames are never translated.
- Language is independent of the OS locale and stored separately from measurement data.

## Audit method and retained literals

`scripts/generate_user_message_inventory.py` performs a repository AST inventory and writes `USER_MESSAGE_INVENTORY.md`. It scans direct Qt presentation calls plus conditional-expression branches, nested qualified signals, status/result/progress/finished signal payloads, validation error/warning collections, execution-plan nodes, common presentation-field assignments (including generic `text`), presentation-helper arguments/returns, and error-formatting helpers. The final source audit also searches `QMessageBox`, visible Qt setters, `currentText()` / `itemText()`, requested error keywords, and Han characters. `tests/test_user_message_inventory.py` validates both synthetic indirect cases and the repository-wide zero-unresolved result.

Retained hard-coded literals are limited to technical constants and machine output (`SMU`, `VISA`, `SCPI`, `USB`, `TIFF`, `PNG`, `JPG`, `RAW`, `HDR`, `ROI`, `DN`, `Gain`, channel IDs, units, SDK state values), developer logs/exceptions, test fixtures, user data, and the specialized close-safety decision described above. Dynamic hardware/library messages are captured as technical context and paired with a stable user-facing error condition.

## Regression coverage

- Catalog key/placeholder equality, visible unknown-key fallback, persistence, runtime switching, and application `tr()` key existence.
- Registry format/subsystem/severity/recoverability/action and bilingual reference validation.
- Structured context/logging, exception capture, unknown-code fallback, bounded history, and critical behavior.
- zh-TW/en-US ErrorDialog rendering, diagnostics copying, action buttons, Error Center filtering/history, and deep links.
- Legacy/cross-language Recipe and Manual SMU canonical persistence.
- Existing mocked SMU, relay, emergency, close-safety, measurement, camera, and file-failure regressions.

## Generated reference

Run `python scripts/generate_error_code_reference.py` after changing the registry or error translations. This prevents `ERROR_CODE_REFERENCE.md` from drifting from executable definitions.

## Final audit result

- Initial inventory: 939 rows, 521 application-facing candidates.
- Final inventory: 546 rows, 118 visible canonical technical/value displays, 0 unresolved translation candidates.
- Translation catalogs: 819 matching keys per language; repository `tr()` calls at final audit: 973 across 48 Python files.
- Central reporting is routed through the GUI adapter/MainWindow boundary and shares 22 registry failure conditions rather than defining per-exception codes.
- Developer/test/vendor/canonical technical rows retained: 428 non-user-facing rows plus 118 allowed visible technical/value rows.
- GUI `currentText()` / `itemText()` logic uses: 0. Tests may inspect display text, but persistence and decisions use canonical item data.
- Remaining hard-coded user-facing strings requiring translation: 0 according to the expanded AST scanner and manual `currentText()` / language-conditional / Han audits. The retained Han literals are legacy migration maps, persistent built-in Recipe/Relay metadata, non-visible sizing/comment text, diagnostic exception details already placed behind localized registry messages, and one message-classification sentinel; retained visible rows are placeholders, units, dimensions, machine readbacks, identifiers, protocol terms, or user data listed in the audit rules above.

## Review corrections (2026-08-25)

- Removed no-op or unsafe Retry declarations from `CAM-202`, `CAM-203`, `FILE-201`, `MEAS-201`, and `REC-201`; `REL-203` now exposes only a real Relay reconnect path.
- Added `CAM-102` for a connected camera with no available frame and `UI-101` for operations blocked while measurement is running.
- Added centralized diagnostics redaction for password, token, secret, API key, credential, authorization, and Bearer values before structured logging, history storage, or clipboard formatting.
- Completed runtime MainWindow retranslation for menus, actions, tooltips, toolbar, Emergency Stop, sidebar sections, Measurement Control Bar, Device Panel, Manual SMU panel, ImageView empty state, and instrument-state snapshots without changing canonical ComboBox data or emitting index-change signals.
- Migrated the additional indirect audit findings in Camera calibration, EL preflight, Recipe/Relay/polarity validation, measurement summaries/execution plans, Pixel CSV progress, connection status, and status-bar presentation.
- Corrected legacy Recipe default behavior: a missing `dark_iv.compliance_action` remains `confirm`; only an explicit legacy abort label maps to `abort`.
