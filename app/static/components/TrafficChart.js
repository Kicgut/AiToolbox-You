import { ref, onMounted, onUnmounted, nextTick } from '../../vendor/vue.esm-browser.prod.js';
import { formatBytes } from '../utils/format.js';

export default {
    name: 'TrafficChart',
    setup() {
        const granularity = ref('hour');
        const loading = ref(true);
        const noData = ref(false);
        let chartInstance = null;
        let canvasRef = ref(null);

        const granularityOptions = [
            { value: 'hour', label: '小时' },
            { value: 'day', label: '天' },
            { value: 'week', label: '周' }
        ];

        async function fetchData() {
            loading.value = true;
            noData.value = false;
            try {
                const params = new URLSearchParams({ granularity: granularity.value });
                const res = await fetch(`/api/timeseries?${params.toString()}`);
                const data = await res.json();
                if (!data.buckets || data.buckets.length === 0) {
                    noData.value = true;
                    if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
                    return;
                }
                renderChart(data.buckets);
            } catch (e) {
                console.error('Failed to fetch timeseries:', e);
            } finally {
                loading.value = false;
            }
        }

        function renderChart(buckets) {
            const labels = buckets.map(b => new Date(b.bucket * 1000).toLocaleString('zh-CN', { hour12: false }));
            const datasets = [
                { label: '直连上传', data: buckets.map(b => b.direct_upload), backgroundColor: 'rgba(52,152,219,0.5)', stack: 'direct' },
                { label: '直连下载', data: buckets.map(b => b.direct_download), backgroundColor: 'rgba(52,152,219,0.9)', stack: 'direct' },
                { label: '代理上传', data: buckets.map(b => b.proxy_upload), backgroundColor: 'rgba(231,76,60,0.5)', stack: 'proxy' },
                { label: '代理下载', data: buckets.map(b => b.proxy_download), backgroundColor: 'rgba(231,76,60,0.9)', stack: 'proxy' },
            ];

            if (chartInstance) {
                chartInstance.data.labels = labels;
                chartInstance.data.datasets = datasets;
                chartInstance.update();
                return;
            }

            nextTick(() => {
                const canvas = document.getElementById('trafficChart');
                if (!canvas) return;
                const ctx = canvas.getContext('2d');
                chartInstance = new Chart(ctx, {
                    type: 'bar',
                    data: { labels, datasets },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            tooltip: {
                                callbacks: {
                                    label: (ctx) => `${ctx.dataset.label}: ${formatBytes(ctx.raw)}`
                                }
                            }
                        },
                        scales: {
                            x: { stacked: true },
                            y: {
                                stacked: true,
                                beginAtZero: true,
                                ticks: { callback: (v) => formatBytes(v) }
                            }
                        }
                    }
                });
            });
        }

        function setGranularity(g) {
            granularity.value = g;
            fetchData();
        }

        onMounted(() => fetchData());

        return { granularity, loading, noData, granularityOptions, setGranularity };
    },
    template: `
        <div class="card chart-card">
            <div class="card-header">
                <h3>流量趋势</h3>
                <div class="tabs">
                    <button v-for="opt in granularityOptions" :key="opt.value"
                        class="tab" :class="{ active: granularity === opt.value }"
                        @click="setGranularity(opt.value)">{{ opt.label }}</button>
                </div>
            </div>
            <div class="chart-wrapper">
                <div v-if="loading" class="loading-state">加载中…</div>
                <div v-else-if="noData" class="empty-state">暂无数据</div>
                <canvas v-show="!loading && !noData" id="trafficChart"></canvas>
            </div>
        </div>
    `
};