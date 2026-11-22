import hashlib,json,sqlite3
from pathlib import Path
from app.config import DATA_DIR
from app.errors import DomainError
SCHEMA="CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')"
def _db():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(SCHEMA)
    return db
def connect(): return _db()
def _decode(row):
    if not row: raise DomainError("NOT_FOUND","批次不存在",404)
    return {**json.loads(row[0]),"version":row[1],"decision":row[2]}
def save(run_id,payload):
    """同源重跑复用已有批次，不新增承诺或赔款。"""
    encoded=json.dumps(payload,ensure_ascii=False)
    with _db() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES (?,?)",(run_id,encoded))
        row=db.execute("SELECT payload,version,decision FROM runs WHERE id=?",(run_id,)).fetchone()
    return _decode(row)
def get(run_id):
    with _db() as db: row=db.execute("SELECT payload,version,decision FROM runs WHERE id=?",(run_id,)).fetchone()
    return _decode(row)
def latest():
    with _db() as db: row=db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return get(row[0]) if row else None
def history():
    with _db() as db: return [{"run_id":i,"version":v,"decision":d} for i,v,d in db.execute("SELECT id,version,decision FROM runs ORDER BY rowid DESC")]
def _stored_digest(payload):
    """结论指纹只取内容，不含生成时刻与耗时，保证同批重试判定为无变化。"""
    manifest={k:v for k,v in (payload.get("manifest") or {}).items() if k not in {"generated_at","elapsed_ms"}}
    stable={"stages":payload.get("stages"),"conclusions":payload.get("conclusions"),"settlement":payload.get("settlement"),"manifest":manifest,"parameters":payload.get("parameters")}
    return hashlib.sha256(json.dumps(stable,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def replace_conclusion(run_id,version,payload):
    """按版本条件整体替换结论。失败不触碰旧行，旧版完整结论保持可读。"""
    if not isinstance(version,int): raise DomainError("BAD_VERSION","请提供版本号")
    encoded=json.dumps(payload,ensure_ascii=False)
    with _db() as db:
        row=db.execute("SELECT payload FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row: raise DomainError("NOT_FOUND","批次不存在",404)
        current=json.loads(row[0])
        if _stored_digest(current)==_stored_digest(payload):
            return get(run_id)
        cursor=db.execute("UPDATE runs SET payload=?,version=version+1,decision='待复核' WHERE id=? AND version=?",(encoded,run_id,version))
        if cursor.rowcount!=1: raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
        updated=db.execute("SELECT payload,version,decision FROM runs WHERE id=?",(run_id,)).fetchone()
    return _decode(updated)
def review(run_id,version,decision):
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    with _db() as db:
        cursor=db.execute("UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?",(decision,run_id,version))
        if cursor.rowcount!=1:
            if not db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
            raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
    return get(run_id)
