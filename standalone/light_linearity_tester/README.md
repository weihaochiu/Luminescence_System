# GSP-4H 光源／相機線性度驗證

獨立工具：手動輸入光強計讀值，掃描 CH × PWM 等級 × Gain × Exposure，
分析曝光線性、實測相對光強線性、Gain 響應及 PWM 重複性／時間條紋。
重用 CameraController、CameraCaptureBridge 的 Scientific MONO16 與 GSP-4H controller；
不啟動 Recipe、SMU 或 Relay，不使用 HDR 合成。
每張使用已存在的相機 handle 進行軟體觸發，驗證 frame Exposure/Gain，
SDK 缺個別欄位時沿用 bridge 的 real exposure／trigger 前後讀回證據。
設定的丟棄幀各自明確觸發；相機軟體觸發不等於與光源 PWM 硬體同步。

## 啟動

完整測試程式位於 `standalone/light_linearity_tester/`。雙擊本資料夾的 `run.bat`，
或使用 repository 根目錄的 `run_light_linearity_qualification.bat`，兩者開啟相同程式。
命令列可在 repository 根目錄執行：

```powershell
.\.venv\Scripts\python.exe -m standalone.light_linearity_tester.main
```

使用專案既有 `.venv` 與依賴；啟動器不自動安裝套件。
此資料夾是獨立啟動的工具，仍依賴 repository 的 `core/`、`gui/`、
`tools/camera_linearity_qualification/`、`tools/gsp4h_controller/` 與資源。
請保留在 repository 內執行；目前不是可單獨複製到其他電腦的 EXE 套件。
關閉其他占用同一相機／GSP-4H 串口的程式。

## 預設一鍵自動檢測

Gain 清單預設為 **100、200、300、400、500、1000、2000、3000、5000%**。
待機時可在「拍攝＋分析」頁直接編輯逗號分隔的 Gain 清單；
自動／固定矩陣模式均使用目前輸入的清單，切換模式與操作完成不覆蓋使用者輸入。
拍攝期間鎖定欄位，結束後恢復可編輯；空白、重複、非法數值會在開始前拒絕。
這是預設九個測試設定，不是把硬體範圍內每個百分比整數都掃一遍。
相機宣告不支援的 Gain 記為 `UNSUPPORTED_HARDWARE_GAIN`，不自行更換成其他值；
Gain 讀回不符、硬體／存檔故障會中止並保留資料。此功能未宣稱實機 5000% 已驗收。

1. 連接相機、GSP-4H，選通道、固定照明／鏡頭／光圈與 ROI。
2. 保持「一鍵自動檢測」勾選，選完整影像、ROI 或摘要保存模式，按開始。
   不用填 PWM、曝光清單、光強表。光源／相機應先暖機。
3. 各 Gain 用 **軟體 ROI 自動曝光** 找錨點：只改曝光、不改 Gain，
   使用相機既有 handle 的 verified software trigger。
   不直接使用一般 SDK「曝光優先」AE，因為該模式可能改 Gain。
4. 程式邊試拍邊選 PWM。從少量種子探測，依可用訊號範圍細分區間，
   每個 Gain 以至少五個有效 PWM、至少 2 EV 的訊號跨度為目標。
   這裡的 2 EV 是工程覆蓋門檻，不是相機動態範圍的官方宣告。
5. 以 1 EV（×2／÷2）找曝光上下界，再細化邊界；正式曝光使用均勻 EV 點，
   最大間隔 0.5 EV，至少五個不同曝光點與 2 EV 曝光跨度。
   上下界不剛好落在 0.5 EV 網格時，會等距分配成較小 EV 間隔。
6. 保留各 Gain 的共同曝光，供跨 PWM 的實測光強回歸。
   曝光範圍狹窄的 PWM 仍可只保存共同曝光點，用於光強分析；
   它自己的曝光曲線標示受限，不會把五個很接近的點硬算成 PASS。
