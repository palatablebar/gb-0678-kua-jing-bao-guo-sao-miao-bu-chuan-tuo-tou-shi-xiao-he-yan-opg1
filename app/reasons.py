REASONS={"BAD_COLUMNS":"列数不匹配","EMPTY_VALUE":"必填值为空","INVALID_NUMBER":"数字格式错误","INVALID_TIME":"时间缺少偏移或格式错误","DUPLICATE_CONFLICT":"同键取值冲突","UNKNOWN_REFERENCE":"引用不存在","STALE_VERSION":"版本已更新","EMPTY_FILE":"文件为空","HEADER_ONLY":"仅有表头","BLANK_ONLY":"全部为空行","BLANK_ROW":"空白行，不参与计算","REPEATED_HEADER":"分段重复表头，不参与计算","DUPLICATE_IDENTICAL":"重复扫描，保留首条","SUPPLEMENT_CONFLICT":"补传与既有扫描取值冲突","PICKUP_BEFORE_RECEIPT":"揽收早于仓库收件","UNKNOWN_NODE":"扫描节点未登记","UNKNOWN_DESTINATION":"目的地未登记","EMPTY_PARCEL":"包裹号为空","PATH_REGRESSION":"扫描路径倒退","SIMULTANEOUS_CONFLICT":"同刻扫描节点冲突","MISSING_ACCEPT":"缺少收件扫描"}
def reject(row, code, detail):
    return {**row,"reason":code,"detail":detail}
def sources(row):
    return row.get("_sources", [row.get("_line",0)])
