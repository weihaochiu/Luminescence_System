# EL 量測設備控制程式架構

文件版本：1.9.1
對應程式版本：V1.9.1
最後更新：2026-08-25（UTC+8）

## 0. 雙語與中央錯誤架構

`core/i18n.py` 是所有 user-facing 文字的單一入口，從 `resources/locales/` 載入 `zh-TW`／`en-US` namespaced catalogs，以 `ui/language` 持久化並用 `language_changed` 通知可即時重譯的視窗。Recipe、Settings 與 ComboBox persistence 只使用 canonical data，不依賴顯示文字。

錯誤依賴方向為 `hardware/workflow failure → GUI/controller boundary → ErrorReporter → structured log + bounded session history + presentation`。`resources/errors/error_registry.json` 只保存穩定 code、subsystem、severity、recoverability、translation key 與 actions；`core/error_context.py` 建立有界且可序列化的 diagnostics；`gui/dialogs/error_dialog.py` 與 `gui/error_center/` 負責 UI。硬體層不匯入 PySide dialog，Critical definitions 不得包含 Ignore／Continue。

Registry action 不是裝飾性 metadata：Dialog 只有在 MainWindow/controller 提供該事件的真實 handler 時才顯示按鈕。沒有通用 Retry；Camera、Relay、SMU reconnect 各自 dispatch。Handler 回傳 True 只表示 request accepted／action started，不代表非同步硬體復原已成功。量測進行中不提供 reconnect。

SMU safety faults are identity-bound. An OUTPUT UNKNOWN fault can only be recovered by the same physical SMU that generated the fault. `SMUFaultIdentity` 保存 VISA resource、serial、manufacturer、model 與完整 IDN；serial 是強 identity，並要求 manufacturer/model 相符。同 serial/model 在重新插拔後允許 VISA resource 改變；同 resource 但 serial 不同必須拒絕。serial 不可取得時，只接受相同 resource 與完整非空 IDN 的保守 fallback。fault identity 在第一次 UNKNOWN/fault latch 後不可由後續錯誤覆寫，跨 transport unbind/disconnect 保留，且 `bind_driver()`、connection manager、pending reconnect target、connected callback 與 `recover_safety_fault()` 都各自重新驗證。

Runtime 語言切換由 `language_changed` 觸發集中 retranslation。所有 ComboBox 以 `QSignalBlocker` 保留 canonical `itemData()` 與 selection，retranslation 不送硬體命令、不改 Recipe／Settings／metadata。`InstrumentStateManager` 只發布 canonical state 派生的當前語言 snapshot，不保存長期翻譯狀態。

## 1. 文件目的

本文件是程式結構的主要依據，說明模組責任、依賴方向、資料流、安全邊界與新功能應放置的位置。修改程式架構時必須同步更新本文件；新增或變更使用者需求時必須同步更新 `REQUIREMENTS_LOG.md`。

本專案採「依職責拆分、避免過度零碎」原則。檔案大小是需要檢視的訊號，不是機械式拆分門檻。只有當功能具備獨立責任、生命週期、I/O 邊界或可單獨測試的介面時，才建立新模組。

## 2. 啟動與主要資料流

1. `main.py` 呼叫 `gui.app.main()`。
2. `app.py` 建立 Qt Application 與 `MainWindow`。
3. `MainWindow` 建立相機控制器、SMU 連線／控制／監測服務與 Recipe Store。
4. 主畫面從 Store 載入通過驗證的 Recipe；EL Matrix 的 Sample ID 與 Area 由各 Logical Channel 保存。
5. 使用者確認無硬體動作的量測摘要後建立 immutable Measurement Snapshot，完整 preflight 在任何 OUTPUT ON／routing／capture 前彙整執行；worker 只讀 snapshot，主執行緒持續處理 Live View、Progress 與安全停止。
6. worker 依序執行全 Channel polarity、verified all-off、一次 Shared Dark，再逐 Channel 執行 Dark I–V 與 EL Matrix；所有 exit path 共用 verified safe shutdown。
7. 只有 Runner 回傳 SMU OUTPUT OFF、routing OFF、White Light OFF、ownership released 全部成功後，才由 `pixel_csv_postprocessor.py` 從 RAW TIFF 產生 Pixel CSV；CSV 失敗不回寫或刪除硬體量測資料。

## 3. 分層與依賴方向

依賴方向固定為：

