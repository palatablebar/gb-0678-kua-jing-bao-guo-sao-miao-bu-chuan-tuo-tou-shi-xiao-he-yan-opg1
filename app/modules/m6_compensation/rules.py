from decimal import Decimal
from app.reasons import sources
from app.errors import DomainError
from app.clock import settlement
def evaluate(rows,context):
    intake=context.get("intake")
    bad=context.get("quarantine",[])
    excluded=context.get("excluded",[])
    accepted=set(x for row in rows for x in sources(row))
    rejected=set(x for row in bad for x in sources(row))
    skipped=set(x for row in excluded for x in sources(row))
    if accepted & rejected: raise DomainError("LINEAGE_OVERLAP","同一来源行被重复裁决")
    if accepted & skipped or rejected & skipped: raise DomainError("LINEAGE_OVERLAP","同一来源行被重复裁决")
    parcels=[str(row.get("parcel")) for row in rows]
    if len(parcels)!=len(set(parcels)): raise DomainError("DUPLICATE_CONCLUSION","同一包裹出现多份结论")
    m={"accepted_inputs":len(accepted),"quarantine_inputs":len(rejected),"output_records":len(rows),"excluded_inputs":len(skipped)}
    if intake:
        m.update(input=intake["input"],excluded=intake["duplicate"]+intake["blank"]+intake["repeated_headers"],balanced=intake["input"]==len(accepted)+len(rejected)+len(skipped))
    else:m.update(input=len(accepted)+len(rejected)+len(skipped),excluded=len(skipped),balanced=True)
    output=[]
    for row in rows:
        expected=Decimal(str(row.get("expected","0")));reported=Decimal(str(row.get("reported","0")))
        output.append({**row,"difference":str(expected-reported),"status":"通过" if expected==reported else "差异"})
    m.update(expected_total=str(sum((Decimal(str(r.get("expected","0"))) for r in rows),Decimal(0))),reported_total=str(sum((Decimal(str(r.get("reported","0"))) for r in rows),Decimal(0))),differences=sum(r["status"]=="差异" for r in output))
    m.update(settlement(output))
    return {"rows":output,"quarantine":[],"metrics":m}
