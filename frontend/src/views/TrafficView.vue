<script setup lang="ts">
import { Activity, ArrowDownToLine, ArrowUpFromLine, RadioTower } from '@lucide/vue';
import { BarController, BarElement, CategoryScale, Chart, Legend, LinearScale, Tooltip } from 'chart.js';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

type Direction = '' | 'proxy' | 'direct';
type TopDimension = 'app' | 'host' | 'chain' | 'connection';

interface Connection {
  id: string;
  process_name?: string;
  host?: string;
  dest_port?: number;
  direction?: Exclude<Direction, ''>;
  chain?: string;
  speed_up?: number;
  speed_down?: number;
  start_ts?: number;
  disconnected?: boolean;
  expires_at?: number;
}

interface TopRow {
  id?: string;
  process_name?: string;
  host?: string;
  chain?: string;
  upload_bytes?: number;
  download_bytes?: number;
}

interface TrafficStatus {
  connected?: boolean;
  live_count?: number;
}

interface TrafficBucket {
  bucket: number | string;
  direct_upload?: number;
  direct_download?: number;
  proxy_upload?: number;
  proxy_download?: number;
}

const granularity = ref('hour');
const direction = ref<Direction>('');
const selectedApp = ref('');
const topDimension = ref<TopDimension>('app');
const liveFilter = ref<{ dimension: TopDimension; value: string } | null>(null);
const apps = ref<string[]>([]);
const live = ref<Connection[]>([]);
const disconnected = ref<Connection[]>([]);
const top = ref<TopRow[]>([]);
const status = ref<TrafficStatus>({});
const loading = ref(true);
const hasSeries = ref(false);
const error = ref('');
const streamState = ref<'connected' | 'reconnecting' | 'offline'>('reconnecting');
const chartCanvas = ref<HTMLCanvasElement | null>(null);
let chart: Chart | null = null;
let socket: WebSocket | null = null;
let retryTimer: number | null = null;