`GUI／協調層 → 應用服務與資料模型 → 硬體介面／檔案 I/O → 原廠 SDK`

下層不可反向匯入主視窗或 Recipe 對話框。數值分析模組不可依賴 Qt、相機 SDK 或 SMU，確保可在無硬體環境測試。

## 4. 模組責任

### 4.1 應用入口與主視窗

| 模組 | 單一責任 | 不應包含 |
| --- | --- | --- |
| `main.py` | 最小啟動入口 | UI、硬體或資料邏輯 |
| `app.py` | Qt Application 初始化 | 量測流程 |
| `main_window.py` | 主狀態、Recipe 協調、應用生命週期 | 大量 widget 建構、相機 SDK 細節 |
| `main_window_ui.py` | 主畫面、選單、工具列、狀態列、訊號連接 | Recipe JSON、相機 SDK 命令 |
| `main_window_devices.py` | 相機／SMU 連線、UI request routing、Live View、曝光拍攝、一般影像存檔 | SCPI、ownership、safety、polarity |
| `main_window_measurement.py` | Recipe worker 生命週期、Manual 啟動確認與 finally safety cleanup 接線 | SCPI、polarity calculation |
| `device_panel.py` | 左側相機、SMU 與有效 Recipe 清單 | 設備驅動與檔案儲存 |

`MainWindow` 使用少量 mixin 組合完整行為。Mixin 只用來分離大型 UI 類別的明確職責，不應再拆成每個按鈕或每個事件一個檔案。

曝光控制的 widget 狀態統一由 `main_window_devices.py::_update_exposure_control_state()` 決定。`ExposureMode` 與影像亮度目標驗證位於 `camera_exposure.py`；目前影像亮度的 0–255 preview 計算位於 `image_brightness.py`。`CameraController` 負責 SDK capability/status query 與 300 ms refresh，GUI 只呈現狀態並 routing 使用者命令。共用的相機連線／中斷函式不可直接覆寫 Exposure、Gain、影像亮度目標或套用按鈕的個別狀態，避免連線狀態與自動／手動模式互相衝突。

Live View Scientific DN／SDK AE Metering ROI 的資料流固定為：

```text
ImageView image-pixel ROI
 ├─→ scientific_frame_ready uint16 H×W frame
 │    → scientific_dn.mean_effective_dn_roi()
 │    → Live View ROI Mean Effective DN
 │
 └─→ CameraController public API
      → put_AEAuxRect(x, y, width, height)
      → get_AEAuxRect() exact readback verification
      → RisingCam SDK Continuous / Once Auto Exposure
```

- `ImageView` 只管理 scene overlay 與 viewport／scene／原始 image-pixel 座標轉換；overlay 不修改 QImage、scientific ndarray、capture pixels 或輸出檔案。
- MainWindow 只保存 controller 已建立的最新 scientific ndarray reference，不為每幀複製 full frame；ROI calculation 只建立 slice view，Effective DN 的 bit depth／right-left alignment interpretation 沿用 `scientific_dn.py`。
- `scientific_frame_ready` 與 `effective_dn_status_changed` 都會觸發 ROI refresh，以處理同一 frame 中 alignment status 較晚更新的 signal ordering；alignment unknown 時 fail closed 顯示無法判定。
- GUI 不得存取 private camera handle；AE rectangle requested／readback／mode／verification state 的 single source of truth 是 `CameraController`。只有 requested 與 `get_AEAuxRect()` readback 完全一致時才是 verified；write/readback/mismatch 失敗不影響 Scientific ROI overlay 與 DN 顯示，但 SDK AE 維持關閉並顯示失敗狀態。
- `NNCAM_OPTION_AUTOEXPOSURE_PERCENT=100` 固定代表 full active AE ROI average；active rectangle 是完整影像時才等同 full-frame average。Camera open、Clear ROI 與 resolution change 都明確設定並驗證 `(0, 0, current_width, current_height)`，且必須在重新啟用 AE 前完成。
- Whole-frame `MeanEffectiveDN` 保持 diagnostic 語意；`MeteringMeanEffectiveDN` 在 verified custom ROI 使用相同 Effective-DN ROI interpretation，在 full-image mode 等於 whole-frame mean。AE calibration、stability fallback 與 convergence record 只使用 metering mean，calibration schema 以 camera／resolution／alignment／AE ROI geometry 隔離 profile。
- 相同解析度保留 ROI；解析度變更、image clear 或 camera disconnect 清除 GUI ROI。ROI 不保存至 QSettings／Recipe／metadata，也不裁切 acquisition、正式量測或影像輸出。

