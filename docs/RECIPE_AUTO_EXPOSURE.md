# Recipe 自動曝光與 Gain 選擇

需求日期：2026-11-04（Asia/Taipei）。

狀態：已實作軟體流程；驗證方式為 Qt、模擬 SDK／硬體與合成影像測試。實際 RisingCam 的 AE 收斂、指定 Gain 鎖定、逾時／斷線與 Dark 拍攝仍須實機驗收。

2026-11-04 實機錯誤定位與 bundled SDK 檢查：

- 實機先回報 `get_AutoExpoRange(): 0x8000FFFF`，之後回報 `put_MaxAutoExpoTimeAGain(15000000, 500): 0x80070057`。
- 本機附帶的 `gui/sdk/nncam.dll` 版本為 `57.27250.20241216`，SHA-256 為 `5415db5023282484bff0ad5b293df2a6c12a1c1abf7ed8a0e6ff6816750f96fa`。靜態檢查 IUA8300KMBV4 的虛擬介面與函式內容確認：最大 AE setter 在 RVA `0xA6D9E5` 比較曝光與 `0x4C4B40`（5,000,000 µs），超過即回傳 `E_INVALIDARG`；Gain 同時受 `0x1388`（5000%）限制。這不是手動曝光硬體上限。
- 同一 setter 在沒有取像影像處理流程時，會於 RVA `0xA6DBD1` 回傳 `E_UNEXPECTED`，且可能已寫入暫存範圍；因此讀寫／還原均使用個別 limit API，並在取像啟動後寫入、核對實際值。
- 合併 range getter 在此介面的 RVA `0xA3EF01` 固定回傳 `E_UNEXPECTED`，即使已填入輸出參數；Recipe 不再依賴此 API。上述證據來自專案實際 DLL，不代表已完成實機 AE 收斂驗收。

先前自動曝光階段的 14 情境模擬、逐步紀錄及流程圖，見 [流程模擬報告](RECIPE_AUTO_EXPOSURE_SIMULATION.md)。該階段相關回歸 152／152 通過；模擬階段未再變更正式硬體控制程式。

本次整合加入 [各 Channel ROI](RECIPE_CHANNEL_ROI.md)：正式量測前開啟白光，依啟用 channel 設定 CH1→ROI1 至 CH4→ROI4。後續每個 channel 的 AE 都使用對應 ROI；TIFF、衍生影像及 Pixel CSV 只儲存該範圍，Shared Dark 從同一次拍攝分別裁出各 channel 的 ROI。測光設定必須完成 SDK readback 驗證。

2026-11-04 整合推送前驗證：相關回歸 **179／179**、完整 `unittest discover -s tests -v` **846／846 通過**（0 failed、0 errors、0 skipped），編譯與差異檢查通過。先前光源 GUI worker 逾時在未修改該工具／測試下重跑通過；文件內先前失敗數量保留為歷史紀錄。

## 1. 使用者需求

在既有 Recipe 的「3 EL Matrix」設定頁加入「曝光模式」下拉選單，選項為「手動曝光」與「自動曝光」，下方動態顯示對應表單。此介面依使用者後續指示，取代原本兩組表單同時顯示、未選用者反灰的設計。

- 選擇自動曝光：下拉選單下方只顯示自動曝光表單，隱藏並停用手動 Gain × Exposure 矩陣。
- 選擇手動曝光：下拉選單下方只顯示可編輯的手動矩陣，隱藏並停用自動曝光表單。
- 自動曝光提供「自動 Gain」及「指定 Gain」兩種選項。
- 自動曝光新增自訂 Stop 清單，支援正負及小數，依清單順序拍攝；不強制加入 0 Stop。
- 兩種曝光模式必須擇一，不能同時選取或同時不選取。
- 切換模式保留兩邊的設定；停用的設定不參與本次拍攝或有效性檢查。已填寫且可解析的手動矩陣也會隨自動曝光 Recipe 一起保存。
- Repeat 是兩種模式共用的每條件拍攝次數，持續可編輯。Channel、電流密度／電壓、穩定時間與 compliance 也持續沿用既有設定。

## 2. 自動曝光選項

