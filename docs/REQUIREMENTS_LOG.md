# EL 量測設備控制程式需求紀錄

文件版本：1.6
最後更新：2026-08-25（UTC+8）

## Current requirement — I18N-ERROR-001

- 狀態：已完成（2026-08-25）。
- 支援語言：`zh-TW`、`en-US`；語言設定獨立持久化並支援 runtime signal/retranslation。
- canonical compatibility：Recipe／Settings／Manual SMU 不保存翻譯文字；legacy 中文值在讀取時映射，原始檔不做破壞式覆寫。
- error architecture：中央 Registry／Reporter／Context、統一 Error Dialog、可搜尋與篩選 Error Center、500 筆 bounded Session History、diagnostics copy 與 exact-code deep link。
- safety：沿用既有 SMU OUTPUT OFF、Relay routing、Emergency、close safety 與 measurement abort 流程；Critical 無 Ignore／Continue。
- 文件與測試：`USER_MESSAGE_INVENTORY.md`、由 registry 生成的 `ERROR_CODE_REFERENCE.md`、migration audit，以及 i18n/error GUI/canonical/safety automated regression。

### I18N-ERROR-002－第二輪雙語與錯誤復歸稽核

- 狀態：已完成（2026-08-25）。
- 使用者原意：依實際程式碼逐項確認 Error action 真實可執行、SMU reconnect 不破壞 OUTPUT safety latch、MainWindow runtime retranslation 完整、inventory 能發現間接動態文字、diagnostics 不外洩敏感值，並修正 Recipe legacy 預設回歸。
- 驗收條件：無 handler 不顯示 action；無 generic Retry；measurement 中不 reconnect；SMU 僅 reconnect 明確選定 resource 並重新執行 verified OUTPUT OFF；MainWindow 代表性 UI 雙向即時切換且 canonical data/signal 不變；scanner 涵蓋 IfExp、nested signals 與 indirect presentation；registry action 白名單；敏感 context/exception/traceback 在 log/history/copy 前遮蔽；缺少 compliance action 維持 confirm。
- 影響模組：`core/error_*`、`gui/main_window_*`、`gui/dialogs/error_dialog.py`、Device／SMU／state presentation、locale/registry resources、Recipe migration、inventory generator、tests 與 i18n/error docs。
- 相容性／資料遷移：不改 Recipe schema；舊中文值仍只在讀取時映射，新資料持續寫 canonical value。語言設定不進入 Recipe、measurement metadata 或 hardware workflow。
- 安全風險：只重接既有 recovery boundary，不更改 measurement sequence、SCPI protocol、Relay protocol 或 Emergency precedence。任何未知 OUTPUT 狀態均 fail closed。
- 測試與驗證：新增 Error action/mapping、MainWindow runtime i18n、inventory scanner、diagnostics redaction 與 Recipe default regressions；完整命令與結果記錄於 `I18N_ERROR_SYSTEM_MIGRATION.md` 及本次 Git 報告。
- 取代或關聯需求：補強 `I18N-ERROR-001`，不取代既有 SMU／Relay／Emergency／close safety requirements。

### I18N-ERROR-003－SMU safety fault 實體 identity 綁定

- 狀態：已完成（2026-08-25）。
- P0 原因：舊版只保存 OUTPUT UNKNOWN boolean；A disconnect 後，任何新 driver 都可能繼承 latch，導致 B 的 OUTPUT OFF readback 錯誤清除 A 的 fault。
- 驗收：第一次 fault 保存 immutable VISA/serial/manufacturer/model/IDN；serial 為強 identity；同 resource／不同 serial 拒絕，同 serial/model／新 resource 可受控復原；identity 跨 unbind 保留且不可覆寫；所有 normal/auto/reconnect/bind/recovery path fail closed。
- 復原成功條件：相同實體 SMU、authoritative OUTPUT OFF、Relay routing OFF、White Light OFF 全部驗證成功後，才清除 identity、UNKNOWN/fault latch 並回到 IDLE/READY。
- Error boundary：SMU-203/205 context 優先使用 fault target；OUTPUT OFF unconfirmed、unexpected output、compliance、generic failure 改由 canonical `SMUErrorKind` 決定 code，不解析翻譯文字。
- Diagnostics/i18n：補強 JSON credential、access/refresh token、Authorization schemes、URL query redaction；AE metering list-joined tooltip 完成雙語並納入 scanner regression。
- Persistence assessment：unresolved fault 尚不跨 process restart；現行沒有 atomic hardware-fault journal，本次保留為明確 remaining risk，不以非原子 QSettings 草率擴張。

註：版本摘要中的「Recipe 停用／暫緩」只描述當時版本，現行狀態一律以 FLOW-ELM-001 與 V1.8.2 為準。

## Current requirement — CAL-RULER-001

