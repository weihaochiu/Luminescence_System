from __future__ import annotations

"""JSON-backed localization with strict key and placeholder validation."""

from enum import Enum
from functools import lru_cache
import json
from pathlib import Path
from string import Formatter
from typing import Any, Mapping

from PySide6.QtCore import QObject, Signal


class Language(str, Enum):
    ZH_TW = "zh-TW"
    EN_US = "en-US"


DEFAULT_LANGUAGE = Language.ZH_TW
LANGUAGE_SETTINGS_KEY = "ui/language"
LOCALES_DIRECTORY = Path(__file__).resolve().parents[1] / "resources" / "locales"
LOCALE_FILES = {
    Language.ZH_TW: "zh_TW.json",
    Language.EN_US: "en_US.json",
}


def normalize_language(value: object) -> Language:
    if isinstance(value, Language):
        return value
    text = str(value or "").strip().replace("_", "-").lower()
    aliases = {
        "zh": Language.ZH_TW,
        "zh-tw": Language.ZH_TW,
        "traditional chinese": Language.ZH_TW,
        "en": Language.EN_US,
        "en-us": Language.EN_US,
        "english": Language.EN_US,
    }
    return aliases.get(text, DEFAULT_LANGUAGE)


def placeholder_names(template: str) -> frozenset[str]:
    names: set[str] = set()
    for _literal, field_name, _format_spec, _conversion in Formatter().parse(template):
        if field_name:
            names.add(field_name.split(".", 1)[0].split("[", 1)[0])
    return frozenset(names)


@lru_cache(maxsize=len(LOCALE_FILES))
def load_catalog(language: Language) -> dict[str, str]:
    path = LOCALES_DIRECTORY / LOCALE_FILES[language]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in payload.items()
    ):
        raise ValueError(f"Invalid translation catalog: {path}")
    return payload


def validate_catalogs(
    catalogs: Mapping[Language, Mapping[str, str]] | None = None,
) -> list[str]:
    selected = catalogs or {language: load_catalog(language) for language in Language}
    errors: list[str] = []
    expected_keys = set(selected[DEFAULT_LANGUAGE])
    for language in Language:
        keys = set(selected[language])
        for key in sorted(expected_keys - keys):
            errors.append(f"{language.value} missing key: {key}")
        for key in sorted(keys - expected_keys):
            errors.append(f"{language.value} has extra key: {key}")
    for key in sorted(set.intersection(*(set(catalog) for catalog in selected.values()))):
        placeholders = {
            language: placeholder_names(selected[language][key]) for language in Language
        }
        if len(set(placeholders.values())) != 1:
            detail = ", ".join(
                f"{language.value}={sorted(values)}"
                for language, values in placeholders.items()
            )
            errors.append(f"Placeholder mismatch for {key}: {detail}")
    return errors


class I18n(QObject):
    language_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._language = DEFAULT_LANGUAGE
        self._settings: Any | None = None

    @property
    def language(self) -> Language:
        return self._language

    def configure(self, settings: Any | None = None) -> Language:
        self._settings = settings
        persisted = (
            settings.value(LANGUAGE_SETTINGS_KEY, DEFAULT_LANGUAGE.value)
            if settings is not None
            else DEFAULT_LANGUAGE.value
        )
        self._language = normalize_language(persisted)
        return self._language

    def set_language(self, language: Language | str, *, persist: bool = True) -> bool:
        selected = normalize_language(language)
        changed = selected is not self._language
        self._language = selected
        if persist and self._settings is not None:
            self._settings.setValue(LANGUAGE_SETTINGS_KEY, selected.value)
            sync = getattr(self._settings, "sync", None)
            if callable(sync):
                sync()
        if changed:
            self.language_changed.emit(selected.value)
        return changed

    def translate(self, key: str, **kwargs: object) -> str:
        catalog = load_catalog(self._language)
        template = catalog.get(key)
        if template is None and self._language is not DEFAULT_LANGUAGE:
            template = load_catalog(DEFAULT_LANGUAGE).get(key)
        if template is None:
            return f"[{key}]"
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(f"Invalid placeholders for translation key {key}: {exc}") from exc


i18n = I18n()


def configure_i18n(settings: Any | None = None) -> Language:
    return i18n.configure(settings)


def set_language(language: Language | str, *, persist: bool = True) -> bool:
    return i18n.set_language(language, persist=persist)


def tr(key: str, **kwargs: object) -> str:
    return i18n.translate(key, **kwargs)
