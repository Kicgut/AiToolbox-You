<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { Activity, Bell, CheckCircle2, CircleUserRound, Database, MessageSquareText, PlayCircle, Search, ShieldCheck, Sparkles } from '@lucide/vue';

type Metric = { value: number | null; availability: string; quality: string; reason_code?: string | null };
type Session = { id: string; title?: string; tool: string; event_count: number; updated_at: number };
type Run = { id: string; tool: string; mode: string; state: string; cwd?: string; pending_approval_count?: number; updated_at?: string };
type Quality = { quality: string; source: string; count: number };

const loading = ref(true);
const unavailable = ref(false);
const sessions = ref<Session[]>([]);
const runs = ref<Run[]>([]);
const metrics = ref<Record<string, Metric>>({});
const quality = ref<Quality[]>([]);

const activeRuns = computed(() => runs.value.filter(run => ['queued', 'starting', 'running', 'waiting_approval'].includes(run.state)));
const indexedCount = computed(() => sessions.value.length ? `${sessions.value.length}+` : '—');
const token = computed(() => metrics.value.total_tokens);
const requestCount = computed(() => metrics.value.request_count);
const qualityCount = computed(() => quality.value.reduce((sum, item) => sum + item.count, 0));
const display = (value?: number | null) => value == null ? '—' : value.toLocaleString('zh-CN');
const runState = (state: string) => ({ queued: '排队中', starting: '启动中', running: '运行中', waiting_approval: '等待审批', succeeded: '已完成', failed: '失败', cancelled: '已取消' }[state] ?? state);
const shortTitle = (item: Session) => item.title?.trim() || item.tool.toUpperCase() + ' 会话';

async function load() {
  loading.value = true; unavailable.value = false;
  try {
    const [sessionResponse, runResponse, overviewResponse, qualityResponse] = await Promise.all([
      fetch('/api/ai-workbench/sessions?limit=5'), fetch('/api/ai-workbench/runs?limit=5'),
      fetch('/api/ai-workbench/statistics/overview'), fetch('/api/ai-workbench/statistics/data-quality')
    ]);
    if (![sessionResponse, runResponse, overviewResponse, qualityResponse].every(response => response.ok)) throw new Error('overview unavailable');
    sessions.value = (await sessionResponse.json()).data ?? [];
    runs.value = (await runResponse.json()).data ?? [];
    metrics.value = (await overviewResponse.json()).metrics ?? {};
    quality.value = (await qualityResponse.json()).data ?? [];
  } catch { unavailable.value = true; } finally { loading.value = false; }
}
onMounted(load);
</script>

<template>
  <main class="overview page-frame">
    <header class="overview-hero overview-toolbar">
      <div><p class="page-kicker">本地 AI 开发工作台</p><h1>早上好，开发者</h1><p class="hero-copy">会话、受控运行、统计与流量监控的本地工作入口。</p></div>
      <div class="overview-tools">
        <label class="global-search disabled-control"><Search :size="17" aria-hidden="true" /><input disabled placeholder="全局搜索待开发" /><kbd>⌘ K</kbd></label>
        <button class="icon-placeholder" disabled aria-label="通知功能待开发"><Bell :size="18" /></button>
        <span class="avatar-placeholder" aria-label="用户资料功能待开发"><CircleUserRound :size="27" /></span>
      </div>
    </header>
    <p v-if="unavailable" class="notice error" role="alert">总览数据暂不可用。你仍可从侧栏进入各功能页面。</p>

    <section class="overview-kpis" aria-label="当前工作状态">
      <article class="overview-kpi"><MessageSquareText aria-hidden="true" /><span>最近已索引会话</span><strong>{{ loading ? '…' : indexedCount }}</strong><small>来自本地会话索引</small></article>
      <article class="overview-kpi"><Activity aria-hidden="true" /><span>已记录请求</span><strong>{{ loading ? '…' : display(requestCount?.value) }}</strong><small>{{ requestCount?.availability === 'available' ? '来源：已归集用量' : '暂无可用统计' }}</small></article>
      <article class="overview-kpi"><PlayCircle aria-hidden="true" /><span>运行中或待处理</span><strong>{{ loading ? '…' : activeRuns.length }}</strong><small>来源：受控运行队列</small></article>
      <article class="overview-kpi"><ShieldCheck aria-hidden="true" /><span>数据质量记录</span><strong>{{ loading ? '…' : qualityCount || '—' }}</strong><small>{{ quality.length ? '含来源与质量标记' : '暂无质量记录' }}</small></article>
    </section>

    <section class="overview-main-grid">
      <article class="overview-panel overview-trend"><div class="panel-heading"><div><p class="page-kicker">真实数据摘要</p><h2>用量趋势</h2></div><RouterLink to="/statistics">查看统计 →</RouterLink></div><div v-if="token?.value != null" class="trend-value"><strong>{{ display(token.value) }}</strong><span>总 Token（{{ token.quality }}）</span></div><div v-else class="panel-empty"><Database :size="24" /><p>暂无可绘制的 Token 趋势。统计服务返回真实序列后将在这里展示。</p></div></article>
      <article class="overview-panel"><div class="panel-heading"><h2>运行队列</h2><RouterLink to="/runs">查看全部 →</RouterLink></div><div class="overview-list"><RouterLink v-for="run in runs.slice(0, 3)" :key="run.id" class="overview-row" to="/runs"><span class="row-icon"><PlayCircle :size="17" /></span><span><b>{{ run.tool }} · {{ run.mode }}</b><small>{{ run.cwd || '未指定目录' }}</small></span><em :class="`run-state-${run.state}`">{{ runState(run.state) }}</em></RouterLink><p v-if="!loading && !runs.length" class="panel-empty">暂无受控运行</p></div></article>
    </section>
    <section class="overview-bottom-grid">
      <article class="overview-panel"><div class="panel-heading"><h2>最近会话</h2><RouterLink to="/sessions">查看全部 →</RouterLink></div><div class="overview-list"><RouterLink v-for="session in sessions.slice(0, 3)" :key="session.id" class="overview-row" to="/sessions"><span class="row-icon"><MessageSquareText :size="17" /></span><span><b>{{ shortTitle(session) }}</b><small>{{ session.tool }} · {{ session.event_count }} 个事件</small></span></RouterLink><p v-if="!loading && !sessions.length" class="panel-empty">暂无已索引会话</p></div></article>
      <article class="overview-panel"><div class="panel-heading"><h2>实时运行</h2><RouterLink to="/runs">打开运行中心 →</RouterLink></div><div class="panel-empty"><Sparkles :size="24" /><p>{{ activeRuns.length ? `当前有 ${activeRuns.length} 个待处理运行，请在运行中心查看活动流。` : '当前没有活跃运行；可新建只读受控运行。' }}</p></div></article>
      <article class="overview-panel"><div class="panel-heading"><h2>数据质量</h2><RouterLink to="/statistics">查看详情 →</RouterLink></div><div v-if="quality.length" class="quality-summary"><div v-for="item in quality" :key="`${item.source}-${item.quality}`"><span>{{ item.quality }}</span><i></i><strong>{{ item.count }}</strong></div></div><div v-else class="panel-empty"><ShieldCheck :size="24" /><p>暂无质量数据；不会以示例百分比替代。</p></div></article>
    </section>
  </main>
</template>
