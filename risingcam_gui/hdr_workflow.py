from __future__ import annotations

"""Qt workflow for choosing T0 auto-HDR or a locked stability profile."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from .hdr_profile import HDRProfile


@dataclass(frozen=True)
class HDRSessionState:
    mode: str  # t0_auto / stability_locked
    sample_id: str
    profile_path: str = ""
    profile: HDRProfile | None = None

    @property
    def short_label(self) -> str:
        if self.mode == "t0_auto":
            return "HDR：T0 自動校正"
        if self.profile is not None:
            return f"HDR：Stability 鎖定（{len(self.profile.exposure_times_ms)} 段）"
        return "HDR：Stability 鎖定"


def choose_hdr_session(
    parent: QWidget,
    sample_id: str,
    recipe: Any,
    camera_info: dict[str, Any] | None = None,
    initial_directory: str = "",
    hdr_settings: Any | None = None,
) -> HDRSessionState | None:
    sample = sample_id.strip()
    if not sample:
        QMessageBox.warning(parent, "缺少樣品 ID", "啟用 HDR 前請先輸入樣品 ID。")
        return None
    if not recipe.hdr.enabled:
        QMessageBox.information(parent, "Recipe 未啟用 HDR", "請先在 Recipe 內啟用 HDR。詳細參數請到「設定 → HDR」。")
        return None
    if hdr_settings is None or hdr_settings.validate():
        QMessageBox.warning(parent, "HDR 系統設定無效", "請先到「設定 → HDR」完成並保存有效設定。")
        return None

    chooser = QMessageBox(parent)
    chooser.setWindowTitle("自動 HDR－請選擇量測類型")
    chooser.setIcon(QMessageBox.Icon.Question)
    chooser.setText(f"樣品：{sample}\n\n這是該元件的首次量測，還是 Aging／重複量測？")
    chooser.setInformativeText(
        "首次量測會在預掃描後建立 HDR Profile；Aging／重複量測不會重新自動選曝光，"
        "而是匯入並鎖定 T0 Profile。"
    )
    t0_button = chooser.addButton("首次量測（T0）", QMessageBox.ButtonRole.AcceptRole)
    aging_button = chooser.addButton("Aging／重複量測", QMessageBox.ButtonRole.ActionRole)
    chooser.addButton(QMessageBox.StandardButton.Cancel)
    chooser.exec()
    clicked = chooser.clickedButton()

    if clicked is t0_button:
        QMessageBox.information(
            parent,
            "T0 自動 HDR 已選擇",
            "正式量測時將執行全域自動 HDR 預掃描，固定 Gain，並在存檔時自動建立樣品專屬 "
            "HDR Profile。每個曝光的原始 EL、原始 Dark、Master Dark 與 Float32 HDR 都會保存。",
        )
        return HDRSessionState(mode="t0_auto", sample_id=sample)

    if clicked is not aging_button:
        return None

    filename = ""
    candidates = _find_profile_candidates(initial_directory, sample)
    if len(candidates) == 1:
        use_found = QMessageBox.question(
            parent,
            "已找到首次 HDR Profile",
            f"已依 Sample ID 找到：\n{candidates[0].name}\n\n要套用此設定嗎？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if use_found == QMessageBox.StandardButton.Cancel:
            return None
        if use_found == QMessageBox.StandardButton.Yes:
            filename = str(candidates[0])
    if not filename:
        filename, _ = QFileDialog.getOpenFileName(
            parent,
            "選擇該元件首次量測的 HDR Profile",
            initial_directory,
            "HDR Profile (*_HDR_Profile.json *.json)",
        )
    if not filename:
        return None
    try:
        profile = HDRProfile.load(filename)
        errors, warnings = profile.compatibility_issues(sample, recipe, camera_info, hdr_settings)
    except Exception as exc:
        QMessageBox.warning(parent, "HDR Profile 讀取失敗", str(exc))
        return None
    if errors:
        QMessageBox.critical(
            parent,
            "HDR Profile 不相容",
            "無法套用首次量測設定：\n\n• " + "\n• ".join(errors),
        )
        return None

    details = profile_summary(profile)
    if warnings:
        details += "\n\n提醒：\n• " + "\n• ".join(warnings)
    QMessageBox.information(parent, "已鎖定 T0 HDR Profile", details)
    return HDRSessionState(
        mode="stability_locked",
        sample_id=sample,
        profile_path=str(Path(filename).resolve()),
        profile=profile,
    )


def profile_summary(profile: HDRProfile) -> str:
    exposures = "、".join(f"{value:g} ms" for value in profile.exposure_times_ms)
    return (
        f"Sample ID：{profile.sample_id}\n"
        f"建立時間：{profile.created_at}\n"
        f"相機：{profile.camera_model or profile.camera_name or '未記錄'}\n"
        f"固定 Gain：{profile.gain_percent}%\n"
        f"HDR 曝光：{exposures}\n"
        f"每段：{profile.frames_per_exposure} frames\n\n"
        "Aging 量測將重新拍攝相同曝光的 Dark frames，但不會改變 Gain、曝光列表、"
        "HDR 演算法或輸出尺度。"
    )


def _find_profile_candidates(directory: str, sample_id: str) -> list[Path]:
    root = Path(directory) if directory else None
    if root is None or not root.is_dir():
        return []
    safe_id = re.sub(r"[^0-9A-Za-z._-]+", "_", sample_id.strip()).strip("._") or "sample"
    exact = list(root.glob(f"{safe_id}_T0_HDR_Profile.json"))
    if exact:
        return sorted(path.resolve() for path in exact)
    # Measurement roots commonly contain one subdirectory per sample/session.
    return sorted(path.resolve() for path in root.glob(f"*/{safe_id}_T0_HDR_Profile.json"))