Camera Temperature Monitoring 的依賴與資料流固定為：

`Nncam.get_Temperature() → CameraController.read_temperature_c() → CameraTemperatureMonitor → GUI / Chart / CSV / image metadata`

- Bundled SDK 回傳 signed 0.1 °C；`CameraController` 在相機 owner Qt thread 內除以 10 轉為 °C，其他模組不得直接 query SDK handle。
- 相機成功連線後以固定 1 秒 `QTimer` polling。`camera_closing` direct signal 必須先停止 timer、flush/close CSV、清除 latest sample，再關閉 SDK handle。
- Chart 只保留最近 30 分鐘（1800 samples）的顯示資料，但 session CSV 保存全部有效 samples。關閉 Chart 只隱藏 presentation，不停止 monitoring 或 logging。
- CSV 位於 AppData `logs/camera_temperature_YYYYMMDD_HHMMSS.csv`，欄位為 `timestamp,temperature_c`，timestamp 使用含 milliseconds 與 timezone 的 ISO 8601。
- 寫圖時只消費 `CameraTemperatureMonitor.metadata_fields()`。最近有效 sample 超過 3 秒即視為 stale；unavailable/stale 時省略 `CameraTemperature_C` 與 `CameraTemperatureTimestamp`，不寫 0 或 `None`。
- 一般 TIFF／PNG／JPEG／BMP 沿用既有同名 JSON sidecar；metadata I/O 不改變 image pixels 或 bit depth。
- 暫時 SDK error、invalid value 或 unavailable 為 non-fatal，當次 sample 跳過並在下一 interval 重試；缺少 `NNCAM_FLAG_GETTEMPERATURE` 時記錄一次 unsupported、顯示 N/A 並停止無意義查詢。

類別內不需要 instance 狀態的格式化 helper 必須明確使用 `@staticmethod`；其餘方法必須保留 `self`／`cls` 參數。`_format_exposure()` 由相機開啟、手動套用與自動曝光訊號共同呼叫，測試需驗證其 descriptor 綁定方式，不能只檢查函式內容。

### 4.2 Recipe

| 模組 | 單一責任 |
| --- | --- |
| `recipe_store.py` | Recipe dataclass、schema v10、Channel／Matrix、明確舊版遷移／future rejection、Matrix safety 驗證與 Store |
| `recipe_dialog.py` | Recipe 管理對話框外殼、頁面導航與穩定公開入口 |
| `recipe_dialog_pages.py` | 四個設定頁與 widget 建構 |
| `recipe_dialog_logic.py` | 表單與 Recipe 雙向綁定、CRUD、驗證、摘要、JSON 匯入／匯出 |

`recipe_store.py` 即使較長仍維持單檔，因為 schema、遷移、驗證及時間估算共享相同資料不變條件。只有日後出現第二種獨立量測類型或 schema 遷移顯著增加時，才重新評估拆分。

### 4.3 相機、SMU 與輸出

