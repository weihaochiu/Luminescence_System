# Requirements Log

## HDR-VIEW-001 — Offline batch HDR viewer (2026-10-09)

- Requested: standalone viewing-only HDR generation, launched by a main toolbar button; choose a folder and recursively discover EL TIFF/JSON captures.
- Group by MeasurementRunID, SampleID, Channel, commanded current density and Gain. Average repeats at each exposure; never combine runs or gains. Missing run IDs may use an identifiable original run folder; ambiguous inputs are excluded with reasons.
- Generate one HDR result per eligible condition (at least two distinct exposures), with float32 uncalibrated TIFF, 16-bit tone-mapped TIFF, PNG, JSON provenance and batch CSV. Preserve source files and exclude generated output on subsequent scans.
- Background scan/generation, cancellation, progress, elapsed time, remaining-time estimate and estimated finish. Completed groups remain usable after cancellation/failure.
- Reserve a versioned correction interface; first release has no quantitative mode or production calibration claim. Tone mapping affects viewing copies only. No camera/SMU/Relay operations or Recipe changes.
- Status: software implemented; 20/20 new HDR tests and complete regression 775/775 passed (2026-10-09). Qt visual QA generated three synthetic J groups and verified the viewer/toolbar layout. Real EL dataset acceptance remains separate.

## LIGHT-002 — 光源 CH 自訂名稱

- Requested: 2026-10-07。
- 光源設定新增 CH1～CH4 名稱輸入，名稱自動保存至 QSettings `light/channels/{1..4}/name`；前後空白去除，空白名稱保留 CH 編號顯示。
- Sidebar 下拉選單立即顯示「CH2（藍光光源）」；保留 CH1～CH4 的整數 itemData、目前選取與強度。名稱更新、語言切換不發送串口命令。
- 名稱在重開程式後恢復；使用者輸入的文字不隨 UI 語言翻譯。名稱只用於識別，不作燈具連接偵測，也不加入通道啟用／停用功能。
- Acceptance: 名稱保存／恢復、空白回退、雙語顯示、選取不變與正確實體通道命令的 fake-device regression。

## LIGHT-001 — GSP-4H 主程式整合

- Requested: 2026-10-06。
- Sidebar：同一個可收合「光源控制」區塊包含連線狀態、自動連線按鈕、全機光源開關、CH1～CH4 下拉選單及所選 CH 的 0～255 強度（滑桿／數字）。切換 CH 不寫硬體、不改其他通道。
- 拍照：沿用現有 Sidebar 手動拍照及曝光／Gain 控制，不新增光源專用拍照按鈕或另一相機串流。
- 設定選單：PORT／轉接器資訊、重掃與手動連線、安全斷線、None／Even／Odd 同位檢查、啟動自動連線偏好、上次成功設備、模式及四通道讀回、通訊紀錄匯出。
- 連線不自動點燈；四通道設定自動原子保存、讀回與要求值分離、一般關燈保留強度。主程式首次缺少設定時可匯入有效的獨立工具亮度，保留來源檔。
- 安全：單一背景串口 owner；量測／手動極性前取消開燈與待送亮度、重新驗證 L；量測期間互鎖；Emergency 驗證 L＋四通道歸零；退出驗證關燈與串口釋放後結束執行緒，失敗取消退出。光源讀回異常會保留安全清理責任。
- GSP-4H 為選配；既有 Relay 白光／極性照明維持原流程。未加入 Recipe 調光、PL 自動拍攝、外部觸發或同步。
- Status: 已實作軟體整合；自動化測試使用模擬串口，GSP-4H 實機接線及實際熄燈仍需驗收。

## CLQ-001 — Standalone Camera Linearity Qualification

- Requested: 2026-08-28
- Scope: `tools/camera_linearity_qualification/` and standalone root launcher only.
- Acceptance: Existing CameraController/CameraCaptureBridge MONO16 stream; guided Light/Dark capture;
  fixed ROI; versioned criteria; RAW/dark/exposure/gain/repeatability/compression/transition/HDR analysis;
  PASS/CONDITIONAL PASS/FAIL; gated camera profile; reports; fake/synthetic automated tests.
- Production boundaries: no Recipe, SMU, Relay, EL Matrix runner, or production output integration.
- Status: Implemented in software; real RisingCam + stable flat-field acceptance remains required.
