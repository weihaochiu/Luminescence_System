"""Local bilingual UI strings; keep this standalone tool out of production catalogs."""
from core.i18n import Language, i18n


def msg(zh: str, en: str) -> str:
    return en if i18n.language is Language.EN_US else zh
