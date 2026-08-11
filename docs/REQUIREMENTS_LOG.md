# EL 量測設備控制程式需求紀錄

文件版本：1.2
最後更新：2026-08-11（UTC+8）

## 1. 強制維護規則

本文件是後續使用者需求的正式追蹤紀錄。每次新增、修改、取消或延後功能時，開發者必須：

1. 在修改程式前新增或更新需求項目，記錄使用者原意、必要細節、驗收條件與影響模組。
2. 不確定之處標記為「待確認」，不可自行推測成已確認需求。
3. 實作完成後將狀態改為「已完成」，記錄版本與測試；未實作不得標示完成。
4. 若使用者改變決定，保留原紀錄並新增「取代／取消」說明，避免歷史需求消失。
5. 同步更新 `PROGRAM_ARCHITECTURE.md`（若架構有變）及 README 版本紀錄。

狀態定義：

- `已完成`：程式與測試已包含此需求。
- `已確認／待實作`：需求已明確，但目前版本尚未完成。
- `暫緩`：刻意不在目前階段實作，需保留原因。
- `待確認`：仍需使用者決定關鍵行為。
- `已取消／已取代`：不再適用，並指向新的需求 ID。

## 2. 架構與維護性

### RELAY-001－通用 USBRelay8 設定與白光群組

- 狀態：已完成（2026-08-10）
- 使用者要求：以通用 8-channel USB HID Relay Controller 支援 USBRelay8（VID `0x16C0`、PID `0x05DF`），將白光建模為 `white_light` Group（CH1 + CH2），而非在主畫面硬編碼 channel。
- 驗收：設定頁可編輯／保存 CH1～CH8 與 Group；啟用群組之間不得重複使用 channel；主畫面只使用 `group_on/off("white_light")`；ON 失敗 rollback，OFF 繼續嘗試全部 member；多個無序號相同設備不自動連線。
- 測試：`tests/test_relay.py` 涵蓋 Channel、Group、rollback、OFF 容錯、設定 round-trip 與裝置歧義。

### ARCH-001－功能模組化

- 狀態：已完成（V1.3.4）
- 使用者要求：將程式各項功能模組化，避免單一 Python 檔案過大，降低後續維護困難。
- 驗收條件：
  - 主視窗的 UI 建構、設備操作與 Recipe/HDR 協調具清楚邊界。
  - Recipe 對話框的頁面建構、EL 點位邏輯與資料管理分離。
  - HDR 數值處理與檔案輸出分離。
  - 原有公開入口及功能行為保持相容。
- 影響模組：`main_window*`、`recipe_dialog*`、`auto_hdr.py`、`hdr_output.py`。
- 驗證：重構前後 36 項既有測試通過；另增模組結構測試。

### ARCH-002－禁止為拆分而拆分

- 狀態：已完成並持續適用。
- 使用者要求：不可為了縮短檔案而造成檔案過度零碎。
- 驗收條件：
  - 以責任、生命週期、I/O 邊界與可測試性決定是否拆檔，不以固定行數機械判斷。
  - `recipe_store.py` 保留 schema、遷移、驗證及時間估算的完整性。
  - `auto_hdr.py` 保留曝光規劃、過曝判定與合成的完整數值流程。
  - 不建立只有單一小函式、無獨立責任的模組。

### DOC-001－程式架構文件

- 狀態：已完成（V1.3.4）
- 使用者要求：建立記錄程式架構的 Markdown 檔案。
- 驗收條件：`docs/PROGRAM_ARCHITECTURE.md` 必須包含模組責任、依賴方向、安全邊界、資料流、擴充準則及測試策略。

### DOC-002－後續需求必須詳細記錄

- 狀態：已完成並持續適用。
- 使用者要求：後續所有要求都詳細記錄在檔案中。
- 驗收條件：每項要求必須有 ID、狀態、使用者原意、驗收條件、影響範圍與版本／驗證結果；修改或取消時保留歷史。

