import { ref, computed } from '../vendor/vue.esm-browser.prod.js';
import { formatBytes, formatSpeed, formatDuration, formatTimestamp } from '../utils/format.js';
import { label } from '../utils/labels.js';

export default {
    name: 'LiveTable',
    props: {
        liveData: { type: Array, default: () => [] },
        disconnectedBuffer: { type: Array, default: () => [] },
        directionFilter: { type: String, default: '' }
    },
    setup(props) {
        const sortKey = ref('start_ts');
        const sortAsc = ref(false);

        const filteredData = computed(() => {
            let data = props.liveData;
            if (props.directionFilter) {
                data = data.filter(c => c.direction === props.directionFilter);
            }
            data = [...data].sort((a, b) => {
                const va = a[sortKey.value];
                const vb = b[sortKey.value];
                if (va < vb) return sortAsc.value ? -1 : 1;
                if (va > vb) return sortAsc.value ? 1 : -1;
                return 0;
            });
            return data;
        });

        const filteredDisconnected = computed(() => {
            let data = props.disconnectedBuffer;
            if (props.directionFilter) {
                data = data.filter(c => c.direction === props.directionFilter);
            }
            return data;
        });

        const headers = ['process_name', 'host', 'dest_port', 'network', 'direction', 'chain', 'rule', 'speed_up', 'speed_down', 'total_up', 'total_down', 'start_ts'];

        function toggleSort(key) {
            if (sortKey.value === key) {
                sortAsc.value = !sortAsc.value;
            } else {
                sortKey.value = key;
                sortAsc.value = true;
            }
        }

        function formatCell(field, value) {
            if (field === 'speed_up' || field === 'speed_down') return formatSpeed(value);
            if (field === 'total_up' || field === 'total_down') return formatBytes(value);
            if (field === 'start_ts') {
                const now = Math.floor(Date.now() / 1000);
                return formatDuration(now - value) + ' 前';
            }
            if (field === 'direction') return value === 'proxy' ? '代理' : '直连';
            return value;
        }

        return { filteredData, filteredDisconnected, headers, sortKey, sortAsc, toggleSort, label, formatCell };
    },
    template: `
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th v-for="h in headers" :key="h" @click="toggleSort(h)" :class="{ active: sortKey === h }">
                            {{ label(h) }}
                            <span v-if="sortKey === h" class="sort-arrow">{{ sortAsc ? '▲' : '▼' }}</span>
                        </th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="c in filteredData" :key="c.id" :class="c.direction">
                        <td v-for="h in headers" :key="h">{{ formatCell(h, c[h]) }}</td>
                    </tr>
                    <tr v-for="c in filteredDisconnected" :key="'dc-' + c.id" class="disconnected" :class="c.direction">
                        <td v-for="h in headers" :key="h">{{ formatCell(h, c[h]) }}</td>
                    </tr>
                    <tr v-if="filteredData.length === 0 && filteredDisconnected.length === 0">
                        <td :colspan="headers.length" class="empty-state">暂无活跃连接</td>
                    </tr>
                </tbody>
            </table>
        </div>
    `
};
