"""Bilingual text local to the standalone viewer."""
from core.i18n import Language, i18n


def msg(zh: str, en: str) -> str:
    return en if i18n.language is Language.EN_US else zh


def problem_text(code: str) -> str:
    return {
        "NEED_MULTIPLE_EXPOSURES": msg("至少需要兩種曝光", "At least two exposures required"),
        "INCONSISTENT_FORMAT": msg("影像尺寸或 RAW 格式不一致", "Inconsistent image size / RAW format"),
        "INCONSISTENT_CAMERA": msg("相機身份不一致", "Inconsistent camera identity"),
    }.get(code, code)


def phase_text(code: str) -> str:
    return {
        "prepare": msg("準備組別", "Preparing group"),
        "read": msg("讀取與平均曝光", "Reading / averaging exposures"),
        "fuse": msg("合成 HDR", "Fusing HDR"),
        "display": msg("產生觀看影像", "Creating display images"),
        "write": msg("保存結果", "Saving results"),
        "group_failed": msg("此組失敗，繼續其他組", "Group failed; continuing"),
    }.get(code, code)


def status_text(code: str) -> str:
    return {
        "completed": msg("完成", "Completed"),
        "completed_with_errors": msg("完成，部分組別失敗", "Completed with group errors"),
        "cancelled": msg("已取消，已完成結果保留", "Cancelled; completed results preserved"),
        "failed": msg("失敗", "Failed"),
    }.get(code, code)
