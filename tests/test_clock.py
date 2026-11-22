import csv,io
import pytest
from app import store
from app.config import COLUMNS,ROOT
from app.clock import adjudicate,build_conclusions,settlement,POLICY
from app.errors import DomainError
from app.pipeline import calculate,execute,load_sample

from datetime import datetime
from app.values import instant
SUPPLEMENT=(ROOT/"sample_data"/"supplement_pickup.csv").read_bytes()
def ev(scan_id,node,event,received="2026-11-02T01:00:00Z"):
    lag=(instant(received)-instant(event)).total_seconds()/3600
    return {"scan_id":scan_id,"node":node,"event_utc":event,"received_utc":received,"upload_lag_hours":str(lag),"_sources":[int(scan_id[-1])]}

def test_policy_is_carrier_pickup():
    assert POLICY["official_start"]=="PICKUP" and POLICY["official_start_label"]=="承运商揽收"

def test_pickup_supersedes_warehouse_receipt():
    c=adjudicate([ev("100","ACCEPT","2026-11-02T00:00:00Z")],[ev("200","PICKUP","2026-11-02T12:00:00Z")])
    assert c["promise_start_basis"]=="PICKUP" and c["conclusion_status"]=="正式"
    assert c["warehouse_received_at"]=="2026-11-02T00:00:00Z" and c["promise_start_at"]=="2026-11-02T12:00:00Z"
    assert [r["reason_code"] for r in c["not_adopted_records"]]==["RECEIPT_SUPERSEDED"]

def test_late_pickup_upload_still_uses_event_time():
    "揽收补传晚到，起算仍按发生时刻，不按上传时刻"
    c=adjudicate([ev("101","ACCEPT","2026-11-02T00:00:00Z")],[ev("201","PICKUP","2026-11-02T12:00:00Z","2026-11-10T00:00:00Z")])
    assert c["promise_start_at"]=="2026-11-02T12:00:00Z"
    assert c["promise_start_late_upload"] is True

def test_missing_pickup_is_marked_provisional():
    c=adjudicate([ev("102","ACCEPT","2026-11-02T00:00:00Z")],[])
    assert c["promise_start_basis"]=="RECEIPT_FALLBACK" and c["conclusion_status"]=="暂算"
    assert c["not_adopted_records"]==[]

def test_duplicate_pickup_does_not_move_start():
    c=adjudicate([ev("103","ACCEPT","2026-11-02T00:00:00Z")],[ev("203","PICKUP","2026-11-02T12:00:00Z"),ev("204","PICKUP","2026-11-02T12:00:00Z")])
    assert c["promise_start_scan_id"]=="203"
    assert sorted(r["reason_code"] for r in c["not_adopted_records"])==["DUPLICATE_PICKUP","RECEIPT_SUPERSEDED"]

def test_one_conclusion_per_parcel():
    row={"parcel":"0001","expected":"1.00","provisional":False,"promise_start_basis":"PICKUP"}
    with pytest.raises(DomainError) as e:build_conclusions([row,row],"run")
    assert e.value.code=="DUPLICATE_CONCLUSION"

def test_pickup_sample_has_one_conclusion_per_parcel(result_pickup):
    parcels=[c["parcel"] for c in result_pickup["conclusions"]]
    assert len(parcels)==len(set(parcels))==4
    assert result_pickup["settlement"]==settlement(result_pickup["conclusions"])

def test_pickup_sample_official_vs_provisional(result_pickup):
    by={c["parcel"]:c for c in result_pickup["conclusions"]}
    assert by["0101"]["promise_start_basis"]=="PICKUP" and by["0101"]["clock_status"]=="正式"
    assert by["0102"]["promise_start_basis"]=="RECEIPT_FALLBACK" and by["0102"]["clock_status"]=="暂算"
    assert result_pickup["settlement"]["official_count"]==2 and result_pickup["settlement"]["provisional_count"]==2

def test_receipt_would_have_been_late_but_pickup_meets_sla(result_pickup):
    "0101 若按仓库收件 48h 会超时；按揽收 12h 达标"
    row=next(c for c in result_pickup["conclusions"] if c["parcel"]=="0101")
    assert row["sla"]=="达标" and row["expected"]=="0.00" and row["working_hours"]=="12.0"

def test_pickup_sample_report_kept(result_pickup):
    "两段记录全部保留；凡有揽收的票都写明仓库收件为何未采用"
    assert all(c["clock_records"] for c in result_pickup["conclusions"])
    with_pickup=[c for c in result_pickup["conclusions"] if c["promise_start_basis"]=="PICKUP"]
    assert with_pickup and all(c["not_adopted_records"] for c in with_pickup)
    assert all(any(r["basis"]=="RECEIPT" for r in c["clock_records"]) for c in result_pickup["conclusions"])