## 3. Recipe 與量測流程

### FLOW-001－四階段 EL Recipe

- 狀態：已完成介面與驗證；執行層暫緩。
- 流程：
  1. 白光下量測 Jsc／Voc 並確認極性。
  2. 關燈、等待暗態穩定、執行 Dark I–V。
  3. SMU 回零且 OUTPUT OFF 後，拍攝所有唯一相機條件的 Dark Frames。
  4. 依電流／電流密度或電壓點位拍攝 EL。
- 執行層暫緩原因：尚未完成 SMU 安全狀態機、錯誤回零與相機同步。

### FLOW-002－Start／Stop 必須獨立

- 狀態：已完成介面。
- 要求：開始量測與停止按鈕必須位於獨立操作列，不可放在 Recipe 選擇區內。
- 安全限制：在執行層完成以前，兩者維持禁用或安全提示。

### RECIPE-001－Recipe 相機策略選單移除

- 狀態：已完成（V1.3.3）。
- 要求：移除未實作且容易誤解的 Quantitative／Piecewise／Inspection 相機策略；新版 JSON 不再保存 `camera.strategy` 與 `use_camera_override`。
- 相容性：舊 Recipe 可以載入，重新儲存時移除廢棄欄位。

### RECIPE-002－非 HDR 逐點相機條件

- 狀態：已完成（V1.3.3）。
- 要求：HDR 關閉時，每個 EL 點位的 Exposure、Gain、Frames、Frame interval 都必須明確填寫；相機頁數值只供新增、產生及批次填入，不可作為隱含 fallback。

### RECIPE-003－HDR 開關整合到 EL 點位頁

- 狀態：已完成（V1.3.2）。
- 要求：刪除獨立 HDR Recipe 頁；`啟用 HDR` 位於 `5 EL 點位` 頁。
- 行為：啟用後相機欄位反灰並顯示「啟用 HDR」；關閉後恢復先前逐點值。

### RECIPE-004－完整量測快照

- 狀態：已完成資料契約；待執行層實際呼叫。
- 必須保存：完整 Recipe、HDR 系統設定及雜湊、T0 Profile、實際曝光計畫、每段飽和判定、提前終止結果、相機／SMU 條件與輸出檔案清單。

## 4. HDR

### HDR-001－詳細設定集中於「設定 → HDR」

- 狀態：已完成（V1.3.1）。
- 要求：Recipe 僅保存是否啟用 HDR；曝光策略、Gain、frames、門檻、ROI、Dark、輸出與 Aging 規則集中於系統設定。

### HDR-002－T0 與 Aging／重複量測

- 狀態：已完成介面、Profile 與相容性檢查；待量測執行層。
- T0：執行全域預掃描、固定 Gain、決定曝光段並建立樣品專屬 Profile。
- Aging：必須匯入相容 T0 Profile，不重新自動選曝光；核對 Sample ID、相機、Recipe、掃描條件、pixel format 與算法版本。
- 每次 Aging 仍需重新拍攝相同曝光條件的 Dark frames。

### HDR-003－嚴重過曝提前終止

- 狀態：已完成數值與輸出模組。
- 要求：曝光由短至長；每段先拍第一張判斷。若有效 ROI 飽和比例達門檻，保存該判斷幀、排除該段合成、跳過該段剩餘 frames 與所有更長曝光。
- 稽核：manifest 與快照記錄 Planned／Captured／Valid／Excluded／Skipped 及原因。

### HDR-004－HDR 強制輸出

- 狀態：已完成輸出模組；待執行層接線。
- 強制保存：每曝光全部原始 EL TIFF、全部原始 Dark TIFF、Master Dark、`HDR_linear_float32.tiff`、JSON／CSV manifest 與 T0 Profile。
- 選配：8-bit preview PNG，只供顯示，不可用於定量分析。

## 5. 資料輸出與 UI

### OUTPUT-001－全解析度像素 CSV 為選配

