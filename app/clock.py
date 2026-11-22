"""正式承诺起算裁决。

业务裁决：承运商揽收（PICKUP）是正式承诺起算点；仓库收件（ACCEPT）只作为
受理/客服答复记录，不作为正式计时依据。缺少揽收扫描时，暂以仓库收件起算，
结论明确标记为“暂算”，揽收补传后按事件发生时刻重算。这样每票在任一批次中
只有一个起算点，避免同时出现两套达标结论与赔款。
"""

from decimal import Decimal

RECEIPT_NODE = "ACCEPT"
PICKUP_NODE = "PICKUP"
OFFICIAL_START_NODE = PICKUP_NODE

BASIS_LABELS = {
    "PICKUP": "承运商揽收",
    "RECEIPT_FALLBACK": "仓库收件（暂算）",
}

POLICY = {
    "official_start": OFFICIAL_START_NODE,
    "official_start_label": BASIS_LABELS["PICKUP"],
    "fallback_start": RECEIPT_NODE,
    "fallback_label": BASIS_LABELS["RECEIPT_FALLBACK"],
    "fallback_condition": "缺少承运商揽收扫描时暂算，补传后按事件发生时刻重算",
    "late_upload_rule": "起算按事件发生时刻，不按上传时刻",
}

REASONS = {
    "PICKUP_SELECTED": "承运商揽收为正式承诺起算依据",
    "RECEIPT_SUPERSEDED": "已有承运商揽收，仓库收件不作为正式起算（仅作受理答复记录）",
    "RECEIPT_ADOPTED_FALLBACK": "未取得承运商揽收扫描，暂以仓库收件起算（非正式结论）",
    "DUPLICATE_RECEIPT": "重复收件记录，不改变首次收件时间",
    "DUPLICATE_PICKUP": "重复揽收记录，不改变首次揽收时间",
}


def _late_upload(event):
    """上传晚于事件超过 24 小时即视为补传晚到；仅用于展示，不改变起算。"""
    try:
        return float(event.get("upload_lag_hours") or 0) > 24
    except (TypeError, ValueError):
        return False


def _record(event, adopted, reason_code):
    node = event.get("node")
    basis = "PICKUP" if node == PICKUP_NODE else "RECEIPT"
    return {
        "basis": basis,
        "label": BASIS_LABELS["PICKUP"] if basis == "PICKUP" else "仓库收件",
        "scan_id": event.get("scan_id"),
        "event_at": event.get("event_utc"),
        "uploaded_at": event.get("received_utc"),
        "upload_lag_hours": event.get("upload_lag_hours"),
        "late_upload": _late_upload(event),
        "adopted": adopted,
        "reason_code": reason_code,
        "reason": REASONS[reason_code],
        "source_lines": event.get("_sources", [event.get("_line")] if event.get("_line") else []),
    }


def adjudicate(receipts, pickups):
    """为一票裁决唯一正式起算点。

    receipts/pickups 必须已按事件时刻升序排列。返回的 promise_start_* 字段是
    下游时效与赔付唯一可用的计时起点；clock_records 保留两段原始扫描及未采用原因。
    """
    if not receipts:
        raise ValueError("adjudicate requires an accepted receipt scan")
    receipt = receipts[0]
    pickup = pickups[0] if pickups else None
    chosen_is_pickup = pickup is not None
    records = []

    for index, event in enumerate(receipts):
        if chosen_is_pickup:
            code = "RECEIPT_SUPERSEDED" if index == 0 else "DUPLICATE_RECEIPT"
        else:
            code = "RECEIPT_ADOPTED_FALLBACK" if index == 0 else "DUPLICATE_RECEIPT"
        records.append(_record(event, (not chosen_is_pickup) and index == 0, code))

    for index, event in enumerate(pickups):
        code = "PICKUP_SELECTED" if index == 0 else "DUPLICATE_PICKUP"
        records.append(_record(event, index == 0, code))

    chosen = pickup or receipt
    basis = "PICKUP" if chosen_is_pickup else "RECEIPT_FALLBACK"
    return {
        "warehouse_received_at": receipt.get("event_utc"),
        "warehouse_received_scan_id": receipt.get("scan_id"),
        "pickup_at": pickup.get("event_utc") if pickup else None,
        "pickup_scan_id": pickup.get("scan_id") if pickup else None,
        "promise_start_at": chosen.get("event_utc"),
        "promise_start_scan_id": chosen.get("scan_id"),
        "promise_start_basis": basis,
        "promise_start_label": BASIS_LABELS[basis],
        "promise_start_uploaded_at": chosen.get("received_utc"),
        "promise_start_upload_lag_hours": chosen.get("upload_lag_hours"),
        "promise_start_late_upload": _late_upload(chosen),
        "promise_start_reason": REASONS["PICKUP_SELECTED" if chosen_is_pickup else "RECEIPT_ADOPTED_FALLBACK"],
        "conclusion_status": "正式" if chosen_is_pickup else "暂算",
        "provisional": not chosen_is_pickup,
        "clock_records": records,
        "not_adopted_records": [record for record in records if not record["adopted"]],
    }