| 選項 | 行為 |
| --- | --- |
| 自動 Gain | SDK 採 Exposure Preferred（策略 1），可調整曝光時間與 Gain。Gain 使用相機目前 AE 上下限與硬體範圍的交集。 |
| 指定 Gain | 輸入單一 Gain 百分比；SDK 採 Exposure Only（策略 0），並將 AE Gain 最小值與最大值都設成指定值，只調整曝光時間。 |

指定 Gain 欄位只有在「自動曝光＋指定 Gain」時可編輯。這是單一固定 Gain，不是 Gain 清單，也不是 Gain 上限模式。

自動曝光另提供下列 Recipe 專屬參數，避免依賴未選用的手動矩陣：

| 參數 | 預設值／規則 |
| --- | --- |
| 亮度目標 | 50%；可選 20、30、40、50、60、70、80%。沿用既有 SDK target 校正換算；未校正時是 SDK 目標估計。 |
| 曝光時間上限 | 15000 ms；適用於正式拍攝與各 Stop。原生 AE 基準另受 bundled SDK 的 5000 ms 上限限制；系統取兩者與相機能力的交集。最小曝光時間採硬體範圍與官方範圍的交集下限。 |
| AE 收斂逾時 | 60 s；必須大於曝光時間上限換算的秒數。 |
| 指定 Gain | 100%；UI 可輸入 100～65535 的整數百分比，啟動前須符合相機範圍與原生 AE 的 5000% 上限。此 AE 限制不套用於手動曝光模式。 |
| 自訂 Stop 清單 | 預設 `0`，例如 `-2, -1, 0, 0.5, 2`；1～33 個不重複的有限數值，範圍 −12～+12。每個 Stop 皆拍攝 Repeat 次。 |

既有「拍攝逾時」仍用於正式影像拍攝，須至少涵蓋自動曝光時間上限。它與 AE 收斂逾時分開。

## 3. 執行流程

### 手動曝光

維持原本的 Channel → 電流密度／電壓 → Gain → Exposure → Repeat 流程；啟用 Shared Dark 時，仍在 EL 前依手動矩陣拍攝一次。

### 自動曝光

1. 沿用既有初始化、hardware preflight 與選配的各 Channel 極性確認。
2. 各 Channel 完成 routing、polarity factor 套用及選配 Dark I–V。
3. 套用該條件的電流密度／電壓並等待穩定。
4. 停止取像後保存原設定並設定測光策略／目標；重新啟動取像後，設定及核對個別 AE 最小／最大範圍，最後啟用單次 AE。AE 範圍設定需要已啟動的影像處理流程。
5. 收到 SDK 收斂事件後，先關閉 AE 並讀回曝光時間／Gain；確認結果符合曝光上限與 Gain 限制。
6. AE 關閉後，停止取像以恢復策略、測光比例與亮度目標，再啟動取像以恢復並核對 AE 範圍。正式拍攝會重新套用並驗證收斂後的曝光／Gain。
7. 鎖定收斂 Gain，以「AE 基準曝光時間 × 2^Stop」計算各級曝光，依清單順序、每級 Repeat 次拍攝；沿用既有軟體觸發、設定讀回、frame generation barrier 與影格驗證流程。
8. 換下一個電流密度／電壓或 Channel 時重新執行一次 AE。Repeat 之間不重新尋找曝光。
9. 全部 EL 完成後，若啟用 Dark，先確認 SMU 輸出、白光／GSP4H 光源及 routing 關閉，再依本次實際使用的唯一 Gain／曝光時間組合拍攝 Shared Dark，每組仍拍攝 Repeat 次。
10. 完成既有 safe shutdown；Pixel CSV 仍只在安全關閉驗證通過後處理。

自動模式必須在 EL 後拍 Dark，原因是曝光與 Gain 要到每個實際發光條件的 AE 收斂後才確定。不得使用隱藏的手動矩陣中的曝光值代替，或在黑暗條件下執行 AE 決定 EL 曝光。

Shared Dark 依 Gain／曝光時間去重，沿用既有 Repeat／解析度／影像尺寸配對供 Pixel CSV 使用；不匹配的 Dark 不得混用。取消或中途失敗可能尚未取得匹配 Dark，已完成的原始影像保留，但不宣稱該批次已完成暗校正。

## 4. 失敗處理與限制

