/**
 * Byte size and time formatting utilities.
 */

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

export function formatBytes(bytes) {
    if (bytes == null || bytes === 0) return '0 B';
    const i = Math.floor(Math.log(Math.abs(bytes)) / Math.log(1024));
    const idx = Math.min(i, UNITS.length - 1);
    const val = bytes / Math.pow(1024, idx);
    return val.toFixed(idx === 0 ? 0 : 1) + ' ' + UNITS[idx];
}

export function formatSpeed(bytesPerSec) {
    if (bytesPerSec == null) return '0 B/s';
    return formatBytes(bytesPerSec) + '/s';
}

export function formatDuration(seconds) {
    if (seconds == null || seconds < 0) return '-';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}时${m}分${s}秒`;
    if (m > 0) return `${m}分${s}秒`;
    return `${s}秒`;
}

export function formatTimestamp(ts) {
    if (!ts) return '-';
    const d = new Date(ts * 1000);
    return d.toLocaleString('zh-CN', { hour12: false });
}