7. 拍攝完成後自動開啟 **本次 LUX 補填視窗**。只列實際可用 PWM 與背景 PWM 0，
   開窗先自動切到 PWM 0。設備讀回確認及拍攝設定的穩定等待完成後，才開放 LUX 輸入。
   使用者只需讀照度計、輸入穩定數值、按「確定／下一個」（亦可用 Enter）；
   程式自動設定下一個 PWM，不用選列、輸入 PWM 或按套用。
   最後一項按「確定並完成分析」便自動驗證關燈、保存 LUX 並產生報告。
   光強計識別、光學條件、備註可補充；每次確定代表量測配置與拍攝一致且讀值已穩定。
   預設使用本次最大已量測 PWM 作相對參考，不強制要求 PWM 255。

LUX 歷史表唯讀。空白、非數字、NaN/Inf、負值或不高於背景的照光讀值不會進入下一項。
需要修正已輸入值時按「上一步」，程式會自動重新設定該 PWM，再讓使用者確認讀值。
切光或讀回失败時保持輸入鎖定，可「重試設定」或「稍後補填」安全退出。
切光等待可取消；退出後的延遲 callback 不會再次開燈。

程序在沒有 LUX 時先完成曝光／穩定度分析，狀態為 `AWAITING_LUX`。
可選「稍後補填」，程式安全關燈並保留全部拍攝資料。
下次連接 GSP-4H，分析同一資料夾即可再次開啟引導；不需重新拍照。
後補 LUX 需要重現拍攝時的光源、位置、方向、光學配置、暖機與切光等待条件。
它是使用者量測參考，不是相機 DN 換算出的 LUX；若照明漂移，須重新量測／拍攝。

各正式条件保持 Light/Dark 至少五張。預掃描最多兩張 Light／三張 Dark；
第一張已接近飽和時立即結束該探測，不拍完整組。
預掃描與正式影像分開標示；預掃描照片也遵守所選保存模式。
自動 SNR 使用 0.5 effective-DN 的保守噪聲下限，避免零 Dark variance 造成不合理的無限 SNR。
短曝光大幅閃爍／時間條紋會記為 `UNSTABLE`，嘗試較長曝光或較低亮度的錨點。
探測次數有上限，不能找到足夠範圍就標示不足；不根據 R² 刪除非線性點。
來源不明的溫度補償係數不參與計算；相機溫度仍逐張記錄。

自動選點前，時間／張數無法精確預知。開始前提供最低正式點數的容量估算，
預掃描與寬 EV 範圍可能增加張數，不保證比固定矩陣更少。
每次寫檔檢查剩餘空間，空間不足會停止、關燈及保存已完成資料。
進度視窗在自動規劃階段顯示不定進度，正式條件顯示目前規劃張數，並持續更新等待秒數。

`SUMMARY/automatic_planning.json` 保存 AE、各 Gain 的 PWM／曝光計畫、探測資料與不足原因。
`SUMMARY/frame_journal.jsonl` 逐張追加紀錄；定期建立 manifest checkpoint，
正常結束或取消時保存完整 manifest，減少大量短曝光時反覆重寫的開銷。
`SUMMARY/LUX/lux_*.json` 保存每次後補量測版本，與原始 snapshot／statistics 的雜湊綁定；
`analysis_reference.json` 指向目前採用版本。原始拍攝快照、統計與影像均不改寫。
`gain_overview.csv` 與報告 Gain 比較表列出各 Gain 的曲線 PASS／FAIL／受限數及 Dark noise DN。
實測噪聲單位是 DN，不宣稱等於廠商的電子數 read-noise 或絕對動態範圍。

取消「一鍵自動檢測」即可使用下列原有固定矩陣／拍攝前光強表模式。

## 手動光強量測