- 狀態：已完成（V1.2.2）。
- 要求：Dark I–V 與 EL scan summary CSV 維持必要；全解析度 Raw／Dark-corrected／DN/s CSV 預設關閉。
- UI：勾選時先顯示可能達數百 MB／點的容量警告，使用者可取消。
- 可回溯性：關閉時仍可由保留像素值的 TIFF、Master Dark 與 metadata 日後產生。

### UI-001－工具列一致性

- 狀態：已完成（V1.2.3）。
- 要求：主要工具按鈕固定 132 × 36 px、圖示 20 × 20 px，順序為設備 → Recipe → 拍攝 → 檢視。

### UI-002－左側手動曝光控制可操作

- 狀態：已完成（V1.3.5）。
- 提出日期：2026-08-06（UTC+8）。
- 使用者原意：修正左側曝光控制無法改變參數的問題。
- 詳細行為：
  - 相機已連線且「持續自動曝光」關閉時，Exposure、Gain 與「套用手動設定」必須啟用。
  - 「持續自動曝光」開啟時，手動欄位反灰，只開放曝光目標。
  - 相機未連線時，曝光控制全部停用。
  - 介面曝光單位為 ms；送入 RisingCam SDK 時轉為 μs，套用後讀回實際值並更新畫面。
- 驗收條件：共用相機控制狀態函式不得在連線後無條件停用手動欄位；自動／手動模式切換使用單一狀態計算來源。
- 影響模組：`gui/main_window_devices.py`。
- 相容性／資料遷移：不變更 Recipe schema、相機 metadata 或既有設定檔。
- 安全風險：只影響相機曝光與 Gain；不啟用任何 SMU source、compliance 或 OUTPUT 命令。
- 測試與驗證：新增 `tests/test_manual_exposure_controls.py`；完整測試套件通過。
- 完成版本：V1.3.5。

### UI-003－曝光狀態列更新不得拋出方法綁定錯誤

- 狀態：已完成（V1.3.6）。
- 提出日期：2026-08-06（UTC+8）。
- 使用者原意：相機連線與曝光值更新時，不應持續出現 `_format_exposure()` 參數數量錯誤。
- 詳細行為：相機開啟、SDK 曝光訊號、手動曝光套用與自動曝光更新後，狀態列必須依數值顯示 μs、ms 或 s，且不得中斷其他 UI 更新。
- 驗收條件：`_format_exposure()` 必須以 `@staticmethod` 宣告，或改為具 `self` 的 instance method；所有 mixin 方法都必須具備有效的 descriptor 綁定方式。
- 影響模組：`gui/main_window_devices.py`。
- 相容性／資料遷移：不變更 Recipe schema、相機 SDK 參數、影像 metadata 或既有設定檔。
- 安全風險：僅修正曝光文字格式化；不新增 SMU 或相機控制命令。
- 測試與驗證：擴充 `tests/test_manual_exposure_controls.py`，加入 formatter decorator 與 mixin 方法綁定檢查；完整測試套件通過。
- 完成版本：V1.3.6。

## 6. 相機溫度監控

### TEMP-001－確認 SDK 溫度讀取能力

- 狀態：已確認／待實作。
- 要求：使用目前 RisingCam SDK 可用的溫度查詢能力，確認支援機型、單位、無感測器時的回傳與讀取頻率限制。
- 不可假設：若特定相機／SDK 不支援，UI 必須顯示不可用，不可寫入虛構數值。

### TEMP-002－相機溫度 Trend Chart

- 狀態：已確認／待實作。
- 要求：提供可手動開啟的相機溫度趨勢圖；開始擷取影像後自動開啟並開始採樣。
- 建議行為：時間為 X 軸、攝氏溫度為 Y 軸；顯示目前值、最小值、最大值與採樣狀態；相機中斷時保留已取得曲線並停止 polling。
- 待確認：預設採樣間隔、趨勢圖是否可停駐／獨立視窗、保留的最大顯示時間。

