import { ref, onMounted, onUnmounted, computed, watch, nextTick } from '../../vendor/vue.esm-browser.prod.js';
import { formatBytes, formatSpeed } from '../utils/format.js';

export default {
    name: 'StatusBar',
    setup() {
        const connected = ref(false);
        const liveCount = ref(0);
        const totalUp = ref(0);
        const totalDown = ref(0);
        const speedHistory = ref([]);
        const processWarning = ref(false);
        let timer = null;
        let sparklineChart = null;

        const totalSpeedStr = computed(() => {
            return formatSpeed(totalUp.value + totalDown.value);
        });

        async function pollStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                connected.value = data.connected;
                liveCount.value = data.live_count || 0;
            } catch {}
        }

        function updateFromLiveData(conns) {
            let up = 0, down = 0, unknownCount = 0;
            for (const c of conns) {
                up += c.speed_up || 0;
                down += c.speed_down || 0;
                if (c.process_name === '未知') unknownCount++;
            }
            totalUp.value = up;
            totalDown.value = down;
            const total = up + down;
            speedHistory.value.push(total);
            if (speedHistory.value.length > 60) speedHistory.value.shift();
            processWarning.value = conns.length > 0 && (unknownCount / conns.length) > 0.9;
            updateSparkline();
        }

        function updateSparkline() {
            if (!sparklineChart) return;
            const data = speedHistory.value;
            sparklineChart.data.labels = data.map((_, i) => i);
            sparklineChart.data.datasets[0].data = data;
            sparklineChart.update('none');
        }

        function initSparkline() {
            nextTick(() => {
                const canvas = document.getElementById('speedSparkline');
                if (!canvas) return;
                const ctx = canvas.getContext('2d');
                sparklineChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: [],
                        datasets: [{
                            data: [],
                            borderColor: getComputedStyle(document.documentElement).getPropertyValue('--accent-blue').trim() || '#3498db',
                            backgroundColor: 'transparent',
                            borderWidth: 1.5,
                            pointRadius: 0,
                            tension: 0.3
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: false,
                        plugins: { legend: { display: false }, tooltip: { enabled: false } },
                        scales: {
                            x: { display: false },
                            y: { display: false, beginAtZero: true }
                        }
                    }
                });
            });
        }

        onMounted(() => {
            pollStatus();
            timer = setInterval(pollStatus, 5000);
            initSparkline();
        });

        onUnmounted(() => {
            if (timer) clearInterval(timer);
            if (sparklineChart) { sparklineChart.destroy(); sparklineChart = null; }
        });

        return { connected, liveCount, totalSpeedStr, speedHistory, processWarning, updateFromLiveData };
    },
    template: `
        <div class="status-bar">
            <div class="status-bar-main">
                <span class="status-dot" :class="{ connected }"></span>
                <span class="status-text">{{ connected ? '已连接' : '未连接' }}</span>
                <span class="status-count" v-if="connected">活跃连接: {{ liveCount }}</span>
                <div class="speed-block" v-if="connected">
                    <span class="status-speed">当前总速率: {{ totalSpeedStr }}</span>
                    <div class="sparkline-wrapper">
                        <canvas id="speedSparkline"></canvas>
                    </div>
                </div>
            </div>
            <div class="process-warning" v-if="processWarning">
                ⚠ 未检测到应用名，请在 Clash 配置中将 <code>find-process-mode</code> 设为 <code>always</code> 后重启客户端
            </div>
        </div>
    `
};