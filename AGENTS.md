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

python -m unittest discover -s tests

只有全部必要測試通過，才可以進入備份與 GitHub 更新流程。

如果測試失敗：
- 不 commit
- 不 push
- 保留目前修改
- 回報失敗原因

## Push 前強制備份 GitHub 舊版本

任何 commit 或 push 前，先執行：

powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\backup_before_push.ps1"

備份腳本必須：

1. git fetch origin main
2. 從最新 origin/main 建立 ZIP
3. 儲存到：

backup\backup_YYYYMMDDHHMM.zip

4. 備份來源必須是 origin/main
5. 不得把本機尚未 push 的修改混入 ZIP
6. ZIP 檔案大小必須 > 0

如果備份失敗：
- 不 commit
- 不 push
- 停止流程並回報

## 備份成功後自動更新 GitHub

依序執行：

git status
git diff --stat
git add -A
git status

再次確認 staged files 都與本次任務相關。

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

git status
git log -1 --oneline

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

## 使用者當次指示優先

如果使用者明確說：
- 這次不要 push
- 只修改不要 commit
- 不要備份
- 不要上傳 GitHub

則以當次使用者指示為準。