def test_duplicate_batch_retry_adds_no_promise_or_payout(sample):
    a=execute(load_sample("pickup.csv"));b=execute(load_sample("pickup.csv"))
    assert a["run_id"]==b["run_id"] and len(store.history())==1
    assert a["settlement"]==b["settlement"]

def test_supplement_recomputes_same_ticket_only(client):
    p=client.post("/api/runs",json={"sample":"pickup.csv"}).get_json();run_id=p["run_id"]
    extra=SUPPLEMENT
    r=client.post(f"/api/runs/{run_id}/scans",json={"csv":extra.decode(),"version":1});assert r.status_code==200
    after=r.get_json()
    assert after["version"]==2 and after["run_id"]==run_id
    by={c["parcel"]:c for c in after["conclusions"]}
    assert by["0102"]["promise_start_basis"]=="PICKUP" and by["0102"]["clock_status"]=="正式"
    assert by["0104"]["promise_start_basis"]=="PICKUP"
    assert by["0101"]["promise_start_at"]=="2026-11-02T12:00:00+00:00"
    assert after["settlement"]["provisional_count"]==0
    assert len(after["conclusions"])==4

def test_supplement_retry_is_idempotent(client):
    p=client.post("/api/runs",json={"sample":"pickup.csv"}).get_json();run_id=p["run_id"]
    extra=SUPPLEMENT.decode()
    first=client.post(f"/api/runs/{run_id}/scans",json={"csv":extra,"version":1}).get_json()
    second=client.post(f"/api/runs/{run_id}/scans",json={"csv":extra,"version":first["version"]}).get_json()
    assert second["version"]==first["version"] and second["settlement"]==first["settlement"]
    assert len(store.history())==1

def test_stale_supplement_keeps_newer_conclusion(client):
    p=client.post("/api/runs",json={"sample":"pickup.csv"}).get_json();run_id=p["run_id"]
    extra=SUPPLEMENT.decode()
    client.post(f"/api/runs/{run_id}/scans",json={"csv":extra,"version":1})
    newer=store.get(run_id)
    other=(COLUMNS and "scan_id,parcel,node,event_time,received_time,destination,promised_hours,declared_value,reported,note\n"
           "9901,0101,揽收,2026-11-02T06:00:00Z,2026-11-03T00:00:00Z,JP,12,200,0,冲突补传\n")
    r=client.post(f"/api/runs/{run_id}/scans",json={"csv":other,"version":1})
    assert r.status_code==409
    assert store.get(run_id)["settlement"]==newer["settlement"]

def test_failed_supplement_keeps_old_full_conclusion(client):
    p=client.post("/api/runs",json={"sample":"pickup.csv"}).get_json();run_id=p["run_id"]
    before=store.get(run_id)
    for body in ({"csv":"scan_id,parcel\n1,x"},{"csv":""},{"csv":"scan_id,parcel,node\n1,2,收件"}):
        r=client.post(f"/api/runs/{run_id}/scans",json={**body,"version":before["version"]})
        assert r.status_code==422
    after=store.get(run_id)
    assert after["version"]==before["version"] and after["conclusions"]==before["conclusions"]

def test_conflicting_supplement_rejected(client):
    p=client.post("/api/runs",json={"sample":"pickup.csv"}).get_json();run_id=p["run_id"]
    before=store.get(run_id)["settlement"]
    conflict=("scan_id,parcel,node,event_time,received_time,destination,promised_hours,declared_value,reported,note\n"
              "1102,0101,揽收,2026-11-02T06:00:00Z,2026-11-03T00:00:00Z,JP,12,200,0,冲突\n")
    r=client.post(f"/api/runs/{run_id}/scans",json={"csv":conflict,"version":before and 1})
    assert r.status_code==409 and r.get_json()["code"]=="SUPPLEMENT_CONFLICT"
    assert store.get(run_id)["settlement"]==before

def test_archive_reads_same_conclusions_and_keeps_raw_scans(client):
    p=client.post("/api/runs",json={"sample":"pickup.csv"}).get_json();run_id=p["run_id"]
    extra=SUPPLEMENT.decode()
    after=client.post(f"/api/runs/{run_id}/scans",json={"csv":extra,"version":1}).get_json()
    text=client.get(f"/api/runs/{run_id}/archive").data.decode("utf-8-sig")
    rows=list(csv.reader(io.StringIO(text)))
    header,body=rows[0],rows[1:]
    kinds=[row[3] for row in body]
    assert kinds.count("conclusion")==len(after["conclusions"])==4
    assert kinds.count("clock")>=8
    parcelled=[row[8] for row in body if row[3]=="conclusion"]
    assert sorted(parcelled)==sorted(c["parcel"] for c in after["conclusions"])
    conclusion_evidence=[row[6] for row in body if row[3]=="conclusion"]
    for c in after["conclusions"]:
        assert any(f'"conclusion_id": "{c["conclusion_id"]}"' in e for e in conclusion_evidence)
    scan_evidence=" ".join(row[6] for row in body if row[3]=="scan")
    assert '"1201"' in scan_evidence and '"1401"' in scan_evidence
    assert 'SUPPLEMENT_CONFLICT' not in text
    assert {row[7] for row in body}=={str(after["version"])}

