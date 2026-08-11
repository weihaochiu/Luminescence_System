# EL 量測設備控制程式架構

文件版本：1.5.1
對應程式版本：V1.5.1
最後更新：2026-08-12（UTC+8）

## 1. 文件目的

本文件是程式結構的主要依據，說明模組責任、依賴方向、資料流、安全邊界與新功能應放置的位置。修改程式架構時必須同步更新本文件；新增或變更使用者需求時必須同步更新 `REQUIREMENTS_LOG.md`。

本專案採「依職責拆分、避免過度零碎」原則。檔案大小是需要檢視的訊號，不是機械式拆分門檻。只有當功能具備獨立責任、生命週期、I/O 邊界或可單獨測試的介面時，才建立新模組。

## 2. 啟動與主要資料流

1. `main.py` 呼叫 `gui.app.main()`。
2. `app.py` 建立 Qt Application 與 `MainWindow`。
3. `MainWindow` 建立相機控制器、SMU 連線／控制／監測服務、Recipe Store 與 HDR Settings Store。
4. 主畫面從 Store 載入通過驗證的 Recipe，使用者選擇 Recipe、樣品 ID、輸出位置與 HDR T0／Aging 模式。
5. 現階段只完成設備連線、一般拍攝、Recipe／HDR 設定與資料契約；量測執行狀態機仍安全停用。

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
| `main_window.py` | 主狀態、Recipe/HDR 協調、應用生命週期 | 大量 widget 建構、相機 SDK 細節 |
| `main_window_ui.py` | 主畫面、選單、工具列、狀態列、訊號連接 | Recipe JSON、相機 SDK 命令 |
| `main_window_devices.py` | 相機／SMU 連線、UI request routing、Live View、曝光拍攝、一般影像存檔 | SCPI、ownership、safety、polarity |
| `main_window_measurement.py` | Recipe worker 生命週期、Manual 啟動確認與 finally safety cleanup 接線 | SCPI、polarity calculation |
| `device_panel.py` | 左側相機、SMU 與有效 Recipe 清單 | 設備驅動與檔案儲存 |

`MainWindow` 使用少量 mixin 組合完整行為。Mixin 只用來分離大型 UI 類別的明確職責，不應再拆成每個按鈕或每個事件一個檔案。

曝光控制的 widget 狀態統一由 `main_window_devices.py::_update_exposure_control_state()` 決定。共用的相機連線／中斷函式不可直接覆寫 Exposure、Gain、自動曝光目標或套用按鈕的個別狀態，避免連線狀態與自動／手動模式互相衝突。

類別內不需要 instance 狀態的格式化 helper 必須明確使用 `@staticmethod`；其餘方法必須保留 `self`／`cls` 參數。`_format_exposure()` 由相機開啟、手動套用與自動曝光訊號共同呼叫，測試需驗證其 descriptor 綁定方式，不能只檢查函式內容。

### 4.2 Recipe

| 模組 | 單一責任 |
| --- | --- |
| `recipe_store.py` | Recipe dataclass、schema v6、舊版遷移、驗證、警告、時間估算與 Store |
| `recipe_dialog.py` | Recipe 管理對話框外殼、頁面導航與穩定公開入口 |
| `recipe_dialog_pages.py` | 八個設定頁與 widget 建構 |
| `recipe_dialog_points.py` | EL 點位產生、表格解析、HDR 欄位反灰、相機欄位保存 |
| `recipe_dialog_logic.py` | 表單與 Recipe 雙向綁定、CRUD、驗證、摘要、JSON 匯入／匯出 |

`recipe_store.py` 即使較長仍維持單檔，因為 schema、遷移、驗證及時間估算共享相同資料不變條件。只有日後出現第二種獨立量測類型或 schema 遷移顯著增加時，才重新評估拆分。

### 4.3 HDR

