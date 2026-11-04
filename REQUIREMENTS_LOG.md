# Requirements Log

## RECIPE-RELEASE-001 — ROI 與自動曝光整合推送前驗證（2026-11-04）

- 使用者授權將 Recipe 自動曝光／Gain／Stop 與各 Channel ROI 一併更新至 GitHub main；既有 HDR 工具列隱藏的 5 個暫存修改不納入本次提交，保留內容與原暫存狀態。
- 最新相關回歸 **179／179 通過**；完整 `.venv\Scripts\python.exe -m unittest discover -s tests -v` **846／846 通過**（0 failed、0 errors、0 skipped）。先前光源 GUI worker 逾時測試在未修改該工具與測試的情況下，單獨及完整套件重跑均通過。
- `compileall -q gui tests` 與 `git diff --check` 通過。以下各功能的先前失敗紀錄保留作歷史證據，以本節的最新完整回歸結果為準。實際 RisingCam、白光與 SMU／Relay 量測仍需實機驗收。

## RECIPE-ROI-001 — 各 Channel ROI 與裁切輸出（2026-11-04）

- Recipe 開始前開啟 Relay 白光，依啟用 channel 框選，固定 CH1→ROI1 至 CH4→ROI4；非連續 channel 不重新編號，1～4 channel 各選一次。
- ROI 僅屬本次量測並納入不可變 snapshot。每 channel 使用自己的 SDK AE 測光 ROI，驗證失敗停止量測。
- TIFF 保存 ROI 原始 scientific 像素，PNG／JPG／Footer JPG 與延後處理的 Pixel CSV 使用相同範圍；metadata 記錄原圖尺寸、ROI 座標及裁切尺寸。
- Shared Dark 不增加實體拍攝次數，分別輸出各 channel 的 ROI；CSV 暗校正比對 channel 與座標，避免同尺寸不同位置誤配。
- Footer 依 ROI 寬高調整字級、留白、換行與高度，不改變 ROI 像素；極小 ROI 的顯示文字可縮略，JSON 保留完整資訊。
- 流程、欄位與限制見 [Recipe 各 Channel ROI](docs/RECIPE_CHANNEL_ROI.md)。軟體測試與硬體驗收分別記錄；工作區既有修改保留，不自動 commit／push。
- 驗證：新增 ROI 測試 **23／23 通過**；完整 `unittest discover -s tests -v` **846 項中 845 通過、1 失敗**。唯一失敗是既有 `test_cancelling_lux_measurement_turns_off_light_through_worker` 的 `Worker did not complete`，與本次修改前已記錄的光源 GUI worker 逾時相同；未修改該工具或測試。`compileall -q gui tests` 與 `git diff --check` 通過。已產生並檢視 CH2／ROI2 設定視窗及不同長寬比 footer 圖片；白光與 RisingCam 實機驗收待完成。

## RECIPE-AE-001 — Recipe 自動曝光與 Gain 選擇（2026-11-04）

- 使用者最新要求：既有 Recipe 使用「手動曝光／自動曝光」下拉選單，下方動態顯示所選模式的設定表單；未選用表單隱藏並停用，切換時保留兩邊設定。取代原本兩組表單同時顯示、未選用者反灰的設計。
- 自動曝光提供自動 Gain 或指定單一 Gain；指定 Gain 時只調曝光時間。
- 時間預估同步：Recipe 右側即時計算、開始量測確認說明 AE 預算，執行中約每秒更新，按實際收斂曝光／Dark 去重修正；實際拍攝存檔較慢時允許完成時間延後。上方電流／電壓矩陣維持原樣。
- 自動曝光新增自訂 Stop 清單（含正負與小數），按輸入順序、每級 Repeat 拍攝；收斂 Gain 固定，曝光時間為基準 × 2^Stop。0 可省略，拍攝上限涵蓋所有 Stop，SDK 基準範圍會相應縮小；時間與 Dark 預算同步計算。
- 已加入 schema v13 保存；v12 自動曝光預設 Stop `[0]`，更早 Recipe 預設手動。每 Channel／電氣條件單次 AE 收斂後鎖定 Gain、後拍匹配 Shared Dark、上限估算及失敗／逾時／取消處理。
- 詳細操作、資料欄位、執行順序與驗收條件見 [Recipe 自動曝光規格](docs/RECIPE_AUTO_EXPOSURE.md)。
- 流程模擬：14／14 情境符合預期，相關回歸重跑 152／152 通過；雙通道主情境 4 次 AE、40 EL＋16 Dark、136 個 Pixel CSV 數值驗證通過。含取消／逾時、拍攝失敗與安全關閉未確認時阻擋後處理；本輪未改正式硬體程式。[模擬報告與流程圖](docs/RECIPE_AUTO_EXPOSURE_SIMULATION.md)。
- 狀態：已實作軟體流程；實際 RisingCam 收斂、Gain 鎖定與 Dark 拍攝待實機驗收。
- 驗證：自動曝光功能 26／26、時間預估 11／11、自訂 Stop 11／11，最新相關回歸 **152／152 通過**。完整 unittest **823 項中 822 通過、1 失敗**，為既有光源 GUI worker 等待逾時，單獨重跑仍失敗；該光源程式及測試未修改。前一時間預估版本曾達 812／812 通過；詳見規格文件驗證紀錄。本輪保留修改、不 commit／push。

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