- 狀態：軟體實作完成（V1.9.0）；實際相機＋鐵尺大量辨識 acceptance 待執行。
- 使用者原意：先以 standalone engineering tester 驗證任意 XY／0–360° 鐵尺 detection、旋正／mild perspective rectification、1 mm/5 mm/10 mm tick、尺上單／雙位數 OCR、geometry/OCR cross-validation、robust long-span pixels/mm、µm/pixel、scale bar preview、debug evidence、batch regression 與 random-placement repeatability，再決定是否整合正式 Recipe。
- 架構：新增無 Qt／硬體依賴的 `core/calibration/` 與只向下呼叫 service 的 `tools/ruler_scale_calibration_tester/`；Camera mode 重用既有 `CameraController`，不複製 SDK wrapper。
- Coordinate gate：rectified image 只供 detection/OCR；accepted references inverse-transform 回 original frame，最後 `pixels/mm` fitting 對應 original stored image plane。ruler marking surface Z 必須等於未來 sample emission surface Z。
- OCR：可替換 interface；第一版採 optional pytesseract＋使用者明確安裝的 Windows Tesseract executable；unavailable 時顯示原因、不自動下載、不回傳假值。OCR outlier 可由 geometry 拒絕／提出 correction，但 raw 與 correction 均保存。
- Quality：min usable intervals 10、min span 10 mm、positive finite scale 與 fit consistency 為必要 gate；quality_score 是 documented engineering score，不宣稱 probability。
- Evidence：Original/rectified/threshold/edges/ticks/OCR/final overlay 與 result JSON；`local/generated`、dataset、OCR cache 不進 Git。Batch 回報 detection/OCR/calibration counts、mean/SD/CV/failure reasons；GUI 累積 repeatability N/mean/SD/CV/min/max/max deviation，不先宣稱門檻。
- 明確排除：不修改 Recipe、polarity、measurement runner、SMU output、relay safety、正式 JPG footer 或 TIFF；不自動控制白光。
- 驗證：21 項 unit/synthetic tests 涵蓋 scale math、scale bar、perfect/missing/false/noisy tick、OCR sequence/outlier、0/30/90/135/180/270°、mild perspective、no ruler/no ticks/insufficient ticks/OCR unavailable/debug package/batch；完整 repository regression 511/511 通過。實際辨識率不得由 synthetic tests 推論。

### CAL-RULER-002－Physical pitch、evidence 與 repeatability 強化

- 狀態：已完成（V1.9.1）；實際相機＋鐵尺 acceptance 仍待執行。
- Correctness gate：`periodic_pitch_px` 不再直接當作 px/mm；評估 1/2/5/10 mm hypotheses，只有完整 tick hierarchy 或已 association 的相鄰公分 OCR 能產生 `tick_hierarchy_verified`／`ocr_verified` PASS。ambiguous physical pitch 一律 FAIL，不受 quality score 影響。
- Evidence：`CalibrationService` 保存 exact raw ndarray copy；debug package 以 tifffile 寫出 exact `raw_input.tiff`，另存 preview/intermediate overlays 與包含 dtype/min/max/source/pitch hypotheses 的 JSON，不把 pixels 塞進 JSON。
- Source/UI：Live View 與 Captured 分離；camera identity 綁 device、scientific frame sequence、capture timestamp，file identity 綁 absolute path、mtime、size。結果顯示實際 analyzed frame/source。
- Repeatability：Analyze 不自動新增 run；只有 physically verified success 可人工加入，同 source identity 防重，並輸出逐 run 與 N/mean/SD/CV/min/max/max deviation 的 UTF-8 CSV。
- Dependency/launcher：OpenCV 因 reusable core 直接使用維持 mandatory；pytesseract 改放 tester `requirements-ocr.txt`，Tesseract executable 由使用者另行安裝且有雙語診斷。根目錄 BAT 使用既有 `.venv`，不自動安裝。

## Current superseding requirement — HDR removal

- 狀態：已完成（2026-08-14）。
- 現行產品不包含 HDR UI、設定、Recipe schema、runtime、snapshot、preflight、output、Profile 或專用模組。
- 舊 Recipe 的 legacy `hdr` key 只在載入時忽略，重新儲存後移除。
- 本文件後續所有 HDR 條目只保留為歷史需求紀錄，不代表現行功能或相容性承諾。

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

- 狀態：已由 FLOW-ELM-001 的 EL Matrix 執行模式部分取代；Legacy 設定保留相容讀取。
- 流程：
  1. 白光下量測 Jsc／Voc 並確認極性。
  2. 關燈、等待暗態穩定、執行 Dark I–V。
  3. SMU 回零且 OUTPUT OFF 後，拍攝所有唯一相機條件的 Dark Frames。
  4. 依電流／電流密度或電壓點位拍攝 EL。