| 模組 | 單一責任 |
| --- | --- |
| `camera_controller.py` | RisingCam SDK 包裝、相機事件、曝光／Gain、溫度安全存取與影像串流 |
| `camera_temperature_monitor.py` | 1 秒溫度 polling、latest snapshot、30 分鐘 rolling history、CSV session 與 non-fatal 錯誤處理 |
| `camera_temperature_chart.py` | Camera Temperature vs Time 呈現、目前值與 session min/max；不控制 monitor 生命週期 |
| `smu_base.py` | SMU 裝置與驅動抽象 |
| `keysight_b2900.py` | Keysight B2900 系列識別與連線驅動 |
| `smu_manager.py` | 背景 VISA 掃描、連線、狀態與安全中斷 |
| `smu_control.py` | ownership/output single source of truth、Manual/Recipe interlock、polarity、安全驗證與序列化命令 |
| `instrument_state_manager.py` | 合併 connection／ownership／operation／output，產生唯一的 GUI enablement policy |
| `smu_monitor.py` | 500 ms 非阻塞 readback 排程；Recipe ownership 時略過 polling |
| `smu_manual_panel.py` | CV/CC、setpoint、compliance、輸出按鈕與 readback 顯示；不匯入 driver／VISA |
| `measurement_control_bar.py` | 底部 context/actions 的單一 widget set 與 WIDE／STANDARD／COMPACT 重排 |
| `el_matrix_plan.py` | 無硬體依賴的固定順序、capture count、純曝光與 pre-run ETA |
| `el_matrix_preflight.py` | SMU identity/VISA、Relay mapping、Camera capability/format、輸出與磁碟空間的聚合式 preflight |
| `measurement_snapshot.py` | 遞迴 immutable Measurement Snapshot、canonical SHA-256 與原子落盤 |
| `el_matrix_runner.py` | 全 Channel polarity → Shared Dark 一次 → 每 Channel Dark I–V → J → Gain → Exposure → Repeat；runtime watchdog 與共用 safe shutdown |
| `measurement_output.py` | RAW TIFF、Footer JPG、逐張 JSON，以及 atomic Pixel CSV writer |
| `pixel_csv_postprocessor.py` | verified safe-shutdown 後的 TIFF-based Pixel CSV、Shared Dark 配對、SHA-256 manifest、atomic status 與續作 |
| `el_matrix_hardware.py` | runner 到既有 SMU／Relay／Polarity／Camera authority 的安全轉接 |
| `camera_capture_bridge.py` | worker 等待既有 pull-mode stream 的下一張正式 frame；不建立第二 camera stream |
| `measurement_progress_dialog.py` | modeless progress presentation；不自行重算 measurement state |
| `measurement_output.py` | RAW TIFF、下方 Footer JPG、metadata／CSV 與安全檔名 |
| `responsive_layout.py` | logical width、available geometry、font metrics 與 DPI context 的 breakpoint 判定 |
| `image_io.py` | 一般影像與同名 JSON metadata 儲存；metadata 不修改 image pixels |
| `widgets.py` | 可重用的影像顯示與可收合區塊 |

原廠 `sdk/nncam.py` 與 DLL 視為 vendor code，不進行一般格式化或重構。

### 4.4 Standalone Ruler Scale Calibration

Ruler calibration 的依賴方向固定為：

```text
Standalone tester GUI / batch CLI
                 ↓
core.calibration.CalibrationService
                 ↓
ruler detector → rectifier → tick detector + digit recognizer → scale solver → overlay
```

- `core/calibration/` 是無 Qt、無相機 SDK、無 SMU／Relay／Recipe 依賴的 production-reusable 數值核心；正式整合只能呼叫相同 service，不可從 tester GUI copy/paste 演算法。
- `tools/ruler_scale_calibration_tester/` 負責 CameraController 接線、Image File I/O、diagnostic GUI、debug package、batch regression 與 repeatability presentation，不修改正式 Recipe sequence。
- Camera mode 只使用既有 `CameraController` 的 MONO16 `scientific_frame_ready`；tester 不直接存取 private SDK handle，也不建立第二 camera wrapper。
- Rectified `(u,v)` 只供 detection/OCR。所有 accepted tick center 以 inverse homography 回到 original image，再沿 original ruler axis fitting；`pixels/mm` 明確屬於 original stored image plane。
- Solver 先估計無單位的 `periodic_pitch_px`，再以 tick position/length/hierarchy 與 OCR 評估 1/2/5/10 mm `PhysicalPitchHypothesis`；只有 `tick_hierarchy_verified` 或 `ocr_verified` 才建立 `pixels_per_mm` 並 PASS，periodic geometry 單獨不得假定為 1 mm。
- OCR backend 是可替換 `DigitRecognizer`。pytesseract 是 tester optional dependency；Tesseract unavailable 時明確回報 diagnostic，不下載模型、不產生假值。OpenCV 因 reusable calibration core 直接 import，仍是 root mandatory dependency。
- quality score 是已定義的 engineering score，不宣稱 probability，且不得越過 physical-pitch correctness gate。GUI 的 Live View 與 frozen Captured input 分離；repeatability 僅由人工加入、使用 source identity 防重並可匯出 UTF-8 CSV。
- `local/generated/`、`local/datasets/`、`local/ocr_cache/` 是本機 evidence/data/cache boundary，必須維持 Git ignored。

### 4.5 Relay 控制邊界

| 模組 | 責任 |
| --- | --- |
| `relay_controller.py` | USB HID discovery／runtime connection、8-channel command、Group operation rollback 與 audit log |
| `relay_settings.py` | Device identity、Channel／Group schema、JSON persistence、Group channel conflict validation |
| `relay_settings_dialog.py` | `設定 → Relay 設定…`，提供 Channel／Group 編輯與維修用手動控制 |

