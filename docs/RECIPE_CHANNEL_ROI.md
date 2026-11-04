# Recipe 各 Channel ROI

Recipe 正式量測前以元件的 **EL 發光** 定位，在獨立 Live View 視窗依啟用的 CH1～CH4 逐一框選。CH1 固定使用 ROI1，依此類推；只啟用 CH2／CH4 時只需設定 ROI2／ROI4。每次開始量測重新選取，座標不寫入 Recipe 預設值。

在 Recipe「3 EL Matrix → ROI 定位（EL 發光）」設定選取 ROI 的電流密度或電壓；輸出模式跟隨同頁的定電流密度／定電壓，Compliance 沿用同頁設定。電流密度乘各通道面積換算實際電流。schema 14 保存 `roi_current_density_ma_cm2`、`roi_voltage_v`；舊檔缺少時預設 2 mA/cm²／0.8 V，仍須通過全域安全限制。兩個欄位皆保留，僅執行及驗證目前輸出模式所選的值。

每個通道依序：確認 SMU OUTPUT OFF → 切換 routing → 判斷極性 → 確認 OUTPUT OFF 及白光 OFF → 套用極性 → 以定位條件點亮 EL → 穩定等待／讀回 → 等待新相機影像 → 開放框選。極性量測可能在前置階段使用白光；此時禁止框選。真正框選期間白光必須保持 OFF，Relay service 同時阻擋白光群組與個別白光通道的 ON 命令。停用極性確認時使用基本資料指定的正向極性；無法可靠確認極性時不點亮 EL。

按確認後先關閉並核對輸出，再準備下一個通道。新通道未完成上述流程或沒有新的影像時，不接受舊影像／舊 ROI。最後確認、取消、斷線、相機錯誤、解析度變更或 Emergency 都先清理硬體；SMU OUTPUT OFF、routing OFF、白光 OFF、ownership release 任一未確認，均禁止正式量測。背景 worker 持續檢查白光狀態、SMU Compliance 與全域單次輸出／流程時間上限，避免視窗等待期間無限制通電。

定位預覽使用全圖 SDK continuous AE、20% 目標，暫時擴大到硬體及原生 SDK 允許的最多 5 s，Gain 保留原有 AE 範圍。這只用於定位，並不把未收斂預覽視為正式 AE 成功。定位結束恢復原範圍、ROI、手動曝光與 Gain；正式 Recipe 仍依各 Channel ROI 執行自己的 AE 或手動拍攝。定位不產生正式影像／EL 資料列。

選框採原始 image-pixel `(x, y, width, height)`；縮放與平移只影響顯示。不可變 snapshot 的 `camera.ROISelection` 保存定位條件、面積、極性結果、實際電流／電壓及清理結果。已在本次定位完成的極性結果會傳給正式 runner 保存及使用，避免框選後再次開啟白光重做極性量測。

## 正式量測

- 各 ROI 存在不可變 measurement snapshot 的 `camera.ChannelROIs`，納入 SHA-256。
- 進入各 channel 前，worker 經 CameraCaptureBridge 在相機 Qt owner thread 呼叫 public `set_auto_exposure_roi()`，必須通過 SDK write/readback 驗證。
- 該 channel 所有電氣條件、Stop 與 Repeat 都使用相同測光範圍。ROI 驗證失敗不繼續輸出或 AE。
- 拍攝仍取得完整 scientific frame；儲存前才以 `scientific[y:y+h, x:x+w]` 擷取像素。若實際 frame 尺寸與選框時的來源解析度不一致，拒絕儲存並安全停止。
- 原有 Live View 使用完整影像。正式量測結束後，測光範圍恢復為原本 Live View ROI；沒有設定時恢復全圖。

## 檔案與 Dark

TIFF 儲存 ROI 原始 uint16 container 值，不進行位移、縮放、插值或加入註記。PNG／JPG 仍依既有 Effective DN 規則產生顯示副本，但來源改為同一個 ROI。單色 Footer JPG 是 ROI 顯示副本加上右側白底直式灰階 colorbar 與下方灰底頁尾。

Shared Dark 維持每個 Gain／曝光／Repeat 一次實體拍攝，從同一 frame 分別裁切各 channel 的 ROI，儲存於 `DARK/CHn/`。因此實體拍攝計數與預估規則不變，Dark 輸出檔數會乘以啟用 channel 數。不同 ROI 尺寸時仍可正確配對。