- 執行狀態：Legacy `el_sweep` 只作相容讀取；正式硬體執行由 FLOW-ELM-001 的 snapshot-driven EL Matrix 流程取代。

### FLOW-ELM-001－多 Channel EL Matrix 自動量測

- 狀態：已完成並補強（V1.8.1）。
- 提出日期：2026-08-14（UTC+8）。
- 使用者原意：將已驗證的 Camera Gain／Exposure Matrix 正式整合至 Recipe，依序量測固定 CH1～CH4 中已啟用者。
- 詳細行為：先對全部啟用 Channel 逐一 route 並完成 polarity；verified SMU／白光／routing OFF 後拍一次 Shared Dark。再逐 Channel break-before-make route、重套該 Channel factor、暗態穩定、Dark I–V、verified OUTPUT OFF，最後執行 J → Gain → Exposure → Repeat。同一 J 內 SMU OUTPUT 保持 ON，stabilization 只執行一次。
- 驗收條件：Logical Channel 不保存 physical relay；Area 逐 Channel 計算 Source Current；Channel transition 必須先 verified OUTPUT OFF 再使用既有專用 routing API；任何 stop/error 走共用安全關閉。
- 影響模組：`recipe_store.py`、`recipe_dialog*`、`el_matrix_plan.py`、`el_matrix_runner.py`、`el_matrix_hardware.py`、`smu_control.py`。
- 相容性／資料遷移：schema v8；已知舊版明確 migration，缺少重要欄位維持 draft 並列出人工確認項目，future schema 及未知新版欄位拒絕匯入。
- 測試與驗證：`tests/test_el_matrix.py` 與完整 unittest suite。

### OUTPUT-ELM-001－RAW TIFF 與下方 Footer JPG

- 狀態：已完成並補強（V1.8.1）。
- 詳細行為：同一次正式 capture 的 RAW frame 保存 TIFF、更新既有 Live View，並從 copy 建立原圖下方中性灰底／白字三行 Footer JPG；Sample ID 僅在 filename 使用 sanitized 版本。
- 驗收條件：TIFF 尺寸與 pixel bytes 不變；Footer 不覆蓋相機有效畫面；Dark 不顯示 J=0／I／V；正式 metadata 與 manifest 持續保存高精度數值。
- 影響模組：`camera_capture_bridge.py`、`measurement_output.py`、`el_matrix_runner.py`。

### UI-ELM-001－Modeless Progress、Runtime ETA 與 Live View

- 狀態：已完成並補強（V1.8.1）。
- 詳細行為：Summary 在任何 SMU/routing 操作前確認；runtime window modeless，由 worker progress single source of truth 更新 overall monotonic progress、剩餘張數、時間與 finish time。關閉 X 只隱藏視窗，不停止 worker。
- 驗收條件：正式 frame 仍由既有 CameraController pull-mode signal 更新主畫面；bridge 不啟動第二 stream、不插入 preview exposure；Progress Stop 呼叫既有 safe stop。

### FLOW-002－Start／Stop 必須獨立

- 狀態：已完成介面。
- 要求：開始量測與停止按鈕必須位於獨立操作列，不可放在 Recipe 選擇區內。
- 安全限制：Start 只有在 Recipe、設備與輸出 preflight 全部通過時可用；worker 存在期間只保留 Stop 與 Emergency 等安全控制。

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

### CAMERA-TEMP-001－Camera Temperature Monitoring V1

- 狀態：已完成（V1.7.0）。
- 提出日期：2026-08-13（UTC+8）。
- 使用者原意：可靠讀取 RisingCam 感測器溫度，提供 GUI 即時顯示、單純趨勢圖、完整 dedicated CSV，並把 capture 當下最近有效溫度 snapshot 寫入所有正式影像 metadata；telemetry failure 不得影響相機、EL 或 HDR。
- SDK 契約：只使用 repository bundled `gui/sdk/nncam.py` 的 `Nncam.get_Temperature()` 與 `NNCAM_FLAG_GETTEMPERATURE`；原始 signed integer 單位為 0.1 °C，controller 除以 10。
- 生命週期：camera connect 後固定 1 秒 polling；disconnect/shutdown 必須先 stop timer、flush/close CSV、清除 latest sample，才可關閉 SDK handle；disconnect 後不推算 cooling curve。
- GUI／Chart：繁體中文顯示 `xx.x °C` 或 N/A；QtCharts 顯示時間、溫度、目前值與 session min/max，rolling buffer 30 分鐘；關閉 chart 不停止 monitor/log。
- Log：AppData `logs/camera_temperature_YYYYMMDD_HHMMSS.csv`，欄位 `timestamp,temperature_c`，ISO 8601 timestamp 含 milliseconds/timezone；disk 保存全 session 有效資料。
- Metadata：使用 `CameraTemperature_C`、`CameraTemperatureTimestamp`；只消費 monitor latest snapshot，不同步 query SDK；sample age 超過 3 秒視為 stale，unavailable/stale 時省略欄位，不偽造 0 °C 或 `None`。
- 輸出：一般 TIFF／PNG／JPEG／BMP 使用既有同名 JSON sidecar；HDR raw EL、Dark、Master Dark、linear float32 TIFF 與 preview PNG 各自使用 sidecar，pixel data/bit depth 不變。
- Non-fatal：temporary error/invalid/unavailable 跳過當次 sample 並繼續 polling；unsupported 相機顯示 N/A、停止重複 query/error spam，其他相機功能保持正常。
- 明確排除：Camera state machine、event marker、TEC/PID/fan、warning/alarm、over-temperature shutdown、自動停止量測與可調 sampling interval。
- 影響模組：`camera_controller.py`、`camera_temperature_monitor.py`、`camera_temperature_chart.py`、`main_window*`、`image_io.py`、`hdr_output.py`。
- 驗證：`tests/test_camera_temperature.py` 25 項專門測試與完整 suite 239 項全部通過；`python -m compileall .`、`git diff --check` 通過。

