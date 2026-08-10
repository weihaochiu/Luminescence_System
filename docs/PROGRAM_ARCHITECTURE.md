# EL 量測設備控制程式架構

文件版本：1.2  
對應程式版本：V1.3.6  
最後更新：2026-08-06（UTC+8）

## 1. 文件目的

本文件是程式結構的主要依據，說明模組責任、依賴方向、資料流、安全邊界與新功能應放置的位置。修改程式架構時必須同步更新本文件；新增或變更使用者需求時必須同步更新 `REQUIREMENTS_LOG.md`。

本專案採「依職責拆分、避免過度零碎」原則。檔案大小是需要檢視的訊號，不是機械式拆分門檻。只有當功能具備獨立責任、生命週期、I/O 邊界或可單獨測試的介面時，才建立新模組。

## 2. 啟動與主要資料流

1. `main.py` 呼叫 `gui.app.main()`。
2. `app.py` 建立 Qt Application 與 `MainWindow`。
3. `MainWindow` 建立相機控制器、SMU 管理器、Recipe Store 與 HDR Settings Store。
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
| `main_window_devices.py` | 相機／SMU 連線、Live View、手動／自動曝光拍攝、一般影像存檔 | Recipe schema、HDR 數值合成 |
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

## 6. 安全邊界

V1.3.6 仍禁止下列操作：

- 寫入 SMU source current／voltage。
- 寫入 compliance。
- 執行 SMU OUTPUT ON／OFF。
- 自動執行 Jsc／Voc、Dark I–V、Dark Frames 與 EL 點位。
- 宣稱相機與 SMU 已完成同步。

在完成可中止的背景狀態機、錯誤回零、OUTPUT OFF 保證、compliance 處理與資料落盤驗證以前，不得啟用「開始量測」。

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
- 涉及 SMU 輸出的版本必須另建硬體模擬、錯誤注入與緊急停止測試，不能只依賴 GUI 手動測試。
