from __future__ import annotations

"""Generate the repository user-message inventory from Python source ASTs."""

import ast
from dataclasses import dataclass
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "USER_MESSAGE_INVENTORY.md"

UI_CONSTRUCTORS = {
    "QAction",
    "QCheckBox",
    "QGroupBox",
    "QLabel",
    "QPushButton",
    "QRadioButton",
    "QToolBar",
}
UI_METHODS = {
    "addAction",
    "addItem",
    "addItems",
    "addMenu",
    "addTab",
    "addRow",
    "setHeaderLabels",
    "setHorizontalHeaderLabels",
    "setPlaceholderText",
    "setText",
    "setTitle",
    "setWindowTitle",
}
TOOLTIP_METHODS = {"setStatusTip", "setToolTip", "setWhatsThis"}
STATUS_METHODS = {"showMessage"}
MESSAGEBOX_METHODS = {"about", "critical", "information", "question", "warning"}
KEYWORDS = re.compile(
    r"錯誤|失敗|警告|無法|逾時|未連接|timeout|failed|error|warning",
    re.IGNORECASE,
)
TECHNICAL_DISPLAY_LITERALS = {
    "--", "—", "— V", "— mA/cm²", "N/A", "Unknown", "OFF",
    "FPS —", "SMU —", "0 / 0", "0.0%", "100.0%", "SDK", "Sensor",
    "Alignment", "NPLC", "Relay", "Recipe", "Raw DN", "PNG", "JPG",
}
TECHNICAL_DISPLAY_RE = re.compile(
    r"^(?:\{[^}]+\}|v?\{[^}]+\})(?:\s*(?:/|×|%|ms|s|V|mA/cm²|bit|\||｜|—|\([^)]*\))\s*(?:\{[^}]+\})?)*$"
)


def _is_technical_display(message: str) -> bool:
    compact = " ".join(message.split())
    if compact in TECHNICAL_DISPLAY_LITERALS:
        return True
    if TECHNICAL_DISPLAY_RE.fullmatch(compact):
        return True
    if re.fullmatch(r"Relay \{[^}]+\}", compact):
        return True
    return False


@dataclass(frozen=True)
class Entry:
    file: str
    line: int
    function: str
    message: str
    kind: str
    user_facing: bool
    translation: bool
    reason: str


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _owner_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id
    return ""