- AE ROI 必須已驗證；SDK policy 與 AE Gain 範圍資訊須可讀取。
- 修改 AE 範圍、策略、測光比例、亮度目標及指定 Gain 後，都驗證讀回；不支援或讀回不符即失敗，不默默改用其他策略。原生 AE 基準最多 5000 ms，正式 Stop 拍攝可依相機與 Recipe 上限超過此值；啟動前的時間估計維持依拍攝上限作保守估算。
- 不收斂、收斂逾時、使用者取消、相機錯誤／斷線、固定 Gain 漂移或結果超出上限時，中止該次量測並走既有安全關閉流程。
- 不因為亮度不足而突破指定 Gain 或曝光時間上限；不以失敗結果繼續正式拍攝。
- 相機操作集中在既有 Qt owner thread；worker 透過 bridge 等待結果，等待時持續檢查取消與 runtime watchdog，不開第二條相機串流。
- 清理時使晚到的 AE 請求／結果失效，關閉 AE 並恢復臨時設定；清理讀回異常也必須回報失敗。
- 自動模式的正式 EL 張數為 Channel 數 × 電氣條件數 × Stop 數 × Repeat。Dark 張數最多與 EL 張數相同，實際會依唯一曝光／Gain 去重；啟動前張數與磁碟按最多 Dark 估算，時間則採包含每條件 AE 逾時及各 Stop 曝光上限之和的保守估算。時間仍受實際拍攝／存檔速度影響，估算不代表 SDK 已算出曝光值，也不是固定的完成期限。
- 自動 Gain 可能使不同條件的 Gain 不同。未完成 Gain／線性／Dark 等校正前，不可直接視為定量可比的 EL 資料。

## 5. Recipe 保存與相容性

Recipe schema 更新為 **13**。新設定存於既有 `el_matrix`：

```json
{
  "exposure_mode": "auto",
  "auto_gain_mode": "fixed",
  "auto_gain_percent": 200,
  "auto_target_percent": 50,
  "auto_max_exposure_ms": 15000.0,
  "auto_timeout_s": 60.0,
  "auto_exposure_stops": [-2, -1, 0, 1, 2],
  "gains_percent": [100, 200, 300],
  "exposures_ms": [100, 500, 1000],
  "repeat": 2
}
```

- `exposure_mode`：`manual`／`auto`，預設 `manual`。
- `auto_gain_mode`：`auto`／`fixed`，預設 `auto`。
- `auto_exposure_stops` 預設 `[0.0]`，v12 與更早 Recipe 缺少此欄位時只拍原本 AE 基準，不增加張數。
- 舊 Recipe 缺少新欄位時，預設為手動曝光，保留原本矩陣，不自動改成 AE。
- 手動／自動設定隨儲存、重開、複製、匯入、匯出與 immutable Measurement Snapshot 保存；新版本 Recipe 不應由舊版程式開啟。
- 每張正式影像繼續保存實際曝光、Gain 與設定／影格讀回；另加入 `RecipeExposureMode`、`RecipeAEGainMode`、`RecipeAEConverged`，以及 AE 目標、策略、Gain 上下限、曝光上限、ROI 與校正套用資訊。後拍 Dark 同樣保留對應的 AE 診斷資料；其中收斂狀態指其來源 EL 條件，Dark 本身不執行 AE。

## 6. 驗收重點與程式位置

- UI：下拉選單模式切換、下方只顯示所選表單、隱藏表單停用、指定 Gain 輸入啟用條件、切換／載入／保存時保留數值、捲動可達性。
- 資料：舊 Recipe 預設手動、新欄位 round-trip、無效模式／數值／逾時拒絕、停用矩陣不影響自動拍攝。
- 執行：定電流密度與定電壓、每條件 AE 一次、Repeat 鎖定、不拍攝未收斂結果、Dark 去重及後處理配對。
- SDK／取消：自動與指定 Gain 策略、設定讀回、部分設定失敗復原、固定 Gain 漂移、AE 失敗／逾時／取消／相機錯誤、晚到的 start／結果不重新啟動 AE。
- 實機：驗證實際相機的 policy 0／1、Gain 固定上下限、長曝光收斂、取消／斷線處置、Dark 熱漂移與資料一致性。

