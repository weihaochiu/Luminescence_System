# Luminescence_System — Codex 專案工作規則

本規則適用於整個 Luminescence_System repository。

## 基本規則

- 預設工作 branch 為 main。
- 不自動建立新的 branch。
- 不建立 Pull Request。
- 不使用 GitHub CLI（gh）。
- GitHub 更新只使用標準 Git 指令。
- 不修改與本次需求無關的檔案。
- 不使用 git push --force。
- 不自動執行 git reset --hard。
- 不刪除使用者既有未提交修改。

## 只有明確要求修改時才修改程式

若使用者只是要求：
- 分析
- 評估
- 規劃
- Review
- 找原因
- 說明架構

則：
- 不修改程式
- 不 commit
- 不 push

只有當使用者明確要求：
- 修改
- 修正
- 新增
- 實作
- 更新
- 重構
- Debug 並修復

才進入正式修改流程。

## 修改前

先執行：

git status

確認：
- repository 正確
- branch 為 main
- 沒有與本次任務無關的既有未提交修改

如果 branch 不是 main，或有來源不明的既有修改：
停止自動 commit / push 流程並回報使用者。

## 修改完成後測試

先執行本次修改相關測試。

之後執行完整測試：

python -m unittest discover -s tests -v

目前 repository layout 下，`python -m unittest discover -v` 可能找不到 tests，
因此不要將它作為正式驗證指令。

只有全部必要測試通過，才可以進入備份與 GitHub 更新流程。

如果測試失敗：
- 不 commit
- 不 push
- 保留目前修改
- 回報失敗原因

## Push 前強制備份 GitHub 舊版本

任何 commit 或 push 前，先執行：

git fetch origin main

fetch 成功後，必須先依「GitHub Backup 清理」規則檢查最新
origin/main 是否意外追蹤 backup/。確認遠端沒有 backup/ tracked files 後，
再執行：

powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\backup_before_push.ps1"

備份腳本必須：

1. git fetch origin main
2. 從最新 origin/main 建立 ZIP
3. 儲存到：

backup\backup_YYYYMMDDHHMM.zip

4. 備份來源必須是 origin/main
5. 不得把本機尚未 push 的修改混入 ZIP
6. ZIP 檔案大小必須 > 0
7. 只整理符合 backup_*.zip 的本機備份
8. 依 LastWriteTime 由新到舊排序，只保留最新 10 個
9. 不得刪除其他 ZIP、其他使用者檔案或 backup 資料夾本身
10. 輪替完成後 backup_*.zip 數量必須 <= 10

如果備份失敗：
- 不 commit
- 不 push
- 停止流程並回報

如果備份輪替失敗，也視為備份流程失敗：
- 不 commit
- 不 push
- 保留目前修改
- 回報錯誤

## GitHub Backup 清理

backup 資料夾只允許存在於本機：

backup\

其中所有符合以下規則的備份 ZIP：

backup\backup_*.zip

絕對不得存在於 GitHub repository 中。

每次準備更新 GitHub 時，在以下指令成功完成後：

git fetch origin main

執行：

git ls-tree -r --name-only origin/main -- backup/

如果沒有任何輸出，表示最新 origin/main 未追蹤 backup/，可正常繼續。

如果輸出包含 backup/、backup/*.zip 或 backup 下其他誤上傳檔案，
視為「Backup 誤上傳」。此時：

1. 不得刪除本機 backup 資料夾。
2. 不得刪除本機 backup ZIP。
3. 只移除 Git repository / GitHub 對 backup 的追蹤。
4. 確認 .gitignore 包含 backup/*.zip。
5. 只有在本機 Git 狀態安全、local main 可與 origin/main fast-forward 同步時，
   才可同步 origin/main，並執行：

   git rm -r --cached --ignore-unmatch backup

6. 再次確認本機 backup 資料夾與 ZIP 仍然存在。
7. 建立清理 commit，例如：

   git commit -m "Remove accidentally uploaded backup files"

8. 使用 git push origin main 推送清理 commit。
9. 清理完成後再次執行 git fetch origin main，並確認：

   git ls-tree -r --name-only origin/main -- backup/

   應無任何輸出。

如果出現以下任一狀況：
- 有來源不明的本機未提交修改
- local main 與 origin/main 發生 divergence
- 無法 fast-forward
- conflict
- 無法安全判斷哪些檔案應移除

則不得自動清理、不得 force push、不得 reset --hard、不得刪除本機 backup。
停止流程並回報使用者。

## 備份成功後自動更新 GitHub

依序執行：

git status
git diff --stat
git add <本次任務相關檔案>
git status

再次確認 staged files 都與本次任務相關，且 backup/ 未被 staged。

然後：

git commit -m "<依本次修改內容自動產生簡潔 commit message>"
git push origin main

禁止：
- force push
- 建立 branch
- 建立 PR
- 使用 gh

如果 push 被拒絕、origin/main 已有新版本、出現 conflict、
需要 merge/rebase 或任何遠端同步異常：
停止並回報，不自行覆蓋遠端。

## Push 後確認

執行：

git fetch origin main
git ls-tree -r --name-only origin/main -- backup/
git status
git log -1 --oneline

git ls-tree 應無任何輸出；若發現 backup/ tracked files，依「GitHub Backup 清理」
規則處理或停止並回報。

最後回報：
- 修改摘要
- 測試結果
- 測試通過數量
- 修改檔案數
- Backup ZIP 路徑
- Backup ZIP 大小
- Commit message
- Commit SHA
- Push 是否成功
- 最終 git status

## Backup 規則

backup/*.zip 不得加入 Git repository。

Push 前 ZIP 必須來自最新 origin/main，
不是目前本機修改版本。

本機 backup 資料夾只保留最近 10 個 backup_*.zip。
不得刪除不符合 backup_*.zip 的 ZIP、其他使用者檔案或 backup 資料夾本身。

## 完整程式修改流程

使用者要求修改
↓
git status
↓
確認 main
↓
修改程式
↓
相關測試
↓
完整測試
↓
測試全部通過
↓
git fetch origin main
↓
檢查 GitHub 是否意外存在 backup/
↓
如果存在，安全移除 GitHub 上的 backup，但保留本機 backup
↓
建立最新 origin/main 的 ZIP 備份
↓
驗證 ZIP
↓
整理 backup 資料夾
↓
只保留最近 10 個 backup_*.zip
↓
git diff / git status
↓
git add
↓
commit
↓
git push origin main
↓
再次確認 GitHub 沒有 backup/
↓
git status
↓
回報結果

## 使用者當次指示優先

如果使用者明確說：
- 這次不要 push
- 只修改不要 commit
- 不要備份
- 不要上傳 GitHub

則以當次使用者指示為準。
