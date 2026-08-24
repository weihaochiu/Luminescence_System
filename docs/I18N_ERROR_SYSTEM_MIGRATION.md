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

## Safety preservation

The migration records and presents existing safety failures after the established safe-stop path runs. It does not replace output-off verification, Break-Before-Make routing, emergency handling, measurement abort cleanup, or close-event fail-closed decisions. The close-safety confirmation remains a specialized non-ignorable decision dialog because it must preserve retry/cancel/explicit forced-close semantics; it also records `SMU-203` through the central reporter.

## Persistent compatibility

- Recipe schema stays unchanged. Legacy `定電流密度`, `定電壓`, Chinese state/polarity/direction/compliance labels, and historical matrix mode labels are mapped to canonical values when read.
- Manual SMU settings map legacy Chinese mode/channel labels to `CC` / `CV` and `Ch1`–`Ch4`.
- User Recipe names, Sample IDs, notes, folders, and filenames are never translated.
- Language is independent of the OS locale and stored separately from measurement data.

## Audit method and retained literals

`scripts/generate_user_message_inventory.py` performs a repository AST inventory and writes `USER_MESSAGE_INVENTORY.md`. The final source audit also searches `QMessageBox`, visible Qt setters, `currentText()` / `itemText()`, requested error keywords, and Han characters.

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
- Final inventory: 530 rows, 87 visible technical/value displays, 0 translation candidates.
- Migrated application-facing literals: 434; literal `tr()` application call sites at final audit: 531.
- Central report call sites found: 35, sharing 20 registry conditions rather than defining per-exception codes.
- Developer/test/vendor/canonical technical rows retained: 530 total rows minus 87 visible technical/value rows = 443.
- GUI `currentText()` / `itemText()` logic uses: 0. Tests may inspect display text, but persistence and decisions use canonical item data.
- Remaining hard-coded user-facing strings requiring translation: 0. The retained displays are placeholders, units, dimensions, machine readbacks, identifiers, protocol terms, or user data listed in the audit rules above.