### TEMP-003－影像 metadata 溫度

- 狀態：已確認／待實作。
- 要求：每張拍攝影像的 metadata 記錄與該影像最接近的相機溫度、採樣時間、與影像拍攝時間差及是否有效。
- 驗收：沒有有效讀值時寫入 `null` 與原因，不可沿用過舊數值而不標示。

### TEMP-004－程式 log／時間序列紀錄

- 狀態：已確認／待實作。
- 要求：程式 log 資料夾保存隨時間變化的溫度資料，供後續回溯曝光與相機熱狀態。
- 最低欄位：timestamp、elapsed time、camera model／serial、temperature °C、read status、measurement／capture context。
- 檔案應採可由 Origin／Excel 讀取的 CSV，並在一般 log 記錄啟動、停止與讀取錯誤。

### TEMP-005－溫度功能獨立模組

- 狀態：已確認／待實作。
- 要求：溫度 polling、資料緩衝、趨勢訊號與 log 寫入由獨立 Python 模組管理，不回填成 `main_window.py` 的大型方法集合。
- 架構限制：保持單一完整溫度模組，除非未來圖表或資料庫具獨立生命週期，否則不再細拆。

## 7. 安全與暫緩項目

### SMU-001－手動 CV／CC 與集中式 SMU control

- 狀態：已完成（V1.4.0；fake SMU 驗證，實機輸出待驗證）。
- 提出日期：2026-08-11（UTC+8）。
- 使用者原意：左側新增固定 CV／CC 手動輸出，共用 Recipe polarity factor、driver 與 connection，並建立底層 ownership/interlock、安全限制、非阻塞 readback、Emergency OFF 及完整 cleanup。
- 驗收條件：IDLE/MANUAL/RECIPE/EMERGENCY；Manual/Recipe 不可並行；physical=requested×factor；500 ms polling 不阻塞 UI 且不與 command race；Manual OFF、Recipe return/stop/exception、Emergency 與 app close 均歸零及 OUTPUT OFF。
- 影響模組：`smu_control.py`、`smu_monitor.py`、`smu_manual_panel.py`、`smu_base.py`、`keysight_b2900.py`、`smu_manager.py`、`main_window*`、文件與測試。
- 相容性／資料遷移：不改 Recipe schema、Camera/HDR、影像與量測輸出格式；完整 Recipe execution 仍停用。
- 安全風險：Keysight SCPI 手動輸出尚未以實體 SMU 驗證；首次硬體使用必須在低限制、無敏感 DUT 條件下確認命令與前面板狀態。
- 測試與驗證：fake SMU 涵蓋 CV/CC、± factor、idempotence、interlock、shutdown、Emergency、錯誤注入、safety 與 I/O serialization；完整 regression suite 通過。
- 完成版本：V1.4.0。

### SMU-002－Manual SMU safety／state consistency hotfix

- 狀態：已完成（V1.4.1；fake SMU 驗證，Keysight B2900 實機待驗證）。
- 提出日期：2026-08-11（UTC+8）。
- 使用者原意：只修正 V1.4.0 code review 發現的 Manual pending race、Emergency queue race、未確認 polarity、disconnect 與 shutdown safety consistency，不重寫既有架構或啟用 Recipe execution。
- 詳細行為：busy check／MANUAL acquire／enqueue 為單一 lock transition；Emergency latch 在 OUTPUT ON 前重查；polarity 預設 UNKNOWN；UI 使用 manager operation state 與 authoritative limits；disconnect 對 unknown output fail-closed；shutdown failure 進入 FAULT 且不宣告 confirmed OFF。
- 驗收條件：double request 不改變第一個 ownership；configure 與 OUTPUT ON 間的 Emergency 不得送出 ON；UNKNOWN polarity 的 Manual／Recipe 不得送出 configure/output；只有明確 OFF＋IDLE＋not busy 可一般 disconnect；`safe_stop()` failure 保留未確認安全狀態。
- 影響模組：`smu_control.py`、`smu_manager.py`、`smu_manual_panel.py`、`main_window_ui.py`、SMU tests、README 與架構／需求文件。
- 相容性／資料遷移：不改 Recipe schema、Camera/HDR/Relay 邏輯或輸出格式；Manual 與 Recipe 繼續共用既有 `SMUControlManager`、PolarityService、SafetyService 與 driver。
- 安全風險：threading Event 可阻止 latch 後尚未送出的 OUTPUT ON，但不可 preempt 已在執行的 blocking PyVISA call；Keysight B2900 的 SCPI response、實體 output 與故障恢復仍需實機確認。
- 測試與驗證：FakeSMU 以 Event 控制 configure timing，涵蓋 double request、Emergency race、UNKNOWN／confirmed polarity、idempotent factor、mode reset、limits injection、unknown disconnect、shutdown failure 與原有 serialization。
- 完成版本：V1.4.1。
- 取代或關聯需求：補強 SMU-001；SAFE-001 的 Recipe execution 暫緩狀態不變。

