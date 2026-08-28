# Camera Linearity Qualification

這是獨立的相機線性度驗證工具。它重用正式程式的 `CameraController` 與
`CameraCaptureBridge` MONO16 pull-mode stream，不建立第二條 RisingCam SDK stream，
也不接入 Recipe、SMU、Relay、EL Matrix runner 或 production output pipeline。

## Windows 實機操作

1. 在 repository 根目錄雙擊 `run_camera_linearity_qualification.bat`。
2. 在 **Capture + Analyze** 選擇相機，按 **Connect**。
3. 等待 Live View 顯示 `Scientific MONO16`、Sensor bit depth、Effective DN maximum
   與 Raw alignment；任何 critical RAW metadata 顯示 unknown 時不可做正式 qualification。
4. 依相機與光源需求設定暖機秒數並等待完成。固定相機、鏡頭、光圈、焦點、解析度與 pixel format。
5. 使用均勻、穩定且可重現的平場光源，測試期間不得移動 ROI 或改變光學條件。
6. 在 Live View 上用滑鼠框選矩形 ROI；確認顯示的 x、y、width、height。若要使用全畫面，按
   **Reset to full image**，並在提示中明確確認。
7. 選 **Pilot only**，使用 G100 Pilot 先判定光源：
   `LIGHT TOO BRIGHT`、`LIGHT TOO DIM` 或 `SUITABLE FOR FULL QUALIFICATION`。
8. 依 Pilot 結果調整光源；Pilot 不會產生可供 production 使用的正式 profile。
9. 選 **Full Qualification**，預設 Gain 為 100/200/300/400/500%，Exposure 為
   50/100/200/500/1000/2000/5000/10000/15000 ms，每條件 Light/Dark 各 5 張。
10. 按 **Start**。LIGHT 提示出現時，打開並穩定固定光源後才按 Yes。
11. LIGHT phase 完成後，關閉光源或完整遮住鏡頭。不要以畫面角落背景代替 Dark。
12. DARK 提示會顯示目前流程狀態；確認遮光後按 Yes。工具先拍 Dark preview，若過亮或太接近
    matching Light，會警告並要求重新確認。
13. DARK phase 只針對實際完成的 Gain × Exposure conditions 拍 matching Dark，完成後自動分析。
14. **Results** 最上方顯示 PASS／CONDITIONAL PASS／FAIL、validated Gains、可靠 DN 範圍、
    compression/saturation、transition-frame 與 HDR readiness。
15. 報告與 profile 位於 session 的 `ANALYSIS`：
    `CAMERA_LINEARITY_REPORT.md`、CSV、PNG、`analysis_summary.json` 與
    `camera_linearity_profile.json`。

停止時先使用 **Stop safely**。它在目前 SDK/capture safe point 取消、恢復原 Exposure、Gain、
Auto Exposure 狀態，再讓工作執行緒結束。只有需要立即釋放 SDK handle 時才使用
**Emergency close camera**。拍攝中關閉視窗會先詢問安全停止，完成清理後才關閉。

## 結果語意

- **PASS**：完整 Full Qualification 證據、所有測試 Gain、matching Dark、每條件至少五次、
  critical RAW metadata、溫度範圍、transition frame、linearity 與 repeatability gates 都通過。
- **CONDITIONAL PASS**：部分 Gain 通過，或缺 Dark/repeats/uniform-source 等正式證據。
- **FAIL**：RAW integrity、線性度、repeatability、transition、compression 或其他 critical gate 失敗。
- 只有真實相機 Full Qualification 的正式 PASS 才會設定
  `profile_usable_for_production: true`。Pilot、Quick Verification、synthetic/fake camera、缺 Dark
  或缺 repeats 一律為 false。

Quick Verification 載入既有正式 profile，使用 G100 的 5–7 個代表曝光點、Light/Dark 各 3 張，
輸出 `PROFILE STILL VALID`、`PROFILE DRIFT WARNING` 或
`PROFILE INVALID — FULL QUALIFICATION REQUIRED`，不建立新的正式 production profile。

## Analyze Existing Folder

此頁可分析本工具 session、一般 TIFF＋JSON sidecar 資料夾，以及含可辨識 camera metadata 的既有
EL test 資料。先執行 preflight，列出 TIFF/JSON、缺 sidecar、dtype/shape、bit depth、DN maximum、
alignment、Gain/Exposure/repeats、Dark completeness、溫度、readback、sequence 與 ROI 狀態。
沒有 Dark 或 repeats 時仍可做 exploratory analysis，但結論上限是
`CONDITIONAL PASS / INSUFFICIENT EVIDENCE`。Critical DN metadata 不可靠時會 fail closed，不能產生正式 profile。

## 光源與重新驗證

- 不建議使用會隨時間衰減或升溫漂移的 EL 樣品作為唯一 calibration source。
- 最佳選擇是均勻、穩定、可重現的平場光源。
- 若使用 EL 樣品，結果只能視為 system-level empirical qualification，不能取代相機物理校正。
- 完整 qualification 不需要每次量測都做；日常可用 Quick Verification 檢查 drift。
- Dark frames 受 Exposure、Gain、溫度與時間影響，不能永久沿用一次。
- 更換相機、鏡頭、解析度、pixel format、SDK/driver、capture timing、ROI 定義或驗證溫度範圍後，
  應重新執行 Full Qualification。

## 檔案完整性

每張正式影像保存原始 uint16 MONO16 TIFF 與 atomic JSON sidecar。分析使用 float32/float64 matching-dark
subtraction且保留負值，不覆寫、normalize、tone-map、Gamma、auto-contrast、加 footer 或轉成 8-bit。
sidecar 保存 requested/actual Exposure/Gain、frame sequence、settling count、溫度、ROI、RAW metadata、
software commit 與 TIFF SHA-256。Manifest 與 JSON 採 atomic replace。

## 開發驗證

```powershell
python -m unittest tests.test_camera_linearity_qualification -v
python -m unittest discover -s tests -v
python -m compileall -q gui tools tests
```

Automated tests 使用 fake camera 與小型 synthetic uint16 frame，不需要 CI 連接相機。這些測試只驗證
軟體邏輯，不代表真實 RisingCam、光源均勻度、鏡頭、溫度或長曝光 timing 已完成硬體驗證。