主要模組：`gui/recipe_store.py`、`gui/recipe_dialog_pages.py`、`gui/recipe_dialog_logic.py`、`gui/measurement_execution_plan.py`、`gui/el_matrix_plan.py`、`gui/el_matrix_runner.py`、`gui/el_matrix_preflight.py`、`gui/el_matrix_hardware.py`、`gui/camera_capture_bridge.py`、`gui/camera_recipe_ae.py`、`gui/main_window_measurement.py`。

功能回歸測試：`tests/test_recipe_auto_exposure.py`。完整驗證指令：

```powershell
.venv\Scripts\python.exe -m unittest tests.test_recipe_auto_exposure -v
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 7. 軟體驗證紀錄

- 功能測試：`tests/test_recipe_auto_exposure.py`，26／26 通過。
- 自動曝光初版的完整回歸曾達到 801／801 通過。
- 下拉選單調整當時的相關回歸：102／102 通過，包含模式選項、載入／保存、數值保留、實際顯示／隱藏與手動表單高度縮回。
- 下拉選單調整當時的完整回歸執行 801 項，800 項通過、1 項失敗；該次重跑仍為相同結果。
- 該階段唯一失敗為既有光源 GUI 測試 `test_cancelling_lux_measurement_turns_off_light_through_worker`（`tests/test_light_linearity_automatic.py:305`），背景 worker 在測試等待時間內未完成。光源程式與該測試維持原狀；下述最新時間預估版本的完整回歸中該項已通過。
- 最新時間預估同步版本：新增預估測試 11／11，相關回歸 121／121，完整回歸 **812／812 通過**。完整指令為 `.venv\Scripts\python.exe -m unittest discover -s tests -v`。
- 後續自訂 Stop 清單版本：新增 Stop 測試 **11／11**，相關回歸 **152／152**；完整回歸 **823 項中 822 通過、1 失敗**（238.225 s）。失敗仍為上述既有光源 GUI worker 等待逾時；單獨重跑該項亦失敗，該光源程式及測試未修改。因完整測試未全數通過，保留修改、不 commit／push。
- Python 編譯與 `git diff --check` 通過；Qt offscreen 以中文字型檢查自動／手動模式畫面。下拉選單版本另檢查動態表單顯示與隱藏。
- 本次沒有相機／SMU／Relay 實機操作；實機驗收範圍仍依第 6 節。

## 8. 時間預估同步調整

Recipe 編輯器右側新增「時間預估」，直接使用 `ELMatrixPlan`，顯示估算依據、總時間、純曝光時間、拍攝數量與單一電氣條件 OUTPUT ON 時間。修改曝光模式、Channel、有效的電流／電壓清單、Repeat、Dark、穩定時間與相關曝光參數時立即更新。未選用的手動矩陣不影響自動模式；無有效設定或無選取 Recipe 時清除舊估算。

### 啟動前計算

設 `N = 啟用 Channel 數 × 有效電流密度／電壓條件數`、`R = Repeat`：

- 手動模式：EL 張數為 `N × Gain 數 × Exposure 數 × R`，Shared Dark 只按完整 Gain × Exposure × Repeat 矩陣拍一次；純曝光時間按所有實際指定曝光時間相加，不使用自動曝光設定。
- 自動模式：設 `S = Stop 數`，EL 張數為 `N × S × R`，Dark 暫按最多 `N × S × R` 張；每個條件執行一次 AE，AE 預算為 `N × AE 收斂逾時`，不乘以 Stop 數、Gain 數、手動曝光段數或 Repeat。各 Stop 先按受限 AE 基準上限乘以 `2^Stop` 估算。
- 自動 Gain／指定 Gain 都是一個條件執行一次 AE，不額外增加 Gain 矩陣。
- 兩種模式均包含穩定等待、極性、Dark IV、routing、Dark setup 與預估拍攝／存檔開銷。
- 開始量測確認視窗顯示相同估算；自動模式另說明 AE 收斂預算。Pixel CSV 時間不混入硬體預估，於安全關閉後另按實際檔案處理速度估算。

### 執行中修正

- 可取消等待期間，約每秒送出剩餘時間與預計完成時間更新；AE、穩定等待或正式曝光仍在進行時會消耗目前階段的預算。
- 某階段完成後，移除該階段全部預估預算，避免因實際比預估快而留下一段永遠扣不完的時間。
- 每個 AE 一旦收斂，立即以實際曝光取代該條件所有 Repeat 的曝光上限；同時按目前已知的唯一 Gain／曝光時間更新 Dark。其他尚未收斂條件保留各自 AE 逾時／曝光上限預算。
- 相同 Gain／曝光結果立即共用同一組 Dark 預算；不同 Gain 或曝光保持分開，無須等到所有 EL 拍攝完成才修正。
- 進度視窗的「估算依據」區分手動矩陣、自動曝光待收斂、全部 AE 已鎖定與 Pixel CSV 處理。
- 剩餘時間按已觀察到的拍攝／存檔開銷持續修正；預計完成時間允許延後，不再強制只能提前。完成全部拍攝後，已用完的固定預算與曝光預算不殘留。

例如 2 個電氣條件、1 個 Channel、Repeat 2、自動曝光上限 15 s、AE 逾時 60 s 且啟用 Dark，先估 4 EL＋最多 4 Dark，純曝光最多估 120 s、AE 預算 120 s（另加其餘開銷）。如果兩個條件都收斂到相同 Gain／500 ms，則更新為 4 EL＋2 Dark；Dark 剩餘純曝光只需 1 s。

回歸測試：`tests/test_exposure_estimates.py`，涵蓋公式、隱藏矩陣排除、條件／Channel／Repeat、部分收斂與 Dark 去重、等待倒數、較慢拍攝延後完成時間、Recipe 即時顯示、確認視窗與執行進度。

## 9. 自訂 Stop 清單

- 以逗號或分號分隔，支援 `-2, -1, 0, 0.5, 2`。照輸入順序拍攝；0 表示 AE 基準，若清單未填 0，就不拍基準影像。AE 本身仍須先收斂。
- 每個電氣條件只收斂一次，之後 Gain 固定；Stop 只改變曝光時間。例：基準 500 ms，`-1, 0, 1` 依序拍攝 250、500、1000 ms，每級皆套用 Repeat。
- 「曝光時間上限」適用於基準與所有正式拍攝，並須符合相機範圍。系統先縮小 SDK AE 基準範圍：下限為 `ceil(相機最短曝光 / min(1, 最小 Stop 倍率))`，上限為 `floor(拍攝曝光上限 / max(1, 最大 Stop 倍率))`。例如最短 30 µs、上限 15000 ms、Stop 清單 `-2, 0, 2`，AE 基準可用範圍為 120～3750000 µs。
- 所有曝光按相機整數微秒精度四捨五入。空白、重複、非有限值、範圍外或無法容納完整清單的設定禁止啟動；收斂後若不同 Stop 變成相同微秒曝光，亦中止並安全關閉，不刪除該級、不截斷到相同曝光。
- Dark 依最終 Gain／曝光時間去重，包含不同 Stop 或不同條件間的相同組合；各 Repeat 保持既有配對。
- EL metadata 新增 `RecipeAEBaselineExposureUs` 與 `RecipeAEStop`，並保存實際曝光。SDK 診斷另記錄受限基準範圍 `RecipeAEMinExposureMs`／`RecipeAEMaxExposureMs` 及總拍攝上限 `RecipeAEExposureCeilingMs`。Shared Dark 的 AE 診斷來自使用該組 Gain／曝光的來源 EL 條件，Dark 自身不執行 AE。
- Recipe 預覽、確認視窗、磁碟需求與 runtime ETA 皆使用 Stop 數及各級曝光之和；收斂後立即以整組實際 Stop 曝光取代上限，Dark 亦立即去重。

Stop 回歸測試：`tests/test_recipe_ae_stops.py`，涵蓋小數與順序、0 可省略、界限／微秒精度、v12 預設與 v13 保存、動態預估、SDK 範圍、實際 runner 序列／metadata／Dark 配對、部分收斂 ETA 與安全失敗。

介面驗證截圖（Qt offscreen 實際表單，非實機拍攝）：`local/recipe_stops_current_density.png`、`local/recipe_stops_voltage.png`。截圖使用 `-2, -1, 0, 0.5, 2`、Repeat 2，確認電流／電壓矩陣仍可編輯，且右側執行順序及時間預估包含各 Stop。
