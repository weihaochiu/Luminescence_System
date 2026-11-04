# Recipe 各 Channel ROI

Recipe 正式量測前會開啟既有 Relay 白光，在獨立的 Live View 視窗依啟用的 CH1～CH4 逐一框選。CH1 固定使用 ROI1，依此類推；只啟用 CH2／CH4 時只需設定 ROI2／ROI4。每次開始量測重新選取，不寫入 Recipe 預設值。

選框採原始 image-pixel `(x, y, width, height)`；縮放與平移只影響顯示。按確認後進入下一個啟用 channel，最後一次確認後先驗證白光 OFF，再進行正式量測。此流程適用手動曝光與自動曝光 Recipe；手動模式仍依指定曝光／Gain 拍攝。

框選期間 SMU OUTPUT 與所有 SMU routing 必須確認 OFF，保留 Recipe ownership 並鎖定主視窗量測控制。白光預覽暫時使用全圖 SDK continuous AE；完成或取消時停用預覽 AE、恢復先前的手動曝光／Gain 與 Live View 測光範圍。相機錯誤、斷線、影格逾時、解析度變更或 Emergency 會取消準備；白光 OFF 無法確認時禁止正式量測。白光、相機及 SMU 清理分別執行，單項清理失敗不跳過其他清理。

## 正式量測

- 各 ROI 存在不可變 measurement snapshot 的 `camera.ChannelROIs`，納入 SHA-256。
- 進入各 channel 前，worker 經 CameraCaptureBridge 在相機 Qt owner thread 呼叫 public `set_auto_exposure_roi()`，必須通過 SDK write/readback 驗證。
- 該 channel 所有電氣條件、Stop 與 Repeat 都使用相同測光範圍。ROI 驗證失敗不繼續輸出或 AE。
- 拍攝仍取得完整 scientific frame；儲存前才以 `scientific[y:y+h, x:x+w]` 擷取像素。若實際 frame 尺寸與選框時的來源解析度不一致，拒絕儲存並安全停止。
- 原有 Live View 使用完整影像。正式量測結束後，測光範圍恢復為原本 Live View ROI；沒有設定時恢復全圖。

## 檔案與 Dark

TIFF 儲存 ROI 原始 uint16 container 值，不進行位移、縮放、插值或加入註記。PNG／JPG 仍依既有 Effective DN 規則產生顯示副本，但來源改為同一個 ROI。Footer JPG 是 ROI 顯示副本加上下方灰底頁尾。

Shared Dark 維持每個 Gain／曝光／Repeat 一次實體拍攝，從同一 frame 分別裁切各 channel 的 ROI，儲存於 `DARK/CHn/`。因此實體拍攝計數與預估規則不變，Dark 輸出檔數會乘以啟用 channel 數。不同 ROI 尺寸時仍可正確配對。

每張 JSON 與 measurement manifest 增加 `ROIId`、`ChannelROI`、`SourceImageWidth`、`SourceImageHeight`。`ImageWidth`／`ImageHeight`、`ScientificShape` 與 `RawImageWidth`／`RawImageHeight` 表示裁切後像素尺寸；相機 `Resolution` 保留來源解析度。Dark 的 `ApplicableChannels` 只有對應 channel，`DarkScope=CHANNEL_ROI`。

Pixel CSV 仍在 verified safe shutdown 後從裁切 TIFF 產生；RAW、DarkCorrected、ExposureNormalized 都只含 ROI 像素。配對除 Gain／曝光／Repeat／解析度／尺寸外，還必須比對 channel 與完整 ROI 座標，避免同尺寸不同位置誤配。CSV 的 X／Y 為 ROI 內的局部座標，原圖位置可用 JSON `ChannelROI` 的 x／y 還原。

## Footer 排版

字級、留白與換行依裁切後寬高計算，寬度保持 ROI 原寬，footer 高度上限為 ROI 高度的 30%（最小預算 32 px）。文字只出現在額外下方區域，原有 ROI 像素不變、不放大、不拉伸。窄長、寬扁及極小 ROI 無法容納完整資訊時，只有顯示副本縮略文字，完整資訊仍保留於 JSON。

## 驗證

`tests/test_recipe_channel_roi.py` 涵蓋啟用 1～4 channel、非連續 channel、取消／錯誤／斷線／解析度變更、白光與 SMU 清理失敗、Qt owner thread ROI 設定、AE 切換、各格式裁切、Shared Dark 像素配對與 footer 尺寸／像素完整性。實際白光、RisingCam AE 收斂與實體量測仍需硬體驗收。

2026-11-04 軟體驗證：本次新增 23／23 測試通過；完整 `python -m unittest discover -s tests -v` 846 項中 845 通過，唯一失敗為既有光源工具 `test_cancelling_lux_measurement_turns_off_light_through_worker` worker 等待逾時。編譯檢查與 `git diff --check` 通過。已檢視離線渲染的 CH2／ROI2 視窗，以及 640×480、160×900、900×80、160×160 的 footer 圖片。

同日推送前重新驗證：相關回歸 **179／179**、完整套件 **846／846 通過**（0 failed、0 errors、0 skipped），編譯與差異檢查通過。上述光源取消測試未修改，單獨及完整重跑均通過；前述 845／846 為較早驗證紀錄。