每張 JSON 與 measurement manifest 增加 `ROIId`、`ChannelROI`、`SourceImageWidth`、`SourceImageHeight`。`ImageWidth`／`ImageHeight`、`ScientificShape` 與 `RawImageWidth`／`RawImageHeight` 表示裁切後像素尺寸；相機 `Resolution` 保留來源解析度。Dark 的 `ApplicableChannels` 只有對應 channel，`DarkScope=CHANNEL_ROI`。

Pixel CSV 仍在 verified safe shutdown 後從裁切 TIFF 產生；RAW、DarkCorrected、ExposureNormalized 都只含 ROI 像素。配對除 Gain／曝光／Repeat／解析度／尺寸外，還必須比對 channel 與完整 ROI 座標，避免同尺寸不同位置誤配。CSV 的 X／Y 為 ROI 內的局部座標，原圖位置可用 JSON `ChannelROI` 的 x／y 還原。

## Footer 排版

colorbar 位於原圖右側的新增白色畫布，上方最大值／白色，下方 0／黑色，標示數值與 `Linear`。已知 RAW alignment 使用 `Effective DN` 與實際 sensor bit depth 的完整範圍，例如 12-bit 為 0～4095；不依每張影像最大值拉伸。alignment 未知時，沿用顯示副本的 0～65535 container 映射，明確標為 `Container DN`。刻度與影像採相同的線性 8-bit 灰階換算；JPEG 有量化與壓縮，精確數值仍以 TIFF／CSV 為準。既有 RGB 相容輸出不加單一灰階圖例。

完整 ROI 保持在輸出左上角 `(0, 0)`，不覆蓋、不裁切、不縮放、不插值。色階圖例太高時，只增加 ROI 下方留白。頁尾排在影像／圖例區的下方，寬度使用新增色階區後的畫布寬度，footer 高度上限仍為 ROI 高度的 30%（最小預算 32 px）。窄長、寬扁及極小 ROI 無法容納完整資訊時，只有顯示副本縮略文字，完整資訊仍保留於 JSON。

逐張 JSON 與 measurement manifest 的 `FooterColorbar` 記錄位置、灰階映射、線性範圍、量的名稱、刻度與原圖／色階條座標；未輸出 Footer JPG 或來源為 RGB 時為 null。`RawImageWidth`／`RawImageHeight` 仍是 ROI 原尺寸，`AnnotatedJpegWidth`／`AnnotatedJpegHeight` 為含圖例及頁尾的輸出尺寸。Dark 與 EL 使用相同規則。一般 PNG／JPG 與 RAW TIFF 不加色階條。

## 驗證

`tests/test_recipe_channel_roi.py` 涵蓋啟用 1～4 channel、非連續 channel、取消／錯誤／斷線／解析度變更、白光與 SMU 清理失敗、Qt owner thread ROI 設定、AE 切換、各格式裁切、Shared Dark 像素配對與 footer 尺寸／像素完整性。實際白光、RisingCam AE 收斂與實體量測仍需硬體驗收。

EL 定位回歸：`tests/test_recipe_roi_excitation.py` 包含面積／電流換算、定電壓、正負極性、極性失敗、白光或 Compliance 異常、取消、Emergency、逾時、實際 Qt dialog 與背景 thread 的通道切換、影格門檻、Recipe 保存及 UI 切換。`tests/test_relay.py` 驗證白光 inhibit 及硬體讀回；實體 EL 可見度、實際接線及收斂仍需設備驗收。

2026-11-04 軟體驗證：本次新增 23／23 測試通過；完整 `python -m unittest discover -s tests -v` 846 項中 845 通過，唯一失敗為既有光源工具 `test_cancelling_lux_measurement_turns_off_light_through_worker` worker 等待逾時。編譯檢查與 `git diff --check` 通過。已檢視離線渲染的 CH2／ROI2 視窗，以及 640×480、160×900、900×80、160×160 的 footer 圖片。

同日推送前重新驗證：相關回歸 **179／179**、完整套件 **846／846 通過**（0 failed、0 errors、0 skipped），編譯與差異檢查通過。上述光源取消測試未修改，單獨及完整重跑均通過；前述 845／846 為較早驗證紀錄。

同日新增右側灰階 colorbar：`tests/test_image_colorbar.py` 新增 **8／8** 通過，涵蓋 8/10/12/14/16-bit 數值域、RAW 左右對齊、unknown container fallback、Dark／EL、原圖像素保留、極小／窄長／寬扁 ROI、PNG／JPG／TIFF 邊界、RGB 相容與跨影像固定範圍。相關回歸 **114／114**、完整套件 **854／854 通過**（0 failures、0 errors、0 skipped），編譯與差異檢查通過；已檢視 640×480、160×900、900×80、2×2 的實際函式 synthetic 輸出。硬體驗收待完成。