1. 到「GSP-4H／手動光強表」選 PORT／Parity，連線只讀設定，不自動點燈。
2. 選 CH1～CH4，輸入光源名稱／顏色、光強計識別、單位、量測日期、位置／距離及備註。
3. 選 0～255 等級，按「套用此等級供光強計量測」；只啟用該通道，其他通道歸零。
   PWM 0 會安全關燈。此操作是明確點燈要求，選通道或編輯表格本身不寫硬體。
4. 等光源及光強計讀值穩定，把數值輸入對應列。可只量測需要掃描的等級，其他留空。
5. 背景／零點填入光強計在不照明時的讀值；PWM 0 的輸入不會自動改變背景欄位。
6. 預設以 PWM 255 為參考，也可選其他已測等級：
   `relative = (reading - background) / (reference reading - background)`。
   正規化不代表 PWM 255 已驗證為 100% duty/DC；空白不插值，不當成零。
7. JSON 保存完整通道、儀器與光學條件。CSV 有 256 列，欄位為
   `channel,pwm_level,measured_intensity,unit,relative_intensity`；匯入只使用原始讀值，
   拒絕錯誤通道／單位、重複 PWM、負值與 NaN/Inf，不直接相信 CSV 相對值。

各通道的有效表格在切換、開始測試、檔案操作及正常退出時保存於
本資料夾的 `data/calibrations/CH1.json` 等檔案；表格不修改主程式亮度偏好。
新位置尚無對應光強表時，會讀取舊 `local/light_linearity/calibrations/` 的表格，
再次保存時寫入新位置；舊表格與舊測試資料均保留。
不同光源／顏色使用不同表格。換燈具、量測單位、位置、距離、鏡頭／光圈後重新量測。
Lux 等讀值只在同一光源光譜下作相對參考，不用來跨顏色比較光功率。

## 照明與 ROI

不必照滿全幅。框選均勻、穩定、未飽和且避開光斑邊緣的照明 ROI；
全幅原始照片仍可保存，但線性結論只適用於此 ROI。
全畫面像素一致性驗證需要全幅均勻照明。
光強計放在能代表 ROI 照明的固定位置，保持量測與拍攝的光學配置一致。

## 掃描

1. 連接相機，確認 Scientific MONO16、實際 SensorBitDepth、EffectiveDNMax、RAW alignment。
2. 框選 ROI。設定 Gain、曝光、Light/Dark 張數、丟棄幀與相機暖機等待。
3. 設定 PWM 等級清單；0 是 Dark，不加入 Light 掃描。
4. 預設要求清單的每個等級都有正的實測相對光強。取消此選項可做探索掃描，
   未量測的等級不參與實測光強回歸。
5. 設定每次切光後的穩定秒數。每條件先關燈拍 matching Dark，再點燈等待後拍 Light，
   因此光強表必須對應足夠穩定後的照明；LED 的熱漂移／切光暫態仍需實機確認。
6. 「Pilot」使用少量 repeats；不滿五次或不滿五個有效點不會給該回歸 PASS。
7. 「估算空間與測試時間」依實際相機解析度／ROI 計算，包含 matching Dark、丟棄幀與切光等待。
   按 Start 再顯示本次估計。估計不含讀出、串口與寫檔延遲；提前停止可能減少張數。
8. 進度對話框顯示條件、當前 repeat、曝光、張數、已用時間與速度估計 ETA。
   GUI 每 0.5 秒更新，等待長曝光時也持續顯示等待時間。這表示介面仍回應，不表示硬體已完成。
   安全停止／關閉對話框／Esc 都要求取消，保持進度視窗直到 worker 完成清理。

每個條件只保留一份 Dark 的統計累積於記憶體，處理完便釋放；不在 RAM 保留整個矩陣。
接近飽和時跳過同 PWM／Gain 的更長曝光，記錄原因，不掩蓋其他非線性點。
退出與中止均嘗試 L＋CH1～4 歸零，讀回後再釋放串口；失敗保留視窗供重試。

## PWM

