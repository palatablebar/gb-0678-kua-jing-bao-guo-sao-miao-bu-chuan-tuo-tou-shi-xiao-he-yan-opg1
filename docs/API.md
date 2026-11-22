# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离（cumulative_quarantine）与累计排除（cumulative_excluded）。/api/upload接收multipart文件file。

## 结论与证据

`GET /api/runs/<id>` 与 `GET /api/runs/<id>/archive` 使用同一份 `conclusions` 台账：每票一条，含 `promise_start_at`（唯一正式起算）、`promise_start_basis`（PICKUP/RECEIPT_FALLBACK）、`clock_status`（正式/暂算）、`clock_records`（仓库收件与承运商揽收两段原始记录）、`not_adopted_records`（未采用原因）。`settlement` 汇总票数与赔付，正式与暂算分列。导出CSV的 `kind` 列区分 `conclusion`、`clock`、`scan`、`quarantine`、`excluded`、`settlement`。

## 补传

`POST /api/runs/<id>/scans` 补传后到的揽收扫描，接收 multipart（file+version）或 JSON（csv+version）。

- 按事件发生时刻重算同一票，仅更新该批次，不新建批次；返回体版本号加一。
- 完全相同补传幂等：不升版本、不新增承诺或赔款。
- `version` 不是当前版本返回409 `STALE_VERSION`，新版本结论不被覆盖。
- 同 `scan_id` 不同取值返回409 `SUPPLEMENT_CONFLICT`；表头/列数/空文件返回422。以上失败均不修改既有结论，旧版完整结论保持可读。
- 原始扫描不删除：每次补传后的证据导出仍包含最初上传的全部原始扫描行（`kind=scan`）。