### 4.6 Standalone Camera Linearity Qualification

`tools/camera_linearity_qualification/` 是獨立 GUI 與分析邊界。Camera mode 只透過既有
`CameraController`、`CameraCaptureBridge` 接收 MONO16 scientific frame；不得直接存取 private
SDK handle，也不得建立第二條 stream。`capture_plan`/`capture_runner` 負責 ordered Gain × Exposure、
setting readback、settling、frame-sequence barrier、guided LIGHT/DARK、safe cancellation/state restore 與
atomic TIFF/JSON/manifest。`image_loader`/`analysis`/`regression` 是離線數值層，`report`/`profile` 負責
CSV/PNG/Markdown 與 production-gated versioned profile。

此工具不得匯入或改寫 Recipe、SMU、Relay、EL Matrix runner、production output pipeline。
Pilot、Quick、synthetic/fake、缺 Dark/repeats 或非完整 PASS 的 profile 均維持
`profile_usable_for_production=false`；真實 RisingCam/平場光源驗證屬硬體 acceptance，不能由 CI 宣稱完成。

HID path 僅供當次連線使用，設定檔不保存 USB port、Windows location 或 path。主畫面白光控制只能呼叫 `RelayService.group_on/off("white_light")`；CH1／CH2 的單獨控制僅位於設定視窗。Group ON 部分失敗會對全部 member 嘗試 OFF rollback，Group OFF 則累積失敗但繼續操作後續 member。

## 5. Recipe 與 EL Matrix 邊界

- Recipe 的 `el_matrix.current_density_ma_cm2`、`gains_percent`、`exposures_ms` 與 `repeat` 是正式 capture sequence 的唯一來源。
- Recipe schema 不含 HDR；legacy `hdr` key 僅在讀取時忽略，重新儲存後不再存在。
- Execution Plan 與 runtime 都固定使用 Channel → Current Density → Gain → Exposure → Repeat。
- 量測快照保存當次完整 Recipe、相機／SMU／Relay 條件、正式執行順序與輸出設定。

## 6. SMU 架構與安全邊界

```text
MainWindow / signal wiring
├─ InstrumentStateManager → immutable SMUUIState
│  └─ ManualSMUPanel / DevicePanel (presentation only)
└─ Recipe worker lifecycle
              │
              ▼
SMUControlManager  ← ownership/output/operation state Single Source of Truth
├─ PolarityService ← UNKNOWN / confirmed factor Single Source of Truth
├─ SMUSafetyService
├─ SMUMonitor (500 ms request; skips RECIPE/busy)
└─ serialized I/O lock + one-worker queue
              │
              ▼
SMUDriver interface
              │
              ▼
KeysightB2900Driver ← instrument-specific SCPI
              │
              ▼
shared VISA resource / physical SMU
```

Manual 與 Recipe 在 `SMUControlManager` 互鎖。所有高階 output transition 經此層；Manual panel 不保存另一份 output/ownership state，也不建立 VISA connection。Manual Output 的 busy check、MANUAL acquire 與 enqueue 在同一個 state lock 內完成，busy rejection 不得 release 既有 ownership。`operation_state_changed` 將 READY、BUSY、OUTPUT_ON、RECIPE_LOCKED、EMERGENCY／SHUTTING_DOWN 與 FAULT 同步到 UI，控制層仍是唯一 authoritative state。

`InstrumentStateManager` 不取代底層 interlock，而是唯一負責 GUI policy：它把非同步連線生命週期與 control 的 ownership／operation／output／`output_confirmed_off` 合併成不可變 `SMUUIState`。`READY_MANUAL` 僅允許 `IDLE + READY + output_enabled=False + output_confirmed_off=True`；Manual 正常輸出使用 `MANUAL_OUTPUT_ON`，`IDLE + READY + OUTPUT ON` 等矛盾組合進入 `UNEXPECTED_OUTPUT_ON`，只開放安全 OFF／Emergency。`SMUControlManager.bind_driver()` 每次綁定或解除都發布完整 snapshot，避免 UI 保留上一個 session 的 BUSY、RECIPE 或 FAULT。Camera state 不輸入此 manager，因此 Live View、曝光或拍攝不會鎖定 SMU Manual。