### SAFE-001－SMU 輸出保持停用

- 狀態：部分取代；手動輸出由 SMU-001 開放，Recipe 實際量測仍暫緩。
- 要求：完整 Recipe 在完成 polarity determination、四階段硬體狀態機、相機同步與資料落盤驗證以前不可啟用。

### SCOPE-001－Door 功能

- 狀態：暫緩。
- 原因：暗箱門硬體尚未 ready；現階段不加入 Door interlock 或感測器流程。

### SCOPE-002－VDE c-Si 缺陷分類

- 狀態：暫緩。
- 原因：主要針對 c-Si cell／module，與目前鈣鈦礦 EL 軟體優先目標不一致。

## 8. 後續需求新增模板

複製下列區塊並使用不重複 ID：

```markdown
### AREA-NNN－需求名稱

- 狀態：待確認／已確認／已完成／暫緩／已取消
- 提出日期：YYYY-MM-DD（UTC+8）
- 使用者原意：
- 詳細行為：
- 驗收條件：
- 影響模組：
- 相容性／資料遷移：
- 安全風險：
- 測試與驗證：
- 完成版本：
- 取代或關聯需求：
```

## 9. 版本變更摘要

### V1.4.1－2026-08-11

- 修正 Manual pending ownership race，新增 authoritative operation state 與 UI immediate lock。
- 新增 Emergency latch、UNKNOWN polarity interlock、fail-closed disconnect 與 shutdown confirmation／FAULT。
- Manual UI 改用 authoritative safety limits，CV／CC 切換時 setpoint 歸零；新增 deterministic fake SMU regression tests。
- 完整 Recipe execution、Camera/HDR 與 Relay 行為維持不變。

### V1.4.0－2026-08-11

- 新增 Manual CV／CC panel、central ownership/interlock、共用 polarity、安全限制、序列化 readback、Emergency 與 lifecycle cleanup。
- 新增 fake SMU control regression tests；完整 Recipe 執行維持停用。

### V1.3.6－2026-08-06

- 修正 `_format_exposure()` 在類別內缺少 `@staticmethod`，導致 instance 呼叫時自動多傳入 `self` 的 `TypeError`。
- 新增格式化方法與 mixin descriptor 綁定回歸測試。
- PyVISA 的 `psutil`／`zeroconf` 警告確認與本次錯誤無關，未加入非必要依賴。

### V1.3.5－2026-08-06

- 修正相機連線共用函式覆寫手動曝光控制狀態，導致 Exposure、Gain 與套用按鈕反灰的問題。
- 統一由自動／手動曝光狀態函式管理相關 widget，並新增回歸測試。

### V1.3.4－2026-08-06

- 完成職責導向模組化；未改變量測安全邊界。
- 建立架構文件與本需求紀錄。
- 將相機溫度趨勢、metadata、log 與獨立模組列為已確認待實作需求。