### UI-CAM-DNROI-001－Live View Scientific DN ROI／SDK AE Metering ROI

- 狀態：已完成（2026-08-19 AE metering scope correction）。
- 提出日期：2026-08-19（UTC+8）。
- 使用者原意：EL Live View 真正關注的通常是中央元件區域；whole-frame Mean DN 會包含大量黑色背景，因此使用者需要直接在 Live View 框選關注區域，並即時查看該區域的 Scientific Effective DN 平均值。
- 詳細行為：只實作 `Live View → User ROI → Scientific Effective DN Mean → 即時顯示`。ROI 使用原始 image-pixel coordinates；相同解析度的新 frame 保留 ROI，解析度變更、影像清除或相機中斷時清除 ROI。數值只取自既有 `scientific_frame_ready` 的 `uint16 H×W` scientific frame，並沿用既有 Effective DN alignment interpretation。
- 驗收條件：一般模式保留 ScrollHandDrag／wheel zoom／Fit to Window／Actual Size；選取模式完成後自動恢復平移。ROI overlay 只存在於 scene，不修改 QImage、scientific ndarray 或輸出像素。Alignment unknown 時顯示無法判定；左側 whole-frame MeanEffectiveDN 語意保持不變。
- ROI coordinate contract：`(x, y, width, height)` 一律是原始 image-pixel integer coordinates，採 `scientific[y:y + height, x:x + width]`；負值、零尺寸與超界 ROI 明確拒絕。Fit／100%／zoom／pan 只改變 view transform，不改變 ROI 座標。
- Scientific DN source：唯一來源是既有 `CameraController.scientific_frame_ready` 的 `uint16 H×W` scientific ndarray；MainWindow 只保留 latest frame reference，不 copy full frame，不使用 QImage／QPixmap／preview RGB／`equivalent_brightness_8bit()`。
- Auto Exposure 修正需求：同一個 user DN ROI 必須同時作為 Scientific Effective DN analysis ROI 與 RisingCam SDK Auto Exposure metering ROI；GUI 只能透過 `CameraController` public API 呼叫 `put_AEAuxRect()` 並以 `get_AEAuxRect()` 完整 readback 驗證。Clear、camera open 與 resolution change 必須明確恢復 `(0, 0, current_width, current_height)`。
- SDK percent 語意：`NNCAM_OPTION_AUTOEXPOSURE_PERCENT=100` 必須保持不變；依 bundled SDK 定義，其語意為 full active AE ROI average。只有 active AE ROI 等於完整影像時，才等同 full-frame average。
- Calibration／convergence 邊界：whole-frame `_latest_mean_effective_dn`、`_latest_effective_dn_fraction` 保持 diagnostic 語意；代表 SDK AE metering feedback 的判斷必須另用與 verified active AE ROI 一致的 Metering Mean Effective DN。Calibration profile 必須以 ROI geometry 隔離，禁止 full-image profile 無察覺地套用 custom ROI。
- 實際修改檔案：本階段修改 `docs/REQUIREMENTS_LOG.md`、`docs/PROGRAM_ARCHITECTURE.md`、`gui/camera_ae_calibration.py`、`gui/camera_controller.py`、`gui/main_window_ui.py`、`gui/main_window_devices.py`、`tests/test_camera_ae_roi.py`、`tests/test_camera_ae_calibration.py`、`tests/test_camera_exposure.py`、`tests/test_camera_scientific.py`、`tests/test_live_view_dn_roi.py`；沿用前一階段未改寫的 `gui/scientific_dn.py::mean_effective_dn_roi()` 與 `gui/widgets.py::ImageView` image-pixel ROI／overlay。
- 相容性／資料遷移：不保存 ROI；不變更 Recipe、measurement、metadata、影像輸出或 capture dimensions。
- 安全風險：只設定 AE metering rectangle，不得使用 acquisition/crop ROI，不得改變 full-resolution capture、輸出 pixels、Recipe、metadata 或正式量測流程。SDK write/readback failure 必須 fail closed 顯示驗證失敗，不可 silent fallback。
- 測試與驗證：新增 `tests/test_camera_ae_roi.py` 14 項 controller／SDK AE ROI 專門測試，並擴充 `tests/test_live_view_dn_roi.py`、`tests/test_camera_ae_calibration.py`、`tests/test_camera_exposure.py`、`tests/test_camera_scientific.py`。Related suite 111 項通過；`python -m unittest discover -s tests -v` 共 352 項通過（0 failed、0 errors、0 skipped）；`python -m compileall .` 與 `git diff --check` 通過。RisingCam hardware validation：PENDING，未宣稱實機完成。
- 完成版本：`Wire DN ROI to RisingCam AE metering`。
- 取代或關聯需求：與 whole-frame Effective DN／SDK AE 分離，未取代既有曝光需求。

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