啟動自動連線只選擇上次成功 serial、上次成功 VISA resource，或掃描結果中唯一受支援的 SMU；多台且無法判定時 fail closed，交由使用者手動選擇。受支援 B2900 driver 必須依序送出 `OUTPUT OFF`、以 `:OUTP?` 明確確認 False、設定並讀回確認 `:OUTP:ON:AUTO OFF`、將 source voltage/current 歸零，再次確認 OUTPUT OFF，才可發布 connected／READY_MANUAL；任何 driver bind／初始化失敗均關閉 resource 與 resource manager、清空所有 session 欄位並進入 connection ERROR。

`PolarityService` 預設為 `UNKNOWN`（factor `None`）。Manual setpoint 是 SMU 實體座標，直接送至儀器且不依賴 Polarity；Recipe setpoint 才是 Device 座標。EL Matrix 會先對每個 Channel 完成 Jsc／Voc determination 並保存結果，之後 Channel 重入時只在 verified OUTPUT OFF 狀態重套該 Channel 的明確 `+1` 或 `-1`。`set_confirmed_factor()` 為 idempotent assignment 而非 toggle；不得略過或沿用上一 Channel factor。

Emergency request 先設定 threading Event latch，再排入相同 single-worker queue 做 `safe_shutdown()`。Normal operation 會在 configure 前及真正送出 `OUTPUT ON` 前檢查 latch；最後一段 check／OUTPUT ON 與 Emergency latch transition 有明確同步邊界，因此 Emergency 之後尚未送出的 normal output 不會開啟。已在執行中的 blocking PyVISA call 不宣稱可被 preempt。Emergency shutdown 完整成功且 OUTPUT OFF 後才回到 IDLE 並清除 latch；failure 則保留 latch/錯誤並進入 FAULT。

Manual → Recipe 交接必須先完成 verified shutdown，釋放至 IDLE 後才允許 Recipe acquire。Recipe → Manual 交接先設 cancel latch 封鎖新 Recipe output、通知 worker cancel、關閉白光，再等待目前 I/O safe point 執行 verified shutdown；只有 `OUTPUT OFF` 明確確認後才回到可手動狀態。EL Matrix 的 Channel transition 使用 `recipe_output_off()` 保留 Recipe ownership，但仍要求 OUTPUT OFF readback 後才允許 routing break-before-make。

一般 disconnect 只有在 hardware query 明確回傳 OFF、ownership 為 IDLE 且 control 無 pending I/O 時才允許；True 或 `None` 均 fail-closed。`safe_shutdown()` 的固定順序為 `:OUTP OFF` → `:OUTP? == False` → source 歸零，並以 `output_confirmed_off`／`last_shutdown_ok` 區分完整成功與失敗；query 為 ON、UNKNOWN、exception 或任何 `safe_stop()` failure 都不得宣告安全，必須進入 FAULT。

Identity-bound recovery 的唯一成功路徑為 `UNKNOWN detected → identity latched → transport disconnected → reconnect same physical SMU → OUTPUT OFF readback → Relay routing OFF verification → White Light OFF verification → clear fault identity/latches → IDLE/READY`。找不到 target、掃描結果為零或多個、serial/model mismatch、reconnect failure、OUTPUT 非 OFF、Relay verification failure、White Light verification failure，任何一項都保留原 fault identity、FAULT ownership 與 global output lock。普通 connect／startup auto-connect 不可選擇另一台 SMU；pending reconnect request 失敗時只清除 pending operation，不清除 persistent fault。

目前 fault identity 與 UNKNOWN latch 僅存在 process memory。Repository 尚無可沿用的 atomic persistent hardware-fault journal，因此本次不以 QSettings 草率新增 crash-recovery state；若 application 在 unresolved fault 時被強制終止或斷電，重新啟動後不會恢復該 latch。這是已知 remaining risk，實體設備仍須由 operator 面板確認 OUTPUT OFF。

Readback 由 `SMUMonitor` 的 Qt timer 觸發，但實際 query 在控制層的單一 worker 執行；I/O lock 同時涵蓋 Manual、Recipe、readback 與 shutdown。Recipe ownership 或 busy 時不排入 readback，避免 critical command 中插入 query。B2901BL 實機已確認 OUTPUT OFF 時送出 `:MEAS:VOLT?` 會自動開啟 Source Output，因此 periodic readback 採 OUTP-first：先查 `:OUTP?`，OFF 時禁止 voltage/current/compliance measurement；只有 `MANUAL + OUTPUT_ON` 才量測。其他 OUTPUT ON 組合只發布 output 狀態，保留既有 `UNEXPECTED_OUTPUT_ON` 復歸流程。

