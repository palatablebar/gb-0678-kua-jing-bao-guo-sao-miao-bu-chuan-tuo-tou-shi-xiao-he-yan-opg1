import csv
import io
import json

from app.reasons import sources

HEADER = ["run_id", "input_sha256", "rule_version", "kind", "source_lines", "reason", "evidence", "version", "parcel"]


def _cell(run, kind, parcel, lines, reason, evidence):
    meta = run["manifest"]
    return [
        run["run_id"],
        meta["input_sha256"],
        meta["rule_version"],
        kind,
        json.dumps(lines),
        reason,
        json.dumps(evidence, ensure_ascii=False),
        run.get("version", 1),
        parcel,
    ]


def build_archive(run):
    """唯一证据导出。

    conclusion 区与页面同读 run["conclusions"]，不使用任何二次推导结论。
    clock 区逐票列出仓库收件与承运商揽收两段原始记录及未采用原因。
    scan / quarantine / excluded 区保留全部原始扫描行，补传不会覆盖或删除旧扫描。
    """
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(HEADER)

    conclusions = run.get("conclusions")
    if conclusions is None:
        from app.clock import settle_run
        conclusions, totals = settle_run(run["stages"], run["run_id"])
        run = {**run, "conclusions": conclusions, "settlement": totals}
    for row in conclusions:
        lines = [row.get("promise_start_scan_id")] if row.get("promise_start_scan_id") else []
        writer.writerow(_cell(run, "conclusion", row.get("parcel"), lines, row.get("promise_start_reason", ""), row))

    for row in conclusions:
        for record in row.get("clock_records", []):
            if record.get("adopted"):
                reason = "采纳为此票唯一正式起算" if record.get("basis") == "PICKUP" else "采纳为暂算起算（待揽收补传后转正式）"
            else:
                reason = record.get("reason", "")
            writer.writerow(_cell(run, "clock", row.get("parcel"), record.get("source_lines") or [], reason, record))

    for row in run["stages"][0].get("rows", []):
        writer.writerow(_cell(run, "scan", row.get("parcel"), sources(row), "原始扫描采纳", row))

    for row in run["stages"][-1].get("cumulative_quarantine") or []:
        writer.writerow(_cell(run, "quarantine", row.get("parcel"), sources(row), row.get("reason", ""), row))

    for row in run["stages"][-1].get("cumulative_excluded") or []:
        writer.writerow(_cell(run, "excluded", row.get("parcel"), sources(row), row.get("reason", ""), row))

    writer.writerow(_cell(run, "settlement", "", [], "settlement", run.get("settlement") or {}))
    return "﻿" + stream.getvalue()