### UI-004－相機曝光模式、硬體範圍與即時亮度

- 狀態：已完成（V1.6.0；待 RisingCam 實機驗收）。
- 提出日期：2026-08-12（UTC+8）。
- 使用者原意：曝光控制改為持續自動／手動下拉模式，清楚分離硬體 range 與 AE allowed range，並顯示相機實際 Exposure/Gain 與目前影像亮度。
- 詳細行為：Auto 顯示可修改的影像亮度目標 `/255` 及唯讀實際值；Manual 顯示依 SDK hardware range 建立的 Exposure/Gain 欄位；兩種模式皆顯示 0–255 目前影像亮度。
- 驗收條件：Auto → Manual 保留相機當下值；Manual → Auto 先送 target 再開 AE；非法 target 顯示錯誤並保留上一個有效值；未連線或 SDK query 失敗不 crash。
- 影響模組：`camera_controller.py`、`camera_exposure.py`、`image_brightness.py`、`main_window_ui.py`、`main_window_devices.py`。
- 相容性／資料遷移：Recipe、HDR、SMU、溫度、影像 metadata schema 不變；既有單次自動曝光拍攝流程保留。
- 安全風險：僅讀寫相機曝光、Gain 與原廠 AE；不改變 AE limit/policy，不觸發 SMU output。
- 測試與驗證：新增 capability、mode ordering、亮度與 UI 用語測試；更新既有曝光 UI 結構測試，並執行無頭 UI smoke test。RisingCam 實機數值仍需連線驗收。
- 完成版本：V1.6.0。

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
- 相容性／資料遷移：當時不改 Recipe schema、Camera/HDR、影像與量測輸出格式；當時的 Recipe 停用邊界已由 FLOW-ELM-001 取代。
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
- 取代或關聯需求：補強 SMU-001；當時的 SAFE-001 暫緩狀態已由 FLOW-ELM-001 取代。

### SMU-003－統一狀態與安全自動連線

- 狀態：已完成（V1.5.0；fake VISA／SMU 驗證，Keysight B2901BL 實機待驗證）。
- 提出日期：2026-08-12（UTC+8）。
- 使用者原意：修正 SMU 已連線但 Manual panel 仍反灰，並在掃描到已知設備後安全自動連線。
- 詳細行為：高階狀態至少包含 DISCONNECTED／CONNECTING／READY_MANUAL／AUTO_RUNNING／ERROR／EMERGENCY_STOP；Manual UI 只讀取單一 policy；Camera 操作不鎖 SMU；啟動 auto-connect 依上次成功 serial、上次成功 resource、唯一受支援設備選擇，多台不明時不得猜測。
- 驗收條件：connected＋IDLE＋READY＋OUTPUT OFF 立即開放 Manual；Recipe ownership 鎖定並於完成後恢復；auto-connect 先將兩種 source 歸零、OUTPUT OFF 且 query 明確確認 OFF；不得送出 OUTPUT ON。
- 影響模組：`instrument_state_manager.py`、`smu_manager.py`、`smu_control.py`、`smu_manual_panel.py`、`device_panel.py`、`main_window_devices.py`、`main_window_ui.py`、測試與文件。
- 相容性／資料遷移：沿用 `QSettings` 並新增 auto-connect、last successful serial/resource key；不改 Recipe schema、Camera/HDR/Relay 或資料格式。
- 安全風險：SCPI safety initialization 與 `:OUTP?` response 仍需以實體 Keysight B2901BL、低限制且無敏感 DUT 條件驗證。
- 測試與驗證：狀態轉換、bind reset、選擇優先序、多設備 ambiguity、OUTPUT OFF 確認成功／失敗與禁止 OUTPUT ON。
- 完成版本：V1.5.0。
- 取代或關聯需求：補強 SMU-001、SMU-002；當時的 SAFE-001 暫緩狀態已由 FLOW-ELM-001 取代。

