import hashlib,json
from decimal import Decimal
from app.errors import DomainError
from app.reasons import sources
def evaluate(rows,context):
    stages=[v for v in context.values() if isinstance(v,dict) and "metrics" in v]
    balances=[s["metrics"]["balanced"] for s in stages if "balanced" in s["metrics"]]
    if balances and not all(balances): raise DomainError("UNBALANCED","来源行未对平，不能归档")
    ids=[str(r.get("parcel",r.get("_line",""))) for r in rows]
    if len(ids)!=len(set(ids)): raise DomainError("ARCHIVE_DUPLICATE","归档业务键重复")
    official=sum(str(r.get("clock_status",r.get("conclusion_status","正式")))=="正式" for r in rows)
    provisional=sum(str(r.get("clock_status",r.get("conclusion_status","正式")))=="暂算" for r in rows)
    conclusions=[r for r in rows if r.get("parcel") is not None]
    encoded=json.dumps(rows,ensure_ascii=False,sort_keys=True,default=str).encode()
    return {"rows":rows,"quarantine":[],"metrics":{"records":len(rows),"conclusions":len(conclusions),"unique_parcels":len(set(str(r.get("parcel")) for r in conclusions)),"official":official,"provisional":provisional,"source_lines":len(set(x for row in rows for x in sources(row))),"sha256":hashlib.sha256(encoded).hexdigest(),"ready":True,"differences":sum(r.get("status")=="差异" for r in rows),"compensation_total":str(sum((Decimal(str(r.get("expected") or "0")) for r in conclusions),Decimal(0)))}}