def _text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        pieces: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                pieces.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                try:
                    pieces.append("{" + ast.unparse(value.value) + "}")
                except Exception:
                    pieces.append("{value}")
        return "".join(pieces)
    if isinstance(node, (ast.List, ast.Tuple)):
        values = [_text(item) for item in node.elts]
        values = [item for item in values if item]
        return " | ".join(values) if values else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _text(node.left), _text(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _display_argument(call: ast.Call, name: str) -> ast.AST | None:
    if name in UI_CONSTRUCTORS:
        if not call.args:
            return None
        # QAction may receive an icon before its visible label.
        if name == "QAction" and len(call.args) >= 2 and _text(call.args[0]) is None:
            return call.args[1]
        return call.args[0]
    if name == "addRow":
        return call.args[0] if call.args else None
    if name in UI_METHODS | TOOLTIP_METHODS | STATUS_METHODS:
        return call.args[0] if call.args else None
    return None


def _namespace(relative: str) -> str:
    stem = Path(relative).stem
    if "camera" in stem:
        return "camera"
    if "smu" in stem or stem in {"keysight_b2900", "instrument_state_manager"}:
        return "smu"
    if "relay" in stem:
        return "relay"
    if "recipe" in stem:
        return "recipe"
    if "measurement" in stem or stem.startswith("el_matrix"):
        return "measurement"
    if "image" in stem or "output" in stem or "pixel_csv" in stem:
        return "file"
    if "settings" in stem or "sidebar" in relative:
        return "settings"
    return "app"


def _translation_key(entry: Entry) -> str:
    if not entry.translation:
        return "—"
    return f"{_namespace(entry.file)}.{Path(entry.file).stem}_{entry.line}"


def _error_prefix(entry: Entry) -> str:
    namespace = _namespace(entry.file)
    return {
        "camera": "CAM",
        "smu": "SMU",
        "relay": "REL",
        "recipe": "REC",
        "measurement": "MEAS",
        "file": "FILE",
        "settings": "CFG",
    }.get(namespace, "UI")


class Collector(ast.NodeVisitor):
    def __init__(self, relative: str) -> None:
        self.relative = relative
        self.functions: list[str] = []
        self.entries: list[Entry] = []
        self._seen: set[tuple[int, str, str]] = set()

    @property
    def function(self) -> str:
        return self.functions[-1] if self.functions else "<module>"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _add(
        self,
        node: ast.AST,
        message: str | None,
        kind: str,
        user_facing: bool,
        translation: bool,
        reason: str,
    ) -> None:
        if not message or not message.strip():
            return
        if self.relative.startswith("tests/") or "/sdk/" in f"/{self.relative}":
            user_facing = False
            translation = False
            reason += "; test fixture/vendor SDK, not application UI"
        compact = " ".join(message.replace("|", "\\|").split())
        technical = user_facing and translation and _is_technical_display(message)
        if technical:
            translation = False
            reason += "; canonical technical/value display"
        identity = (getattr(node, "lineno", 0), kind, compact)
        if identity in self._seen:
            return
        self._seen.add(identity)
        self.entries.append(
            Entry(
                self.relative,
                getattr(node, "lineno", 0),
                self.function,
                compact,
                kind,
                user_facing,
                translation,
                reason,
            )
        )

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        owner = _owner_name(node.func)
        display = _display_argument(node, name)
        if display is not None:
            kind = "B. Tooltip" if name in TOOLTIP_METHODS else (
                "C. Status bar message" if name in STATUS_METHODS else "A. UI label / button / menu"
            )
            self._add(node, _text(display), kind, True, True, name)
        elif owner == "QMessageBox" and name in MESSAGEBOX_METHODS:
            title = _text(node.args[1]) if len(node.args) > 1 else None
            message = _text(node.args[2]) if len(node.args) > 2 else None
            combined = " — ".join(item for item in (title, message) if item)
            kind = {
                "information": "D. User-facing informational message",
                "about": "D. User-facing informational message",
                "question": "D. User-facing informational message",
                "warning": "E. User-facing warning",
                "critical": "F. User-facing error",
            }[name]
            if name == "critical" and re.search(r"OUTPUT|輸出|緊急|安全|routing", combined, re.I):
                kind = "G. Safety-critical error"
            self._add(node, combined, kind, True, True, f"QMessageBox.{name}")
        elif name in {"debug", "error", "exception", "info", "warning", "critical"}:
            kind = "I. Exception / traceback" if name == "exception" else "H. Developer-only log"
            self._add(node, _text(node.args[0]) if node.args else None, kind, False, False, f"logger.{name}")
        elif name == "print":
            self._add(node, _text(node.args[0]) if node.args else None, "H. Developer-only log", False, False, "print")
        elif name == "emit" and isinstance(node.func, ast.Attribute):
            signal = _owner_name(node.func)
            if re.search(r"error|warning|message|status|failed|failure", signal, re.I):
                value = _text(node.args[0]) if node.args else None
                user = bool(re.search(r"message|status|error|warning", signal, re.I))
                kind = "F. User-facing error" if re.search(r"error|failed|failure", signal, re.I) else "C. Status bar message"
                self._add(node, value, kind, user, user, f"signal {signal}.emit")
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        message = None
        if isinstance(node.exc, ast.Call) and node.exc.args:
            message = _text(node.exc.args[0])
        self._add(node, message, "I. Exception / traceback", False, False, "raise")
        self.generic_visit(node)


def collect() -> list[Entry]:
    entries: list[Entry] = []
    for path in sorted(ROOT.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if any(part in {".git", ".venv", "__pycache__"} for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        except (OSError, SyntaxError, UnicodeError):
            continue
        collector = Collector(relative)
        collector.visit(tree)
        entries.extend(collector.entries)
    return sorted(entries, key=lambda item: (item.file, item.line, item.kind, item.message))


def render(entries: list[Entry]) -> str:
    user_count = sum(item.user_facing for item in entries)
    translation_count = sum(item.translation for item in entries)
    code_candidates: dict[Entry, str] = {}
    prefix_counts: dict[str, int] = {}
    for entry in entries:
        if entry.user_facing and entry.kind.startswith(("E.", "F.", "G.")):
            prefix = _error_prefix(entry)
            prefix_counts[prefix] = prefix_counts.get(prefix, 100) + 1
            code_candidates[entry] = f"{prefix}-{prefix_counts[prefix]}"

    lines = [
        "# User Message Inventory",
        "",
        "> Generated from the repository Python AST by `scripts/generate_user_message_inventory.py`.",
        "> Line numbers describe the source revision at generation time; rerun the generator after migration.",
        "",
        "## Scope and method",
        "",
        "The scan covers every repository `*.py` file (including tests and the bundled SDK) and classifies visible Qt constructor/setter text, tooltips, status messages, QMessageBox calls, user-facing signal payloads, logger calls, `print`, and raised exception literals. The requested keyword audit (`錯誤`, `失敗`, `警告`, `無法`, `逾時`, `未連接`, `timeout`, `failed`, `error`, `warning`) is also represented where those literals occur in these call sites. Dynamic strings whose value is assembled outside the call are noted by the absence of a literal row and require call-path review during migration.",
        "",
        f"Inventory rows: **{len(entries)}**; user-facing rows: **{user_count}**; translation candidates: **{translation_count}**.",
        "",
        "Error-code values below are migration candidates, not registry definitions. Final codes are curated by failure condition so multiple call sites can share one stable code.",
        "",
        "## Inventory",
        "",
        "| File | Line / function | Current message | Type | User-facing? | Needs translation? | Needs Error Code? | Proposed translation key | Proposed error code | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in entries:
        error_code = code_candidates.get(entry, "—")
        needs_code = "Yes" if error_code != "—" else "No"
        notes = entry.reason
        if entry.file.startswith("tests/"):
            notes += "; test fixture/assertion"
        elif "/sdk/" in f"/{entry.file}":
            notes += "; bundled vendor SDK"
        lines.append(
            "| {file} | {line} / `{function}` | {message} | {kind} | {user} | {translation} | {needs_code} | `{key}` | {code} | {notes} |".format(
                file=entry.file,
                line=entry.line,
                function=entry.function.replace("|", "\\|"),
                message=entry.message.replace("\n", "<br>"),
                kind=entry.kind,
                user="Yes" if entry.user_facing else "No",
                translation="Yes" if entry.translation else "No",
                needs_code=needs_code,
                key=_translation_key(entry),
                code=error_code,
                notes=notes,
            )
        )
    lines.extend(
        [
            "",
            "## Canonical-value audit",
            "",
            "At the initial audit revision, `rg -n 'currentText\\(|itemText\\(' gui` returned no matches. Existing persisted ComboBox-backed values are read primarily through `currentData()` and written with explicit item data. This invariant is covered by regression tests during Phase 3.",
            "",
            "## Migration notes",
            "",
            "- User-entered Recipe names, sample IDs, notes, and paths remain untranslated.",
            "- Technical constants such as CH1, SMU, VISA, SCPI, TIFF, JPG, RAW, HDR, ROI, DN, Gain, units, protocol strings, and file extensions remain canonical.",
            "- Developer logs and exception literals are retained when they are not shown directly to users; expected failure conditions are migrated at the controller/presentation boundary.",
            "- Safety call paths are mapped to shared registry conditions before replacing their presentation so OUTPUT OFF verification, routing protection, emergency handling, abort cleanup, and close safety are unchanged.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    entries = collect()
    OUTPUT.write_text(render(entries), encoding="utf-8")
    print(f"Wrote {OUTPUT} with {len(entries)} rows")


if __name__ == "__main__":
    main()