### UI-001－Responsive measurement workspace

- 狀態：已完成（V1.5.0；Qt offscreen 幾何驗證，Windows 多螢幕 DPI 實機待驗證）。
- 提出日期：2026-08-12（UTC+8）。
- 使用者原意：底部 context/actions、Sidebar 與 Live View 必須適應 1024×768 到 4K、Windows 100–200% DPI 與即時 resize，不能以固定解析度或單純兩列處理。
- 詳細行為：同一 widget set 依 logical available width 與 font metrics 切換 WIDE／STANDARD／COMPACT；Save Path 擴展且保留完整資料；Sidebar／Live View 使用 QSplitter；低高度 Sidebar 使用 QScrollArea；Emergency Stop 永遠位於直接可見的底部 actions。
- 驗收條件：1024／1366／1920 logical geometry 無控制項重疊；Browse／Start／Stop／Emergency 直接可見；resize 即時重排；Sidebar 不把 Live View 壓到低於 minimum；不依 physical resolution 寫條件。
- 影響模組：`measurement_control_bar.py`、`responsive_layout.py`、`main_window_ui.py`、`widgets.py`、responsive tests 與文件。
- 相容性／資料遷移：重用原 signal handler 與 widget aliases；不改 Camera、Recipe、HDR、White Light、measurement backend 或輸出資料。
- 安全風險：Qt offscreen 無法代表所有 Windows 顯示卡、字型與多螢幕切換，仍需 Windows 125／150／200% 實機視覺驗收。
- 測試與驗證：mode breakpoint、同一 widget identity/rearrangement、path/tooltip、QSizePolicy、主視窗 1024×768／1366×768／1920×1080 offscreen 幾何檢查。
- 完成版本：V1.5.0。
- 取代或關聯需求：不改 SAFE-001。

### SMU-003－Manual state consistency／safe recovery／handover hotfix

- 狀態：已完成（V1.5.1；fake VISA／SMU 驗證，Keysight B2901BL 實機待驗證）。
- 提出日期：2026-08-12（UTC+8）。
- 使用者原意：修正已連線但 Manual 反灰、畫面同時顯示 OUT ON／OFF、Polarity UNKNOWN 阻擋手動輸出，以及關閉／交接／Emergency 缺少一致安全確認的問題。
- 詳細行為：所有 GUI 使用同一不可變 `SMUUIState`；`READY_MANUAL` 必須是 IDLE／READY／OUTPUT OFF confirmed；矛盾 readback 進入 `UNEXPECTED_OUTPUT_ON`；Manual 使用 physical SMU coordinate，Recipe 才套用 confirmed Polarity；OFF-first shutdown 明確查詢；Manual ↔ Recipe 交接 fail closed；Emergency 先 latch 並誠實顯示 VISA 序列化限制。
- 驗收條件：未預期 ON 時只開放 OFF／Emergency；OFF query 為 ON／UNKNOWN／exception 時保留 fault/latch；Recipe ownership 不得被一般 recovery OFF 偷走；bind 失敗不得留下 zombie connection；device label 可換行。
- 影響模組：`smu_control.py`、`smu_base.py`、`smu_manager.py`、`instrument_state_manager.py`、Manual／Device／Main Window GUI、SMU tests 與文件。
- 相容性／資料遷移：當時不改 Recipe schema、Camera、HDR、Relay 或輸出資料；當時的 Recipe 停用邊界已由 FLOW-ELM-001 取代。
- 安全風險：fake driver 無法驗證實機韌體對 `:OUTP?` 的 timing；B2901BL 實機需驗證 OFF query、VISA timeout 與前面板狀態。
- 測試與驗證：Manual UNKNOWN polarity、Recipe polarity、unexpected ON、shutdown query failure、雙向 handover、Emergency race、bind cleanup、single-snapshot UI policy。
- 完成版本：V1.5.1。
- 取代或關聯需求：補強 SMU-001、SMU-002；當時的 SAFE-001 暫緩狀態已由 FLOW-ELM-001 取代。

### SMU-004－B2901BL OUTPUT OFF readback auto-output hotfix