目前 GSP-4H driver 不提供頻率／duty 查詢或相機硬體同步。
頻率可手動註記為 Hz（不會改變設備），未知留空；metadata 記錄未驗證與未同步。
各條件重複影像分析亮度 CV 與正規化 row/column profile 的時間變化。
需要 PWM 診斷時，選短／中／長曝光並把 Light repeats 提高至約 30 張；保留個別影像／統計。
加入 0～20 ms 的軟體間隔變化，不能保證完整 PWM 相位覆蓋，也不能由此推定唯一頻率。
時間條紋指標不保證發現固定條紋；固定條紋、均勻度及相機快門模式仍需查看原圖與實機驗收。

## 保存模式與資料夾

開始前自行選擇，預設完整保存；工具不自動刪除以前的測試。
新的預設輸出位置為本資料夾的 `data/runs/`；可自行選其他輸出資料夾。
`data/` 已由本資料夾 `.gitignore` 排除，不將照片或手動量測資料加入 Git。

- 全部完整原始影像：每張 Light/Dark 都保存 uint16 MONO16 TIFF。
- ROI＋首張全幅：每個條件、每個 Light/Dark 類別的首張保存全幅，其餘保存原始 ROI。
  sidecar 記錄 stored_region 與分析 ROI，不改變 RAW DN／bit depth。
- 僅摘要：不保存 TIFF，仍計算全部 ROI 統計與逐幀 metadata；不能事後重算像素／ROI。

```text
Light_Linearity_<timestamp>_<id>/
  SUMMARY/
    measurement_snapshot.json       # 當次光強表、SHA-256、ROI、plan、門檻、commit/dirty
    capture_manifest.json           # 完成／取消／失敗、逐幀、跳過、cleanup errors
    condition_statistics.json        # 完整條件及逐張 Light 數值
    ANALYSIS/
      LIGHT_LINEARITY_REPORT.md
      analysis_summary.json
      conditions.csv
      frame_statistics.csv
      exposure_linearity.csv
      measured_intensity_linearity.csv
      gain_response.csv
      *.png
  IMAGES/CH<channel>_PWM<level>/LIGHT|DARK/G<gain>/*.tiff, *.json
```

「Analyze Existing Folder」選測試根目錄或 SUMMARY，用當次保存的光強表／統計產生報告，
不把現在編輯的光強表套到舊結果，也不重新選 ROI；頁面繼承的 ROI 欄位不參與此操作。
保留的 TIFF 驗證 SHA-256；已移走影像時仍可讀摘要，但報告標示缺圖。
統計／快照校驗失敗會拒絕分析。取消／失敗保留已完成條件及清理結果。

## 分析限制與驗證

一般線性度測試可使用一種均勻、穩定的白光或單色光，不必逐色測試。
保持同一光源的光譜與光學條件穩定；只有比較波長響應或特定 EL 波段時才分色。

固定通道／PWM／Gain 的曝光回歸與固定 Gain／實際曝光的實測相對光強回歸分開。
使用 Dark 扣除的 ROI mean（保留負值），不做 Gamma、tone mapping 或自動對比。
低 SNR、缺有效光強、近飽和的排除原因逐項記錄；其他非線性點不刪除以改善 R²。
至少五個有效 x 點、Light/Dark 各五次、R²≥0.999、最大相對殘差≤2%、CV及時間條紋≤2%，
才會在對應測試組顯示 PASS。它是工程門檻，非完整 EMVA 1288 認證。
手動光強計的精度／線性／頻寬與光學配置由使用者記錄；不能宣稱超過參考儀器的精度。
始終 `profile_usable_for_production=false`，不修改 production 相機設定。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_light_linearity*.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

測試使用小型 synthetic frames、模擬光源與 Qt UI；不代表 RisingCam／GSP-4H／光強計實機已驗收。
本資料夾的 `run_tests.bat` 可執行相關測試；完整專案驗證使用上列第二個指令。
