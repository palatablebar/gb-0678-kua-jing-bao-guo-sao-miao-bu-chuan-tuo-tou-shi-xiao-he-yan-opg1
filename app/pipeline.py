import base64
import csv
import hashlib
import io
import time
from app.config import ROOT,COLUMNS,MODULES
from app.errors import DomainError
from app.values import scalar
from app.manifest import digest,manifest
from app.clock import settle_run,POLICY
from app import store
from app.modules.m1_scans.rules import evaluate as stage1,decode
from app.modules.m2_nodes.rules import evaluate as stage2
from app.modules.m3_timezones.rules import evaluate as stage3
from app.modules.m4_paths.rules import evaluate as stage4
from app.modules.m5_timeliness.rules import evaluate as stage5
from app.modules.m6_compensation.rules import evaluate as stage6
from app.modules.m7_archives.rules import evaluate as stage7
STAGES=[stage1,stage2,stage3,stage4,stage5,stage6,stage7]
SAMPLES={"dirty.csv","clean.csv","legacy.csv","pickup.csv"}
def load_sample(name):
    if name not in SAMPLES: raise DomainError("BAD_SAMPLE","样例不存在",404)
    return (ROOT/"sample_data"/name).read_bytes()
def calculate(raw,params=None,stop=6,batch_id=None,original_raw=None):
    """按顺序执行各阶段。stop<6 时只计算到该阶段，供模块预览使用。"""
    params=params or {};started=time.monotonic();context={"parameters":params,"raw":raw,"quarantine":[],"excluded":[]};stages=[];rows=[]
    for index,stage in enumerate(STAGES[:stop+1]):
        result=stage(raw if index==0 else rows,context)
        result=scalar(result);rows=result["rows"]
        context["quarantine"].extend(result.get("quarantine",[]))
        context["excluded"].extend(result.get("excluded",[]))
        if index==0: context["intake"]=result["metrics"]
        result["cumulative_quarantine"]=list(context["quarantine"])
        result["cumulative_excluded"]=list(context["excluded"])
        context[MODULES[index][0]]=result
        stages.append(result)
    body={"run_id":batch_id or digest(raw,params)[:20],"stages":stages,"manifest":manifest(raw,params,started),"parameters":params,"source_csv_b64":base64.b64encode(raw).decode(),"original_csv_b64":base64.b64encode(original_raw if original_raw is not None else raw).decode()}
    body["manifest"]["original_sha256"]=hashlib.sha256(original_raw if original_raw is not None else raw).hexdigest()
    body["manifest"]["supplemented"]=bool(original_raw is not None and raw!=original_raw)
    if stop==6:
        conclusions,totals=settle_run(stages,body["run_id"])
        body["conclusions"]=conclusions
        body["settlement"]=totals
        body["policy"]=dict(POLICY)
    return body
def execute(raw,params=None):
    result=calculate(raw,params);return store.save(result["run_id"],result)
def _records(raw):
    """按 CSV 逻辑记录切分：引号内换行属于同一条记录，不按物理换行拆开。"""
    text,_=decode(raw)
    return [record for record in csv.reader(io.StringIO(text,newline="")) if record]
def _row_text(cells):
    out=io.StringIO(newline="")
    csv.writer(out).writerow(cells)
    return out.getvalue().rstrip("\r\n")
def _dedupe(current,extra):
    """以 scan_id 合并补传扫描。返回 (合并后字节, 是否变化)。

    与既有记录完全相同的行视为重复上传并忽略（即使原批次本身含冲突重复行也如此）；
    同 scan_id 却带不同取值则整体拒绝，旧版结论保持可读。
    """
    current_rows=_records(current);extra_rows=_records(extra)
    if not current_rows: raise DomainError("NO_SOURCE","批次缺少原始扫描，无法补传",409)
    header=current_rows[0]
    if header!=COLUMNS: raise DomainError("BAD_HEADER","批次原始表头已损坏",409)
    data=current_rows[1:]
    seen_rows={tuple(cells) for cells in data}
    keys={cells[0].strip() for cells in data}
    appended=[]
    for cells in extra_rows[1:] if extra_rows and extra_rows[0]==header else extra_rows:
        if cells==header: continue
        record=tuple(cells);key=cells[0].strip()
        if record in seen_rows: continue
        if key in keys:
            raise DomainError("SUPPLEMENT_CONFLICT",f"补传扫描号 {key} 与既有记录取值冲突，已保留旧版结论",409)
        seen_rows.add(record);keys.add(key);appended.append(cells)
    if not appended: return current,False
    extra_text="\n".join(_row_text(cells) for cells in appended)
    current_text,_=decode(current)
    return (current_text.rstrip("\r\n")+"\n"+extra_text+"\n").encode(),True
def validate_supplement(raw):
    """补传文件必须先整份校验；不合法则拒绝，既有结论保持不变。"""
    text,_=decode(raw)
    if not text.strip(): raise DomainError("EMPTY_SUPPLEMENT","补传文件为空")
    stream=csv.reader(io.StringIO(text,newline=""));header=next(stream,None)
    if header is not None and header!=COLUMNS: raise DomainError("BAD_HEADER","补传表头不匹配")
    data=0
    try:
        for cells in stream:
            if not cells or not any(c.strip() for c in cells): continue
            if cells==COLUMNS: continue
            if len(cells)!=len(COLUMNS): raise DomainError("BAD_COLUMNS","补传行列数不匹配")
            data+=1
    except csv.Error: raise DomainError("BAD_CSV","补传文件引号未闭合或已损坏")
    if data==0: raise DomainError("EMPTY_SUPPLEMENT","补传文件没有数据行")
def supplement(run_id,version,extra_raw):
    """把后到的揽收扫描补进同一票：按版本条件整体重算，失败保留旧结论。

    完全重复的补传直接返回当前批次：不新增版本、承诺或赔款。
    """
    run=store.get(run_id)
    if not isinstance(version,int) or isinstance(version,bool): raise DomainError("BAD_VERSION","补传需要当前版本号")
    current=base64.b64decode(run.get("source_csv_b64") or "")
    original=base64.b64decode(run.get("original_csv_b64") or "") or current
    if not current: raise DomainError("NO_SOURCE","批次缺少原始扫描，无法补传",409)
    if not isinstance(extra_raw,(bytes,bytearray)) or not bytes(extra_raw).strip(): raise DomainError("EMPTY_SUPPLEMENT","补传文件为空")
    validate_supplement(bytes(extra_raw))
    combined,changed=_dedupe(current,bytes(extra_raw))
    if not changed: return run
    result=calculate(combined,run.get("parameters",{}),batch_id=run_id,original_raw=original)
    return store.replace_conclusion(run_id,version,result)
def stage_preview(index,payload):
    if "rows" in payload and index>0:
        if not isinstance(payload["rows"],list) or any(not isinstance(row,dict) for row in payload["rows"]): raise DomainError("BAD_ROWS","记录需要对象列表")
        if not isinstance(payload.get("context",{}),dict): raise DomainError("BAD_CONTEXT","上下文需要对象")
        return scalar(STAGES[index](payload["rows"],payload.get("context",{"parameters":{},"quarantine":[]})))
    raw=payload.get("csv")
    raw=raw.encode() if isinstance(raw,str) else load_sample(payload.get("sample","dirty.csv"))
    return calculate(raw,payload.get("parameters",{}),index)["stages"][-1]