| 模組 | 單一責任 |
| --- | --- |
| `hdr_settings.py` | 系統級 HDR 設定、驗證、雜湊與舊設定遷移 |
| `hdr_settings_dialog.py` | `設定 → HDR` 編輯介面 |
| `auto_hdr.py` | 曝光規劃、預掃描估算、第一幀過曝判定、提前終止、Dark 扣除與定量 HDR 合成 |
| `hdr_output.py` | 原始 EL／Dark、Master Dark、float32 TIFF、preview 與 JSON／CSV manifest |
| `hdr_profile.py` | T0 Profile 建立、簽章、保存、讀取與相容性檢查 |
| `hdr_workflow.py` | T0／Aging 使用者流程與 Profile 選擇 |
| `measurement_snapshot.py` | 完整有效設定與執行結果快照 |

`auto_hdr.py` 保留完整數值流程，避免把曝光規劃、過曝判定與合成拆成過多小檔案。`hdr_output.py` 獨立是因為其責任是檔案 I/O 與稽核 manifest，且可與數值算法分開測試。

### 4.4 相機、SMU 與輸出

| 模組 | 單一責任 |
| --- | --- |
| `camera_controller.py` | RisingCam SDK 包裝、相機事件、曝光／Gain 與影像串流 |
| `smu_base.py` | SMU 裝置與驅動抽象 |
| `keysight_b2900.py` | Keysight B2900 系列識別與連線驅動 |
| `smu_manager.py` | 背景 VISA 掃描、連線、狀態與安全中斷 |
| `smu_control.py` | ownership/output single source of truth、Manual/Recipe interlock、polarity、安全驗證與序列化命令 |
| `instrument_state_manager.py` | 合併 connection／ownership／operation／output，產生唯一的 GUI enablement policy |
| `smu_monitor.py` | 500 ms 非阻塞 readback 排程；Recipe ownership 時略過 polling |
| `smu_manual_panel.py` | CV/CC、setpoint、compliance、輸出按鈕與 readback 顯示；不匯入 driver／VISA |
| `measurement_control_bar.py` | 底部 context/actions 的單一 widget set 與 WIDE／STANDARD／COMPACT 重排 |
| `responsive_layout.py` | logical width、available geometry、font metrics 與 DPI context 的 breakpoint 判定 |
| `image_io.py` | 一般影像與同名 JSON metadata 儲存 |
| `widgets.py` | 可重用的影像顯示與可收合區塊 |

原廠 `sdk/nncam.py` 與 DLL 視為 vendor code，不進行一般格式化或重構。

## 4.5 Relay 控制邊界

| 模組 | 責任 |
| --- | --- |
| `relay_controller.py` | USB HID discovery／runtime connection、8-channel command、Group operation rollback 與 audit log |
| `relay_settings.py` | Device identity、Channel／Group schema、JSON persistence、Group channel conflict validation |
| `relay_settings_dialog.py` | `設定 → Relay 設定…`，提供 Channel／Group 編輯與維修用手動控制 |

HID path 僅供當次連線使用，設定檔不保存 USB port、Windows location 或 path。主畫面白光控制只能呼叫 `RelayService.group_on/off("white_light")`；CH1／CH2 的單獨控制僅位於設定視窗。Group ON 部分失敗會對全部 member 嘗試 OFF rollback，Group OFF 則累積失敗但繼續操作後續 member。

## 5. Recipe 與 HDR 設定邊界

- Recipe 只保存 `hdr.enabled`；所有 HDR 詳細參數位於系統級 `hdr_settings.json`。
- HDR 關閉時，每個 EL 點位的 Exposure、Gain、Frames 與 Frame interval 都是明確且必填的量測條件，不可使用隱含 fallback。
- HDR 開啟時，EL 表格相機欄位僅顯示狀態；實際值由 `設定 → HDR` 與 T0 Profile 決定。
- 量測快照必須保存當次有效的完整 Recipe、HDR 設定、T0 Profile、實際曝光計畫與輸出檔案清單。

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