V1.5.2 修正 B2901BL readback auto-output：OUTP-first、OUTPUT OFF 禁止 `MEAS:*` polling、B2900 auto-output 明確停用並讀回確認；Recipe、Polarity 與 `UNEXPECTED_OUTPUT_ON` 安全狀態不變。
V1.5.1 修正 Manual 實體座標、矛盾 readback 復歸、verified shutdown、雙向安全交接與單一 UI snapshot；V1.8.1 完成 EL Matrix polarity、Dark I–V、snapshot、preflight、watchdog 與輸出閉環。

## 6.1 Responsive GUI 邊界

- `MeasurementControlBar` 只建立一批 widget；layout mode 變更時只重新配置 grid row／column，不複製 signal 或資料狀態。
- breakpoint 集中在 `responsive_layout.py`，輸入為 Qt logical window/content width、screen available geometry、font metrics；`devicePixelRatioF()` 保留為目前 DPI context，不以 physical resolution 硬編碼條件。
- runtime FontChange／ApplicationFontChange／StyleChange／screenChanged 會呼叫 `MeasurementControlBar.refresh_metrics()` 並重新選擇 layout mode。
- WIDE 以單列為主，STANDARD 分離 context/path/actions，COMPACT 採逐列 context 加固定可見 actions。Browse、Start、Stop、Emergency Stop 在所有模式均存在且不進入 scroll area。
- Device Sidebar 與 Live View 使用 `QSplitter`；sidebar 只有 minimum/default width，沒有 fixed width。Sidebar 本身沿用 `QScrollArea` 以支援低高度視窗。
- Save Path 的實際 `QLineEdit.text()` 永遠保存完整字串；顯示空間不足時由 QLineEdit 水平捲動，tooltip 同步完整路徑。

## 7. 新功能放置準則

1. 先在 `REQUIREMENTS_LOG.md` 建立需求 ID、驗收條件與狀態。
2. 判斷功能屬於 UI、協調、資料模型、硬體、數值算法或輸出 I/O。
3. 優先擴充既有高內聚模組；只有責任與生命週期明確獨立時才新增檔案。
4. 若既有檔案接近 500–600 行，需人工檢視是否混合兩個以上職責，但不可只因行數拆分。
5. 新模組名稱必須反映功能職責，不使用 `utils2.py`、`misc.py` 或無語意名稱。
6. 公開匯入路徑如需搬移，應保留相容轉接，避免既有測試與外部呼叫立即失效。
7. 完成後更新架構文件、需求狀態、README 版本紀錄及測試。

## 8. 相機溫度功能預定位置

尚待實作的溫度監控應採一個獨立但完整的 `camera_temperature.py`（名稱可在實作時確認），負責：SDK 溫度讀取、固定週期採樣、時間序列緩衝、CSV／log 寫入與對外訊號。Trend chart 的 widget 可放在同一功能模組或現有 UI 模組中，取決於是否可獨立顯示；不得把 SDK polling、圖表與 metadata 寫入全部塞回 `main_window.py`。

溫度資料對外提供後，由一般影像存檔與未來量測快照模組寫入每張影像 metadata，避免多個模組各自重複查詢 SDK。

## 9. 驗證策略

- `python -m compileall -q gui tests`：所有 Python 檔案語法檢查。
- `python -m unittest discover -s tests -v`：EL Matrix、Recipe schema、量測快照、UI 結構、輸出與模組邊界。
- Windows 實機驗證：RisingCam 連線、Live View、曝光／Gain、一般拍攝、VISA 掃描與 B2900 安全連線。
- Ruler calibration：scale/scale-bar math、missing/false/noisy tick robust fit、OCR sequence outlier、0/30/90/135/180/270° synthetic ruler、no-ruler/no-tick/OCR-unavailable failure regression；synthetic 結果不可替代實際相機＋鐵尺 acceptance。
- 涉及 SMU 輸出的版本必須另建硬體模擬、錯誤注入與緊急停止測試；race test 使用 Event／Barrier 控制 timing，不以 sleep 猜測 configure 與 OUTPUT ON 的時序，也不能只依賴 GUI 手動測試。