/** Format byte counts without presenting missing values as zero. */
function formatBytes(value: number | null | undefined): string {
  if (!value || !Number.isFinite(value)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let amount = value;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return `${amount.toFixed(amount >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

/** Format a current connection rate while preserving unknown values. */
function formatSpeed(value: number | null | undefined): string {
  return value ? `${formatBytes(value)}/s` : '—';
}

/** Format time-series buckets that may be Unix timestamps or SQL date strings. */
function formatBucket(bucket: TrafficBucket['bucket']): string {
  if (typeof bucket !== 'number') return bucket;
  return new Date(bucket * 1000).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
  });
}

/** Format a connection's observed duration for the live table. */
function formatDuration(startTimestamp?: number): string {
  if (!startTimestamp) return '—';
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - startTimestamp));
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分`;
  return `${Math.floor(seconds / 3600)} 小时 ${Math.floor((seconds % 3600) / 60)} 分`;
}

/** Return the meaningful primary label for each supported ranking dimension. */
function topLabel(row: TopRow): string {
  const labels: Record<TopDimension, string | undefined> = {
    app: row.process_name,
    host: row.host,
    chain: row.chain,
    connection: row.id
  };
  return labels[topDimension.value] || '未知';
}

/** Match a live connection to an optional drill-down selected from a ranking row. */
function matchesLiveFilter(item: Connection): boolean {
  if (!liveFilter.value) return true;
  const { dimension, value } = liveFilter.value;
  return (
    (dimension === 'app' && item.process_name === value) ||
    (dimension === 'host' && item.host === value) ||
    (dimension === 'chain' && item.chain === value) ||
    (dimension === 'connection' && item.id === value)
  );
}

const totalUp = computed(() => live.value.reduce((sum, item) => sum + (item.speed_up || 0), 0));
const totalDown = computed(() => live.value.reduce((sum, item) => sum + (item.speed_down || 0), 0));
const directionLabel = computed(() => ({ '': '全部', proxy: '代理', direct: '直连' })[direction.value]);
const visibleLive = computed(() => [...live.value, ...disconnected.value].filter(
  item => (!direction.value || item.direction === direction.value) && matchesLiveFilter(item)
));

/** Draw the four real traffic series and replace the prior Chart.js instance. */
function renderChart(buckets: TrafficBucket[]): void {
  if (!chartCanvas.value) return;
  chart?.destroy();
  chart = new Chart(chartCanvas.value, {
    type: 'bar',
    data: {
      labels: buckets.map(item => formatBucket(item.bucket)),
      datasets: [
        { label: '直连上传', data: buckets.map(item => Number(item.direct_upload || 0)), backgroundColor: '#a5b4fc', stack: 'direct' },
        { label: '直连下载', data: buckets.map(item => Number(item.direct_download || 0)), backgroundColor: '#6366f1', stack: 'direct' },
        { label: '代理上传', data: buckets.map(item => Number(item.proxy_upload || 0)), backgroundColor: '#86efac', stack: 'proxy' },
        { label: '代理下载', data: buckets.map(item => Number(item.proxy_download || 0)), backgroundColor: '#10b981', stack: 'proxy' }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom' } },
      scales: {
        x: { stacked: true, ticks: { maxTicksLimit: 7 } },
        y: { stacked: true, ticks: { callback: value => formatBytes(Number(value)) } }
      }
    }
  });
}

/** Load status, history, ranking and known application names from current filters. */
async function load(): Promise<void> {
  loading.value = true;
  error.value = '';
  const filter = direction.value ? `&direction=${direction.value}` : '';
  const appFilter = selectedApp.value ? `&app=${encodeURIComponent(selectedApp.value)}` : '';
  try {
    const [statusResponse, seriesResponse, topResponse, appsResponse] = await Promise.all([
      fetch('/api/status'),
      fetch(`/api/timeseries?granularity=${granularity.value}${filter}${appFilter}`),
      fetch(`/api/top?dimension=${topDimension.value}&range=1h${filter}`),
      fetch('/api/apps')
    ]);
    if (![statusResponse, seriesResponse, topResponse, appsResponse].every(response => response.ok)) {
      throw new Error('流量服务暂不可用');
    }
    status.value = await statusResponse.json() as TrafficStatus;
    const series = await seriesResponse.json() as { buckets?: TrafficBucket[] };
    const ranking = await topResponse.json() as { data?: TopRow[] };
    apps.value = await appsResponse.json() as string[];
    top.value = ranking.data || [];
    const buckets = series.buckets || [];
    hasSeries.value = buckets.length > 0;
    await nextTick();
    if (hasSeries.value) renderChart(buckets);
    else { chart?.destroy(); chart = null; }
  } catch (cause) {
    hasSeries.value = false;
    error.value = cause instanceof Error ? cause.message : '加载失败';
  } finally {
    loading.value = false;
  }
}

/** Maintain the short-lived live stream and retain only recently closed rows. */
function connect(): void {
  if (socket) {
    socket.onclose = null;
    socket.close();
  }
  streamState.value = 'reconnecting';
  socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/live`);
  socket.onopen = () => { streamState.value = 'connected'; };
  socket.onmessage = event => {
    try {
      const next = JSON.parse(event.data) as Connection[];
      const known = new Map(live.value.map(item => [item.id, item]));
      const justDisconnected = [...known.values()]
        .filter(item => !next.some(current => current.id === item.id))
        .map(item => ({ ...item, disconnected: true, expires_at: Date.now() + 10_000 }));
      disconnected.value = [...disconnected.value, ...justDisconnected]
        .filter(item => (item.expires_at || 0) > Date.now())
        .slice(-8);
      live.value = next;
    } catch {
      error.value = '实时连接数据格式无效，请稍后重试。';
    }
  };
  socket.onclose = () => {
    streamState.value = 'offline';
    retryTimer = window.setTimeout(connect, 2000);
  };
}

/** Apply an in-page drill-down without altering the historical traffic filter. */
function selectTopRow(row: TopRow): void {
  liveFilter.value = { dimension: topDimension.value, value: topLabel(row) };
}

watch([granularity, direction, selectedApp, topDimension], () => { void load(); });
onMounted(() => { void load(); connect(); });
onBeforeUnmount(() => {
  chart?.destroy();
  if (socket) {
    socket.onclose = null;
    socket.close();
  }
  if (retryTimer !== null) window.clearTimeout(retryTimer);
});
</script>

<template>
  <section class="traffic-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">本地网络监控</p>
        <h1>代理流量监控</h1>
        <p>Clash / Mihomo 连接流量与实时连接。</p>
      </div>
      <div class="traffic-state">
        <span :class="['quality-badge', streamState === 'connected' ? 'exact' : 'unavailable']">
          {{ streamState === 'connected' ? '实时已连接' : '正在重连' }}
        </span>
        <button class="quiet" @click="load">刷新</button>
      </div>
    </header>

    <p v-if="error" class="notice error" role="alert">{{ error }} <button class="mini" @click="load">重试</button></p>

    <section class="traffic-metrics" aria-label="实时流量指标">
      <article class="metric-card"><div class="metric-title"><Activity :size="18" aria-hidden="true" /><h2>实时连接</h2></div><p class="metric-value">{{ status.live_count ?? live.length }}</p><small>由本地采集器提供</small></article>
      <article class="metric-card"><div class="metric-title"><ArrowUpFromLine :size="18" aria-hidden="true" /><h2>上传速率</h2></div><p class="metric-value">{{ formatSpeed(totalUp) }}</p><small>当前 {{ directionLabel }}方向</small></article>
      <article class="metric-card"><div class="metric-title"><ArrowDownToLine :size="18" aria-hidden="true" /><h2>下载速率</h2></div><p class="metric-value">{{ formatSpeed(totalDown) }}</p><small>当前 {{ directionLabel }}方向</small></article>
      <article class="metric-card"><div class="metric-title"><RadioTower :size="18" aria-hidden="true" /><h2>Clash 状态</h2></div><p class="metric-value">{{ status.connected ? '已连接' : '未连接' }}</p><small>不读取或展示密钥</small></article>
    </section>

    <section class="traffic-grid">
      <article class="statistics-section traffic-chart">
        <div class="section-heading">
          <div><h2>流量趋势</h2><p>代理与直连、上传与下载</p></div>
          <div class="traffic-controls">
            <select v-model="granularity" aria-label="统计粒度"><option value="hour">小时</option><option value="day">天</option><option value="week">周</option></select>
            <select v-model="direction" aria-label="方向筛选"><option value="">全部方向</option><option value="proxy">仅代理</option><option value="direct">仅直连</option></select>
            <select v-model="selectedApp" aria-label="应用筛选"><option value="">全部应用</option><option v-for="app in apps" :key="app" :value="app">{{ app }}</option></select>
          </div>
        </div>
        <div class="traffic-canvas"><p v-if="loading" class="empty">加载中…</p><p v-else-if="!hasSeries" class="empty">当前范围尚无历史流量。连接产生流量后，这里会显示真实数据。</p><canvas v-else ref="chartCanvas" /></div>
      </article>

      <article class="statistics-section">
        <div class="section-heading"><div><h2>流量排行</h2><p>点击任意行筛选下方实时连接。</p></div><a :href="`/api/export?kind=top&dimension=${topDimension}&range=1h${direction ? `&direction=${direction}` : ''}`">导出 CSV</a></div>
        <div class="traffic-tabs" role="tablist" aria-label="排行维度"><button v-for="item in [['app', '应用'], ['host', '主机'], ['chain', '链路'], ['connection', '连接']] as const" :key="item[0]" :class="{ active: topDimension === item[0] }" role="tab" :aria-selected="topDimension === item[0]" @click="topDimension = item[0]">{{ item[1] }}</button></div>
        <div class="table-wrap"><table><thead><tr><th>{{ { app: '应用', host: '主机', chain: '链路', connection: '连接' }[topDimension] }}</th><th>上传</th><th>下载</th></tr></thead><tbody><tr v-for="row in top.slice(0, 7)" :key="topLabel(row)" class="clickable-row" @click="selectTopRow(row)"><td>{{ topLabel(row) }}</td><td>{{ formatBytes(row.upload_bytes) }}</td><td>{{ formatBytes(row.download_bytes) }}</td></tr><tr v-if="!top.length"><td colspan="3" class="empty">当前范围没有排行数据</td></tr></tbody></table></div>
      </article>
    </section>

    <section class="statistics-section">
      <div class="section-heading"><div><h2>实时连接</h2><p>断开的连接会明确标记，10 秒后从视图移除。</p></div><div class="traffic-state"><span class="quality-badge">{{ visibleLive.length }} 条</span><button v-if="liveFilter" class="quiet mini" @click="liveFilter = null">清除钻取</button></div></div>
      <p v-if="liveFilter" class="traffic-filter">当前筛选：{{ liveFilter.value }}</p>
      <div class="table-wrap"><table><thead><tr><th>应用</th><th>目标主机</th><th>链路</th><th>方向</th><th>上传</th><th>下载</th><th>持续时间</th><th>状态</th></tr></thead><tbody><tr v-for="item in visibleLive" :key="`${item.id}-${item.disconnected}`" :class="{ 'traffic-disconnected': item.disconnected }"><td>{{ item.process_name || '未知' }}</td><td>{{ item.host || '未知' }}{{ item.dest_port ? `:${item.dest_port}` : '' }}</td><td>{{ item.chain || '未知' }}</td><td>{{ item.direction === 'proxy' ? '代理' : '直连' }}</td><td>{{ formatSpeed(item.speed_up) }}</td><td>{{ formatSpeed(item.speed_down) }}</td><td>{{ formatDuration(item.start_ts) }}</td><td>{{ item.disconnected ? '已断开' : '活跃' }}</td></tr><tr v-if="!visibleLive.length"><td colspan="8" class="empty">暂无活跃连接</td></tr></tbody></table></div>
    </section>
  </section>
</template>