def test_export_and_page_share_conclusion(client):
    p=client.post("/api/runs",json={"sample":"pickup.csv"}).get_json()
    page=client.get("/timeliness").data.decode()
    assert p["settlement"]["official_count"]==2
    assert "正式结论 2 票" in page and "暂算结论 2 票" in page

def test_pickup_before_receipt_isolated():
    "两段记录矛盾：揽收早于收件，该揽收行隔离，不出正式结论"
    from app.modules.m4_paths.rules import evaluate as paths
    def scan(i,node,at):
        return {"scan_id":str(i),"parcel":"01","node":node,"event_utc":at,"received_utc":"2026-11-02T01:00:00+00:00","zone":"Asia/Tokyo","destination":"JP","promised_hours":"24","declared_value":"200","reported":"0","_sources":[i]}
    r=paths([scan(1,"ACCEPT","2026-11-02T00:00:00+00:00"),scan(2,"PICKUP","2026-11-01T00:00:00+00:00"),scan(3,"DELIVERED","2026-11-04T00:00:00+00:00")],{})
    assert [q["reason"] for q in r["quarantine"]]==["PICKUP_BEFORE_RECEIPT"]
    assert r["rows"][0]["promise_start_basis"]=="RECEIPT_FALLBACK" and r["rows"][0]["provisional"] is True

def test_every_mapped_parcel_has_one_ledger_row(result):
    "无法裁决的包裹也要显式留一行，不静默消失"
    parcels=[str(r["parcel"]) for r in result["stages"][1]["rows"]]
    ledger=[c["parcel"] for c in result["conclusions"]]
    assert sorted(set(parcels))==sorted(ledger)
    assert len(ledger)==len(set(ledger))
    undecided=[c for c in result["conclusions"] if c["clock_status"]=="未裁决"]
    assert undecided and all(c["promise_start_reason"] for c in undecided)
    s=result["settlement"]
    assert s["official_count"]+s["provisional_count"]+s["undecided_count"]==s["promise_count"]

def test_undecided_parcel_has_no_payout(result):
    for c in result["conclusions"]:
        if c["clock_status"]=="未裁决":
            assert c["expected"]=="0.00" and c["provisional"] is True and c["decided"] is False

def test_supplement_requires_version(client):
    p=client.post("/api/runs",json={"sample":"pickup.csv"}).get_json();run_id=p["run_id"]
    assert client.post(f"/api/runs/{run_id}/scans",json={"csv":SUPPLEMENT.decode()}).status_code==422
    assert store.get(run_id)["version"]==1

def test_supplement_accepts_multipart(client):
    p=client.post("/api/runs",json={"sample":"pickup.csv"}).get_json();run_id=p["run_id"]
    r=client.post(f"/api/runs/{run_id}/scans",data={"version":"1","file":(io.BytesIO(SUPPLEMENT),"s.csv")},content_type="multipart/form-data")
    assert r.status_code==200 and r.get_json()["version"]==2
    assert r.get_json()["settlement"]["official_count"]==4

def test_manifest_records_original_and_supplement_flag(client):
    p=client.post("/api/runs",json={"sample":"pickup.csv"}).get_json()
    assert p["manifest"]["supplemented"] is False and len(p["manifest"]["original_sha256"])==64
    after=client.post(f"/api/runs/{p['run_id']}/scans",json={"csv":SUPPLEMENT.decode(),"version":1}).get_json()
    assert after["manifest"]["supplemented"] is True
    assert after["manifest"]["original_sha256"]==p["manifest"]["original_sha256"]
    assert after["manifest"]["input_sha256"]!=p["manifest"]["input_sha256"]

def test_export_lists_undecided_ticket(client):
    client.post("/api/runs",json={"sample":"dirty.csv"})
    run_id=store.latest()["run_id"]
    rows=list(csv.reader(io.StringIO(client.get(f"/api/runs/{run_id}/archive").data.decode("utf-8-sig"))))[1:]
    undecided=[r for r in rows if r[3]=="conclusion" and '"clock_status": "未裁决"' in r[6]]
    assert len(undecided)==1 and undecided[0][8]=="0009"
    assert "没有可裁决的起算扫描" in undecided[0][6]
