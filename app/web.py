from flask import render_template
from app.config import MODULES,TITLE,SHORT
from app.pipeline import execute,load_sample
from app import store
def register_pages(app):
    def page(index):
        run=store.latest() or execute(load_sample("dirty.csv"))
        from app.clock import POLICY
        if run.get("conclusions") is None or run.get("settlement") is None:
            from app.clock import settle_run
            conclusions,totals=settle_run(run["stages"],run["run_id"])
            run={**run,"conclusions":conclusions,"settlement":totals}
        run.setdefault("policy",dict(POLICY))
        stage=run["stages"][index]
        rows=stage["rows"]
        columns=[['scan_id', 'parcel', 'node', 'event_time', 'received_time'], ['scan_id', 'parcel', 'node', 'destination', 'zone'], ['scan_id', 'parcel', 'event_utc', 'received_utc', 'upload_lag_hours'], ['parcel', 'warehouse_received_at', 'pickup_at', 'promise_start_at', 'promise_start_basis', 'conclusion_status', 'delivered_at', 'scan_count', 'path'], ['parcel', 'promise_start_at', 'promise_start_basis', 'conclusion_status', 'delivered_at', 'working_hours', 'promised_hours', 'late_hours', 'expected', 'sla'], ['parcel', 'expected', 'reported', 'difference', 'status', 'clock_status'], ['parcel', 'promise_start_at', 'conclusion_status', 'delivered_at', 'sla', 'expected', 'status']][index]
        labels={'scan_id': '扫描号', 'parcel': '包裹号', 'node': '节点', 'event_time': '发生时间', 'received_time': '上传时间', 'destination': '目的地', 'zone': '时区', 'event_utc': '发生 UTC', 'received_utc': '上传 UTC', 'upload_lag_hours': '补传时差 / h', 'accepted_at': '收件 UTC', 'warehouse_received_at': '仓库收件 UTC', 'warehouse_received_scan_id': '收件扫描号', 'pickup_at': '承运商揽收 UTC', 'pickup_scan_id': '揽收扫描号', 'promise_start_at': '正式起算 UTC', 'promise_start_scan_id': '起算扫描号', 'promise_start_basis': '起算依据', 'promise_start_label': '起算口径', 'conclusion_status': '结论状态', 'clock_status': '起算状态', 'provisional': '暂算', 'delivered_at': '妥投 UTC', 'delivery_uploaded_at': '妥投上传 UTC', 'scan_count': '扫描数', 'path': '节点路径', 'working_hours': '计时 / h', 'promised_hours': '承诺 / h', 'late_hours': '超时 / h', 'expected': '赔付 / 元', 'sla': '时效结论', 'reported': '申报 / 元', 'difference': '差额 / 元', 'status': '对账结论', 'accepted': '采纳扫描', 'late_uploads': '迟到上传', 'parcels': '包裹数', 'late_parcels': '超时包裹', 'compensation': '赔付合计', 'delivered': '妥投数', 'path_errors': '路径异常', 'official_start': '正式起算票数', 'provisional_start': '暂算票数', 'official_count': '正式结论', 'provisional_count': '暂算结论', 'undecided_count': '未裁决', 'decided_count': '已裁决', 'official_compensation': '正式赔付', 'provisional_compensation': '暂算赔付', 'compensation_total': '赔付合计', 'late_conclusions': '超时票数', 'records': '归档数', 'conclusions': '结论数', 'unique_parcels': '包裹数', 'official': '正式', 'provisional': '暂算', 'source_lines': '源行数', 'sha256': '摘要', 'ready': '可归档', 'differences': '差异数', 'excluded_inputs': '排除行'}
        for key,label in {'accepted_inputs': '采纳来源行', 'quarantine_inputs': '隔离来源行', 'output_records': '结果记录', 'input': '输入行', 'excluded': '排除行', 'balanced': '行数平衡', 'expected_total': '预期合计', 'reported_total': '申报合计', 'differences': '差异项', 'blank': '空行', 'repeated_headers': '分段表头', 'encoding': '编码', 'duplicate': '重复行', 'quarantine': '隔离行', 'accepted': '采纳行', 'sha256': '校验摘要', 'ready': '可归档'}.items(): labels.setdefault(key,label)
        return render_template(f"m{index+1}.html",title=TITLE,short=SHORT,modules=MODULES,index=index,run=run,stage=stage,rows=rows,columns=columns[:12],history=store.history(),labels=labels)
    app.add_url_rule("/",view_func=lambda:page(4))
    for index,(slug,name) in enumerate(MODULES):
        app.add_url_rule("/"+slug,endpoint="page_"+slug,view_func=lambda index=index:page(index))
