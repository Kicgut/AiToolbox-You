/**
 * Chinese label mappings for table headers and UI elements.
 */

export const FIELD_LABELS = {
    process_name: '应用',
    host: '目标主机',
    dest_port: '端口',
    network: '协议',
    direction: '方向',
    chain: '节点',
    rule: '规则',
    speed_up: '↑速度',
    speed_down: '↓速度',
    total_up: '↑总量',
    total_down: '↓总量',
    start_ts: '开始时间',
    upload_bytes: '上传',
    download_bytes: '下载',
    upload: '上传',
    download: '下载',
    total: '总量',
};

export function label(field) {
    return FIELD_LABELS[field] || field;
}