- 狀態：已完成（V1.5.2；Keysight B2901BL 實機 root cause 已驗證，修正版待實機驗收）。
- 提出日期：2026-08-12（UTC+8）。
- 使用者原意：修正 periodic readback 在 OUTPUT OFF 時送出 `:MEAS:VOLT?`，造成 B2901BL 自動開啟 Source Output 並進入 `UNEXPECTED_OUTPUT_ON` 的問題。
- 詳細行為：readback 採 OUTP-first；OFF 時只查 output 並將量測值標成 unavailable；只有合法 `MANUAL + OUTPUT_ON` 才查 voltage/current/compliance；B2900 初始化設定並讀回確認 `:OUTP:ON:AUTO OFF`。
- 驗收條件：IDLE／OFF 連續 polling 不送 `MEAS:*` 且保持 `READY_MANUAL`；IDLE／ON 不量測並進入既有 `UNEXPECTED_OUTPUT_ON`；auto-output 無法確認 OFF 時不得發布 connected／READY_MANUAL。
- 影響模組：`smu_control.py`、`keysight_b2900.py`、`smu_manager.py`、`smu_manual_panel.py`、SMU tests、版本與文件。
- 相容性／資料遷移：不改 Recipe、Polarity、InstrumentStateManager、Camera/HDR/Relay 或資料格式。
- 安全風險：修正版仍須使用 B2901BL 驗證啟動後等待至少 10 秒保持 OUTPUT OFF，並驗證 Manual ON／readback／OFF 循環。
- 測試與驗證：fake B2901BL auto-enable regression、readback call order、unexpected ON state、startup repeated ticks、Manual ON→OFF、auto-output initialization order／fail-closed。
- 完成版本：V1.5.2。
- 取代或關聯需求：補強 SMU-002、SMU-003；當時的 SAFE-001 暫緩狀態已由 FLOW-ELM-001 取代。

### UI-002－Runtime responsive metrics 與 Recipe 顯示修正

- 狀態：已完成（V1.5.1；Qt offscreen 驗證，Windows 多螢幕 DPI 實機待驗證）。
- 提出日期：2026-08-12（UTC+8）。
- 使用者原意：測試必須真的 resize 並呼叫 responsive manager，不可直接指定 mode；runtime DPI／screen／font／style 變更須重新計算；Recipe 標題不可重複。
- 詳細行為：`refresh_metrics()` 更新 runtime minimum widths，event filter 與 `screenChanged` 重新判定；Recipe label 與 value 分離。
- 驗收條件：1024／1366／1920 resize 後由 `update_now()` 自動得到 COMPACT／STANDARD／WIDE；Emergency 永遠可見；Recipe 只顯示一次。
- 影響模組：`measurement_control_bar.py`、`responsive_layout.py`、`main_window.py` 與 responsive tests。
- 相容性／資料遷移：不改 signal handlers 或使用者設定。
- 安全風險：offscreen screen geometry 與實機 Windows scaling 仍可能不同。
- 測試與驗證：自動 mode integration test、runtime FontChange metrics test、既有 geometry／widget identity tests。
- 完成版本：V1.5.1。
- 取代或關聯需求：補強 UI-001。

### REPO-001－Python cache 與本機備份排除

- 狀態：已完成（V1.5.1）。
- 提出日期：2026-08-12（UTC+8）。
- 詳細行為：從 Git index 移除既有 `__pycache__`／`.pyc`，並忽略 Python cache、pytest cache、virtual environments 與 `backup/*.zip`。
- 驗收條件：遠端不得追蹤 cache 或 backup ZIP；source 不刪除；push 前 backup 仍依專案規則建立於本機。
- 完成版本：V1.5.1。

### SAFE-001－SMU 輸出保持停用

- 狀態：已由 SMU-001 與 FLOW-ELM-001 取代（V1.8.1）。
- 要求：Manual 與 Recipe 只能經 authoritative ownership/interlock 輸出；EL Matrix 必須完成每 Channel polarity、Dark I–V、相機 frame generation barrier、資料落盤及 verified safe shutdown。

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

### V1.8.2－2026-08-14

- Pixel CSV 從 EL Matrix 擷取熱路徑移至 verified safe shutdown 後的獨立後處理，禁止在 SMU OUTPUT ON 期間產生 CSV。
- 新增 TIFF-based Shared Dark 配對（Gain／Exposure／Repeat）、atomic metadata/manifest/status、SHA-256 驗證續作與 GUI 重試。
- GUI 改用 Runner 已完成的 safe-shutdown 結果，避免正常完成後重複以 Recipe ownership 關機而誤判 FAULT。

### V1.8.1－2026-08-14