def build_conclusions(rows, run_id):
    """把最终逐票行收敛为唯一结论台账；同一包裹出现两次即中止。"""
    from app.errors import DomainError

    conclusions = []
    seen = set()
    for row in rows:
        parcel = row.get("parcel")
        if parcel is None:
            continue
        if parcel in seen:
            raise DomainError("DUPLICATE_CONCLUSION", f"包裹 {parcel} 出现多份结论，拒绝归档")
        seen.add(parcel)
        provisional = bool(row.get("provisional", True))
        basis = row.get("promise_start_basis") or row.get("clock_basis")
        chosen_is_pickup = basis == "PICKUP"
        reason_code = "PICKUP_SELECTED" if chosen_is_pickup else "RECEIPT_ADOPTED_FALLBACK"
        conclusions.append({
            "conclusion_id": f"{run_id}:{parcel}",
            "parcel": parcel,
            "warehouse_received_at": row.get("warehouse_received_at"),
            "warehouse_received_scan_id": row.get("warehouse_received_scan_id"),
            "pickup_at": row.get("pickup_at"),
            "pickup_scan_id": row.get("pickup_scan_id"),
            "promise_start_at": row.get("promise_start_at") or row.get("clock_start") or row.get("accepted_at"),
            "promise_start_scan_id": row.get("promise_start_scan_id"),
            "promise_start_basis": basis,
            "promise_start_label": row.get("promise_start_label") or BASIS_LABELS.get(basis, "仓库收件（暂算）"),
            "promise_start_uploaded_at": row.get("promise_start_uploaded_at"),
            "promise_start_upload_lag_hours": row.get("promise_start_upload_lag_hours"),
            "promise_start_late_upload": row.get("promise_start_late_upload"),
            "promise_start_reason": REASONS[reason_code],
            "clock_status": row.get("conclusion_status") or row.get("clock_status") or ("暂算" if provisional else "正式"),
            "decided": True,
            "provisional": provisional,
            "delivered_at": row.get("delivered_at"),
            "working_hours": row.get("working_hours"),
            "promised_hours": row.get("promised_hours"),
            "late_hours": row.get("late_hours"),
            "sla": row.get("sla"),
            "expected": row.get("expected", "0.00"),
            "reported": row.get("reported", "0"),
            "difference": row.get("difference"),
            "reconciliation": row.get("status"),
            "compensation_status": "暂算" if provisional else "正式",
            "clock_records": row.get("clock_records", []),
            "not_adopted_records": row.get("not_adopted_records", []),
        })
    return conclusions


UNDECIDED_REASON = "该包裹没有可裁决的起算扫描（收件或揽收均被隔离），暂不产生时效结论与赔款"


def undecided_conclusions(parcels, conclusions, run_id):
    """为无法裁决的包裹补一条显式记录，保证每票在台账中恰好出现一次。"""
    decided = {c.get("parcel") for c in conclusions}
    extra = []
    for parcel in parcels:
        if parcel in decided:
            continue
        extra.append({
            "conclusion_id": f"{run_id}:{parcel}",
            "parcel": parcel,
            "warehouse_received_at": None,
            "warehouse_received_scan_id": None,
            "pickup_at": None,
            "pickup_scan_id": None,
            "promise_start_at": None,
            "promise_start_scan_id": None,
            "promise_start_basis": None,
            "promise_start_label": "未裁决",
            "promise_start_uploaded_at": None,
            "promise_start_upload_lag_hours": None,
            "promise_start_late_upload": False,
            "promise_start_reason": UNDECIDED_REASON,
            "clock_status": "未裁决",
            "decided": False,
            "provisional": True,
            "delivered_at": None,
            "working_hours": None,
            "promised_hours": None,
            "late_hours": None,
            "sla": "未裁决",
            "expected": "0.00",
            "reported": "0",
            "difference": None,
            "reconciliation": "未裁决",
            "compensation_status": "未裁决",
            "clock_records": [],
            "not_adopted_records": [],
        })
    return extra


def settle_run(stages, run_id):
    """由已算好的阶段结果生成唯一结论台账（含未裁决票）与汇总。

    已知包裹号取自各阶段结果与最终隔离清单，因此即使某票的全部扫描都被隔离，
    也会在台账中获得一条“未裁决”记录，而不是静默消失。
    """
    conclusions = build_conclusions(stages[5]["rows"], run_id)
    parcels = []
    sources = [stage.get("rows", []) for stage in stages]
    sources.append(stages[-1].get("cumulative_quarantine", []))
    for rows in sources:
        for row in rows:
            parcel = row.get("parcel")
            if parcel not in (None, "") and parcel not in parcels:
                parcels.append(parcel)
    conclusions = conclusions + undecided_conclusions(parcels, conclusions, run_id)
    return conclusions, settlement(conclusions)


def settlement(conclusions):
    decided = [c for c in conclusions if c.get("decided", True)]
    official = [c for c in decided if not c.get("provisional")]
    provisional = [c for c in decided if c.get("provisional")]
    def total(items):
        value = sum((Decimal(str(item.get("expected") or "0")) for item in items), Decimal(0))
        return str(value.quantize(Decimal("0.01")))
    def sla(items, value):
        return sum(item.get("sla") == value for item in items)

    return {
        "promise_count": len(conclusions),
        "conclusion_count": len(conclusions),
        "decided_count": len(decided),
        "undecided_count": len(conclusions) - len(decided),
        "official_count": len(official),
        "provisional_count": len(provisional),
        "late_conclusions": sla(conclusions, "超时"),
        "official_late": sla(official, "超时"),
        "provisional_late": sla(provisional, "超时"),
        "compensation_total": total(conclusions),
        "official_compensation": total(official),
        "provisional_compensation": total(provisional),
    }
