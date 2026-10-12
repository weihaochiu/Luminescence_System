# GSP-4H 光源／相機線性度測試 — 舊入口

程式實作已集中到 `standalone/light_linearity_tester/`。

請雙擊新資料夾的 `run.bat`，使用說明見：
`standalone/light_linearity_tester/README.md`。

原根目錄 `run_light_linearity_qualification.bat` 與
`python -m tools.light_linearity_qualification.main` 仍可使用，會啟動同一份新實作。
此目錄只保留相容轉接，不保存第二份測試邏輯。

新光強表與測試輸出位於新資料夾的 `data/`（已排除 Git）。
舊 `local/light_linearity/` 資料保留；新位置沒有光強表時會讀取舊表，保存至新位置。