啟動自動連線只選擇上次成功 serial、上次成功 VISA resource，或掃描結果中唯一受支援的 SMU；多台且無法判定時 fail closed，交由使用者手動選擇。受支援 driver 必須依序送出 `OUTPUT OFF`、以 `:OUTP?` 明確確認 False，再將 source voltage/current 歸零，才可發布 connected／READY_MANUAL；任何 driver bind／初始化失敗均關閉 resource 與 resource manager、清空所有 session 欄位並進入 connection ERROR。

`PolarityService` 預設為 `UNKNOWN`（factor `None`）。Manual setpoint 是 SMU 實體座標，直接送至儀器且不依賴 Polarity；Recipe setpoint 才是 Device 座標，必須明確確認 `+1` 或 `-1` 後轉換成 physical SMU command。`set_confirmed_factor()` 為 idempotent assignment 而非 toggle；polarity determination 尚未實作，其未來流程必須只產生 factor，不可預先套用未確認 factor。Manual panel 的 range 由同一份 `SMUSafetyLimits` 注入，不在 UI 維護第二份上限。

Emergency request 先設定 threading Event latch，再排入相同 single-worker queue 做 `safe_shutdown()`。Normal operation 會在 configure 前及真正送出 `OUTPUT ON` 前檢查 latch；最後一段 check／OUTPUT ON 與 Emergency latch transition 有明確同步邊界，因此 Emergency 之後尚未送出的 normal output 不會開啟。已在執行中的 blocking PyVISA call 不宣稱可被 preempt。Emergency shutdown 完整成功且 OUTPUT OFF 後才回到 IDLE 並清除 latch；failure 則保留 latch/錯誤並進入 FAULT。

Manual → Recipe 交接必須先完成 verified shutdown，釋放至 IDLE 後才允許 Recipe acquire。Recipe → Manual 交接先設 cancel latch 封鎖新 Recipe output、通知 worker cancel、關閉白光，再等待目前 I/O safe point 執行 verified shutdown；只有 `OUTPUT OFF` 明確確認後才回到可手動狀態。安全交接支援已完成，但完整 Recipe 硬體執行仍維持停用。

一般 disconnect 只有在 hardware query 明確回傳 OFF、ownership 為 IDLE 且 control 無 pending I/O 時才允許；True 或 `None` 均 fail-closed。`safe_shutdown()` 的固定順序為 `:OUTP OFF` → `:OUTP? == False` → source 歸零，並以 `output_confirmed_off`／`last_shutdown_ok` 區分完整成功與失敗；query 為 ON、UNKNOWN、exception 或任何 `safe_stop()` failure 都不得宣告安全，必須進入 FAULT。

Readback 由 `SMUMonitor` 的 Qt timer 觸發，但實際 query 在控制層的單一 worker 執行；I/O lock 同時涵蓋 Manual、Recipe、readback 與 shutdown。Recipe ownership 或 busy 時不排入 readback，避免 critical command 中插入 query。

V1.5.1 修正 Manual 實體座標、矛盾 readback 復歸、verified shutdown、雙向安全交接與單一 UI snapshot；完整 Recipe 硬體執行仍停用。未完成 Jsc／Voc determination、Dark I–V、Dark Frames、EL 點位與相機同步前，不得啟用主畫面「開始量測」。

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
- `python -m unittest discover -s tests -v`：HDR 數值、Profile、設定快照、Recipe schema、UI 結構與模組邊界。
- Windows 實機驗證：RisingCam 連線、Live View、曝光／Gain、一般拍攝、VISA 掃描與 B2900 安全連線。
- 涉及 SMU 輸出的版本必須另建硬體模擬、錯誤注入與緊急停止測試；race test 使用 Event／Barrier 控制 timing，不以 sleep 猜測 configure 與 OUTPUT ON 的時序，也不能只依賴 GUI 手動測試。
