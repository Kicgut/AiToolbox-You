import { ref, onMounted } from '../../vendor/vue.esm-browser.prod.js';
import { formatBytes, formatTimestamp } from '../utils/format.js';
import { label } from '../utils/labels.js';

export default {
    name: 'TopTable',
    emits: ['drilldown'],
    setup(props, { emit }) {
        const dimension = ref('app');
        const range = ref('1h');
        const direction = ref('');
        const sort = ref('total');
        const data = ref([]);
        const loading = ref(false);

        const dimensionOptions = [
            { value: 'app', label: '应用' },
            { value: 'connection', label: '连接' },
            { value: 'chain', label: '节点' },
            { value: 'host', label: '目标主机' }
        ];

        const rangeOptions = [
            { value: '1h', label: '近1小时' },
            { value: 'today', label: '今天' },
            { value: '7d', label: '近7天' },
            { value: '30d', label: '近30天' }
        ];

        const directionOptions = [
            { value: '', label: '全部' },
            { value: 'proxy', label: '仅代理' },
            { value: 'direct', label: '仅直连' }
        ];

        const sortOptions = [
            { value: 'total', label: '总量' },
            { value: 'upload', label: '上传' },
            { value: 'download', label: '下载' }
        ];

        async function fetchData() {
            loading.value = true;
            try {
                const params = new URLSearchParams({
                    dimension: dimension.value,
                    range: range.value,
                    sort: sort.value,
                    limit: 20
                });
                if (direction.value) params.set('direction', direction.value);
                const res = await fetch(`/api/top?${params.toString()}`);
                const json = await res.json();
                data.value = json.data || [];
            } catch (e) {
                console.error('Failed to fetch top:', e);
            } finally {
                loading.value = false;
            }
        }

        function formatCell(field, value) {
            if (field === 'upload_bytes' || field === 'download_bytes') return formatBytes(value);
            if (field === 'start_ts' || field === 'last_seen_ts') return formatTimestamp(value);
            if (field === 'direction') return value === 'proxy' ? '代理' : '直连';
            return value;
        }

        function handleDrilldown(row) {
            if (row.process_name) emit('drilldown', { type: 'app', value: row.process_name, direction: row.direction });
            else if (row.host) emit('drilldown', { type: 'host', value: row.host, direction: row.direction });
        }

        function exportCSV() {
            const params = new URLSearchParams({
                kind: 'top',
                dimension: dimension.value,
                range: range.value,
                sort: sort.value,
                limit: 100
            });
            if (direction.value) params.set('direction', direction.value);
            window.open(`/api/export?${params.toString()}`, '_blank');
        }

        const headers = ref([]);

        async function fetchDataAndUpdateHeaders() {
            loading.value = true;
            try {
                const params = new URLSearchParams({
                    dimension: dimension.value,
                    range: range.value,
                    sort: sort.value,
                    limit: 20
                });
                if (direction.value) params.set('direction', direction.value);
                const res = await fetch(`/api/top?${params.toString()}`);
                const json = await res.json();
                data.value = json.data || [];
                if (data.value.length > 0) {
                    headers.value = Object.keys(data.value[0]);
                } else {
                    headers.value = [];
                }
            } catch (e) {
                console.error('Failed to fetch top:', e);
            } finally {
                loading.value = false;
            }
        }

        onMounted(() => fetchDataAndUpdateHeaders());

        return {
            dimension, range, direction, sort, data, loading, headers,
            dimensionOptions, rangeOptions, directionOptions, sortOptions,
            fetchData: fetchDataAndUpdateHeaders, formatCell, label, handleDrilldown, exportCSV
        };
    },
    template: `
        <div class="card">
            <div class="card-header">
                <h3>Top 排行</h3>
                <div class="controls">
                    <select v-model="dimension" @change="fetchData">
                        <option v-for="opt in dimensionOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                    </select>
                    <select v-model="range" @change="fetchData">
                        <option v-for="opt in rangeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                    </select>
                    <select v-model="direction" @change="fetchData">
                        <option v-for="opt in directionOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                    </select>
                    <select v-model="sort" @change="fetchData">
                        <option v-for="opt in sortOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                    </select>
                    <button class="btn" @click="exportCSV">导出 CSV</button>
                </div>
            </div>
            <div class="table-container">
                <div v-if="loading" class="loading-state">加载中…</div>
                <div v-else-if="data.length === 0" class="empty-state">暂无数据</div>
                <table v-else class="data-table">
                    <thead>
                        <tr>
                            <th v-for="h in headers" :key="h">{{ label(h) }}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="(row, i) in data" :key="i" @click="handleDrilldown(row)" class="clickable">
                            <td v-for="h in headers" :key="h">{{ formatCell(h, row[h]) }}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    `
};