# 獨立批次 HDR 觀看工具

從已拍攝的 EL 原始 MONO16 TIFF 生成觀看用 HDR；不連接硬體、不修改 Recipe。
**僅供觀看，不能用於 EL 定量亮度／像素強度比較。**

## 啟動與操作

1. 主程式工具列按「HDR 生成」，開啟獨立 process；或雙擊根目錄 `run_hdr_viewer.bat`、本資料夾 `run.bat`。
2. 「選取照片資料夾」可選整個量測批次或包含多批次的上層資料夾，自動掃描所有子資料夾。
3. 查看組別、曝光、原图數與狀態，預設勾選全部有效組。可改輸出位置及觀看 Gamma／亮度壓縮。
4. 按「生成所選 HDR」，背景處理並顯示進度、組別、已用時間、預估剩餘與完成時間。
   ETA 在讀取首張後依實際處理速度與剩餘像素工作量更新，包含融合／顯示／輸出估計，並非保證完成時間。
5. 完成後按「開啟結果資料夾」。取消／關閉會等待目前檔案操作結束，不中斷 TIFF 寫入；已完成組別保留。

使用專案 `.venv` 與既有 NumPy／tifffile／Pillow／PySide6，不自動安裝套件。
仍需保留在 repository 執行，尚非可單獨複製的 EXE。

```powershell
.\.venv\Scripts\python.exe -m standalone.hdr_viewer.main
```

## 分組與輸入

- 支援單頁 uint16 黑白 `.tif`／`.tiff`（大小寫均可）及同名 JSON。
- 優先 `MeasurementRunID`、`SampleID`、`Channel`、`SetCurrentDensityMaCm2`／`CommandedCurrentDensity`、Gain。
  不用實測 J 的微小變動拆組，也不將不同批次／樣品／通道／Gain 混合。
- JSON 缺少批次 ID 時，只在有 `measurement_snapshot.json` 或本專案日期時間＋UUID 格式的原量測資料夾內使用明確 folder fallback。
  資料夾身份以完整路徑記錄。無法辨識批次的散落照片會排除，不猜測拍攝時間間隔。
- 缺 JSON 時，可解析現有檔名 `N000001_Sample_CH1_J10_G100_E100_R1.tiff`。
  曝光單位沿用本專案 ms；此 fallback 只供觀看，明確記錄假設 16-bit/right-aligned container，不能當 sensor 校正。
- JSON 已存在但 RAW metadata 未知／矛盾時拒絕處理，不用照片最大值猜 bit depth。
- `RequestedExposureMs` 用於平均重複曝光的分桶；逐張依 `ExposureUsedUs`／actual exposure 等證據正規化，最後平均，避免微小實際曝光差造成 Repeat 被拆組。
- 至少兩種曝光；尺寸、bit depth、alignment 或明確 camera identity 不一致會標示不可生成。
- Dark、電壓模式、已有 HDR 衍生圖與帶輸出 marker 的資料夾不參與 EL 融合。損壞、矛盾或缺必要 metadata 的檔案列於輸入問題清單與整批 manifest。

第一版假設畫面、樣品與相機位置固定，沒有影像移動／變形補償。
在每個曝光條件平均 Repeat，將未校正 DN 依實際曝光換算為 DN/s，再以工程訊號範圍加權。
近飽和 Repeat 的像素不使用；所有曝光均太暗／飽和的像素記 NaN，觀看圖顯示黑色並另存有效遮罩。
缺校正時，此數值不可視為經驗證的輻射量或定量 EL 資料。

## 輸出

每次建立新的 `HDR_VIEW_OUTPUT_<timestamp>_<id>/`，不覆寫原始照片或舊結果。

```text
HDR_VIEW_OUTPUT_.../
  hdr_viewer_manifest.json         # viewing_only、quantitative=false、掃描問題及批次狀態
  batch_summary.csv               # 每組條件、成功／失敗及輸出資料夾
  0001_Sample_CH1_J10_G100/
    *_HDR_uncalibrated_float32.tiff
    *_HDR_view.tiff                # 16-bit，log compression + display gamma
    *_HDR_preview.png              # 8-bit 觀看副本
    *_HDR_valid_mask.png           # 255=有效，0=無可用曝光
    *_HDR.json                     # 輸入路徑／雜湊／metadata、演算法及觀看參數
```

每組預覽以自己的 99.8 percentile 正值設定白點，**不能依預覽亮度比較不同 J／樣品／批次**。
Gamma 與壓縮不修改浮點合成資料；無有效像素的整組會失敗，其他組仍繼續。
取消只保存完整組別；正在寫入的組別暫存清理，狀態仍記入 manifest。儲存故障顯示原因。
重新掃描會排除本工具輸出資料夾，避免把 HDR 再當原圖合成。

## 校正升級

`processing.Correction` 提供 `apply(signal, frame)`／`describe()`，校正處理在曝光正規化之前。
第一版固定 `NoCorrection`；沒有校正檔入口或定量模式。未來可以增加匹配 Dark、線性化、
Gain 及平場處理，沿用掃描／GUI／批次框架，但仍需另外驗證校正相容性與量化輸出。
請保留原始 TIFF、JSON 與對應 Dark；取得有效校正後重新生成，不能由觀看圖還原定量資料。

## 測試

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_hdr_viewer.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

自動測試使用 synthetic 圖像，涵蓋分組、曝光率、RAW alignment、飽和／無效遮罩、資料矛盾、
完整輸出、取消、背景 GUI、工具列獨立啟動與雙語。實際 EL 資料的視覺驗收需另行進行。