- Recipe safety 改以實際 EL Matrix 計算完整流程、單一 Channel/J OUTPUT ON、最壞功率與最大曝光；新增 runtime watchdog。
- 正式順序改為全 Channel polarity → verified all-off → Shared Dark 一次 → 每 Channel Dark I–V → verified OFF → EL Matrix；禁止略過 polarity。
- 新增 immutable Measurement Snapshot/SHA-256、聚合式 hardware preflight、量測中控制鎖定及 frame sequence barrier。
- 完成 Pixel CSV 選配、逐張 metadata 實際路徑、Dark I–V CSV/JSON 與 final files SHA-256 manifest。
- Recipe schema v8 強化 untrusted JSON 結構、known migration、draft review items、unknown field 與 future schema rejection。
- 驗證結果：targeted 74/74、完整 unittest suite 274/274、compileall 與 `git diff --check` 通過；實機 acceptance test 待執行。

### V1.8.0－2026-08-14

- Recipe schema v7 新增固定 CH1～CH4 與共用 EL Matrix，舊 Recipe 缺少 Sample ID 時要求人工確認。
- 新增 Shared Dark 一次、多 Channel routing/per-channel polarity、J-level stabilization 與同 J OUTPUT persistence runner。
- 新增 RAW TIFF／Footer JPG／metadata manifest、modeless Progress、pre-run/runtime ETA 與既有 Live View frame reuse。
- 新增 EL Matrix ordering、capture counts、ETA、failure cleanup、RAW pixel integrity、Footer 與 filename tests；完整 suite 通過。

### V1.6.0－2026-08-12

- 曝光控制改為持續自動／手動下拉模式與固定 `QStackedWidget` 頁面；統一使用影像亮度、影像亮度目標、曝光時間與 Gain。
- Manual Exposure/Gain range 與 tooltip 由 SDK hardware range 產生；AE allowed range 分開查詢與記錄，不再混用 350 ms／500%。
- 新增 300 ms SDK Exposure/Gain status refresh 與獨立的 0–255 preview brightness helper；相機中斷與查詢失敗顯示 `--`。
- Auto ↔ Manual 切換依指定順序保留相機實際 Exposure/Gain 並套用既有影像亮度目標；新增 capability、亮度、模式順序與 UI 結構測試。

### V1.5.2－2026-08-12

- B2901BL 實機確認 OUTPUT OFF 時 `:MEAS:VOLT?` 會自動開啟 Source Output；readback 改為 OUTP-first，OFF 時禁止 `MEAS:*` polling。
- 只有合法 Manual OUTPUT ON 才取得 voltage/current/compliance；其他 ON 狀態保留 `UNEXPECTED_OUTPUT_ON` 安全復歸。
- B2900 初始化新增 `:OUTP:ON:AUTO OFF` 與 query confirmation；無法確認時連線 fail closed。
- Output OFF 的量測欄位顯示 unavailable；該版 Recipe 停用邊界其後已由 FLOW-ELM-001 取代。

### V1.5.1－2026-08-12

- 將 SMU GUI 收斂至含 `output_confirmed_off` 的 immutable snapshot，新增 Manual ON、未預期 ON 與安全復歸狀態。
- Manual 改用 physical SMU coordinate；Recipe 保留 Device coordinate × confirmed Polarity。
- 安全關閉改為 OUTPUT OFF／明確 query／source zero，新增雙向交接、Emergency latch 說明與 bind failure 全面清理。
- Responsive 測試改為真實 resize + manager update，新增 runtime metrics 重新計算並修正 Recipe 重複文字。
- 清理 Git index 中 Python cache 並擴充 `.gitignore`；該版 Recipe 停用邊界其後已由 FLOW-ELM-001 取代。

### V1.5.0－2026-08-12

- 統一 SMU connection／ownership／operation／output 的 GUI state，修正已連線但 Manual panel 因過期狀態反灰。
- 新增 fail-closed 啟動自動連線；依上次成功 identity 或唯一受支援設備選擇，連線發布前確認 source=0 與 OUTPUT OFF。
- 新增 WIDE／STANDARD／COMPACT control bar、font-metric breakpoint、QSplitter sidebar 與長路徑 tooltip。
- 新增 state、auto-connect safety 與 responsive GUI 測試；Camera、Recipe、HDR、Relay、資料格式與 Recipe execution 安全邊界不變。

### V1.4.1－2026-08-11

- 修正 Manual pending ownership race，新增 authoritative operation state 與 UI immediate lock。
- 新增 Emergency latch、UNKNOWN polarity interlock、fail-closed disconnect 與 shutdown confirmation／FAULT。
- Manual UI 改用 authoritative safety limits，CV／CC 切換時 setpoint 歸零；新增 deterministic fake SMU regression tests。
- 完整 Recipe execution、Camera/HDR 與 Relay 行為維持不變。

### V1.4.0－2026-08-11

- 新增 Manual CV／CC panel、central ownership/interlock、共用 polarity、安全限制、序列化 readback、Emergency 與 lifecycle cleanup。
- 新增 fake SMU control regression tests；該版 Recipe 停用邊界其後已由 FLOW-ELM-001 取代。

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
