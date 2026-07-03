import { ref, onMounted, onUnmounted, provide } from '../vendor/vue.esm-browser.prod.js';
import StatusBar from './components/StatusBar.js';
import TrafficChart from './components/TrafficChart.js';
import TopTable from './components/TopTable.js';
import LiveTable from './components/LiveTable.js';

export default {
    name: 'App',
    components: { StatusBar, TrafficChart, TopTable, LiveTable },
    setup() {
        const liveData = ref([]);
        const liveDirection = ref('');
        const darkMode = ref(false);
        let ws = null;
        let statusBarRef = ref(null);

        // Dark mode: read system preference once, then localStorage
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme) {
            darkMode.value = savedTheme === 'dark';
        } else {
            darkMode.value = window.matchMedia('(prefers-color-scheme: dark)').matches;
        }

        function toggleDarkMode() {
            darkMode.value = !darkMode.value;
            localStorage.setItem('theme', darkMode.value ? 'dark' : 'light');
            document.documentElement.setAttribute('data-theme', darkMode.value ? 'dark' : 'light');
        }

        function connectWS() {
            const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${proto}//${location.host}/ws/live`);
            ws.onmessage = (e) => {
                try {
                    const data = JSON.parse(e.data);
                    liveData.value = data;
                    if (statusBarRef.value) {
                        statusBarRef.value.updateFromLiveData(data);
                    }
                } catch {}
            };
            ws.onclose = () => setTimeout(connectWS, 2000);
            ws.onerror = () => ws.close();
        }

        function handleDrilldown(info) {
            if (info.type === 'app' || info.type === 'host') {
                liveDirection.value = info.direction || '';
            }
        }

        onMounted(() => {
            document.documentElement.setAttribute('data-theme', darkMode.value ? 'dark' : 'light');
            connectWS();
        });

        onUnmounted(() => {
            if (ws) ws.close();
        });

        return { liveData, liveDirection, darkMode, toggleDarkMode, handleDrilldown, statusBarRef };
    },
    template: `
        <div class="app-container">
            <header class="app-header">
                <h1>代理流量监控</h1>
                <button class="theme-toggle" @click="toggleDarkMode">
                    {{ darkMode ? '☀ 亮色' : '🌙 暗色' }}
                </button>
            </header>

            <StatusBar ref="statusBarRef" />

            <TrafficChart />

            <TopTable @drilldown="handleDrilldown" />

            <div class="card">
                <div class="card-header">
                    <h3>实时连接</h3>
                    <div class="controls">
                        <select v-model="liveDirection">
                            <option value="">全部</option>
                            <option value="proxy">仅代理</option>
                            <option value="direct">仅直连</option>
                        </select>
                    </div>
                </div>
                <LiveTable :liveData="liveData" :directionFilter="liveDirection" />
            </div>
        </div>
    `
};