<script setup lang="ts">
import { onMounted, ref } from 'vue'

type Metric = { value: number | null; availability: string; quality: string; source: string | null; reason_code?: string | null; formula?: string }
type Overview = { metrics: Record<string, Metric>; rollup_status: string }

const loading = ref(true)
const error = ref('')
const networkError = ref(false)
const hasData = ref(true)
const overview = ref<Overview | null>(null)
const series = ref<any[]>([])
const connector = ref<any>(null)
const breakdown = ref<any[]>([])
const reliability = ref<any>(null)
const quality = ref<any[]>([])
const conflicts = ref<any[]>([])
const audit = ref<any[]>([])
const expanded = ref<string | null>(null)

function display(metric: Metric | undefined) { return metric?.value == null ? '—' : metric.value.toLocaleString() }
function status(metric: Metric | undefined) { return metric?.value == null ? 'unavailable' : metric.quality }
function costClass(kind: string, metric: Metric | undefined) { return ['quality-badge', kind, status(metric)] }

async function load() {
  loading.value = true; error.value = ''; networkError.value = false
  try {
    const [overviewResponse, seriesResponse, connectorResponse, breakdownResponse, reliabilityResponse, qualityResponse, conflictsResponse, auditResponse] = await Promise.all([
      fetch('/api/ai-workbench/statistics/overview'),
      fetch('/api/ai-workbench/statistics/timeseries'),
      fetch('/api/ai-workbench/statistics/cc-switch/capabilities'),
      fetch('/api/ai-workbench/statistics/breakdown'),
      fetch('/api/ai-workbench/statistics/reliability'),
      fetch('/api/ai-workbench/statistics/data-quality'),
      fetch('/api/ai-workbench/statistics/conflicts'),
      fetch('/api/ai-workbench/statistics/cc-switch/audit')
    ])
    if ([overviewResponse, seriesResponse, connectorResponse, breakdownResponse, reliabilityResponse, qualityResponse, conflictsResponse, auditResponse].some(response => !response.ok)) { networkError.value = true; throw new Error('统计服务请求失败') }
    overview.value = await overviewResponse.json()
    hasData.value = overview.value.rollup_status !== 'empty'
    series.value = (await seriesResponse.json()).data ?? []
    connector.value = await connectorResponse.json()
    breakdown.value = (await breakdownResponse.json()).data ?? []
    reliability.value = await reliabilityResponse.json()
    quality.value = (await qualityResponse.json()).data ?? []
    conflicts.value = (await conflictsResponse.json()).data ?? []
    audit.value = (await auditResponse.json()).data ?? []
  } catch (cause) {
    error.value = networkError.value ? '统计服务请求失败，请检查网络或 API 服务后重试' : (cause instanceof Error ? cause.message : '加载失败')
  } finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <main class="overview statistics-page">
    <section class="overview-heading">
      <p class="eyebrow">Phase 2 · Statistics</p>
      <h2>用量统计</h2>
      <p>原生会话是基础事实；每个指标都保留来源、质量和可用性。</p>
    </section>

    <p v-if="error" class="notice error" role="alert">{{ error }} <button class="mini" @click="load">重试</button></p>
    <p v-else-if="loading" class="empty">加载中…</p>
    <template v-else-if="overview">
      <p v-if="!hasData" class="notice" role="status">该时间段确实没有统计数据（不是请求失败）。</p>
      <p v-if="overview.rollup_status === 'stale'" class="notice" role="status">统计数据正在等待重建，当前结果可能不是最新版本。</p>
      <section class="connector-status" aria-label="CC Switch connector status">
        <div><strong>CC Switch 增强</strong><span class="connector-copy">只读，可选；基础统计不依赖它。</span></div>
        <span :class="['quality-badge', connector?.status === 'available' ? 'exact' : 'unavailable']">{{ connector?.status ?? 'unavailable' }}</span>
      </section>
      <section v-if="audit.length" class="connector-audit" aria-label="CC Switch audit"><span>最近探测：{{ audit[0].status }} · {{ audit[0].action }}</span><time>{{ audit[0].observed_at }}</time></section>
      <section class="metric-grid" aria-label="统计指标">
        <article v-for="(item, key) in overview.metrics" :key="key" class="metric-card">
          <div class="metric-header"><h3>{{ key }}</h3><span :class="costClass(key === 'actual' ? 'actual' : key === 'estimate' ? 'estimate' : 'metric', item)">{{ key === 'actual' ? 'Recorded actual' : key === 'estimate' ? 'API-equivalent estimate' : status(item) }}</span></div>
          <p class="metric-value">{{ display(item) }}</p>
          <button class="metric-detail" type="button" @click="expanded = expanded === key ? null : key">查看来源</button>
          <dl v-if="expanded === key" class="metric-provenance">
            <dt>source</dt><dd>{{ item.source }}</dd>
            <dt>quality</dt><dd>{{ item.quality }}</dd>
            <template v-if="item.reason_code"><dt>reason</dt><dd>{{ item.reason_code }}</dd></template>
            <template v-if="item.formula"><dt>formula</dt><dd>{{ item.formula }}</dd></template>
          </dl>
        </article>
      </section>

      <section class="statistics-section" aria-labelledby="trend-heading">
        <div class="section-heading"><div><p class="eyebrow">Daily rollup</p><h3 id="trend-heading">趋势</h3></div><a href="/api/ai-workbench/statistics/export.csv">导出 CSV</a></div>
        <div class="table-wrap"><table><thead><tr><th>日期</th><th>请求</th><th>输入 token</th><th>输出 token</th><th>质量</th></tr></thead><tbody>
          <tr v-for="point in series" :key="point.bucket_start_utc"><td>{{ point.bucket_date }}</td><td>{{ display(point.metrics.request_count) }}</td><td>{{ display(point.metrics.input_tokens) }}</td><td>{{ display(point.metrics.output_tokens) }}</td><td><span :class="costClass('actual', point.metrics.actual)">Recorded actual {{ display(point.metrics.actual) }}</span> <span :class="costClass('estimate', point.metrics.estimate)">API estimate {{ display(point.metrics.estimate) }}</span><small v-if="point.provenance?.merge_status && point.provenance.merge_status !== 'primary'"> Conflict: {{ point.provenance.merge_status }}</small><small v-if="point.metrics.estimate.formula"> {{ point.metrics.estimate.formula }}</small></td></tr>
          <tr v-if="!series.length"><td colspan="5" class="empty">当前筛选范围没有数据</td></tr>
        </tbody></table></div>
      </section>

      <section class="statistics-columns">
        <section class="statistics-section" aria-labelledby="breakdown-heading"><div class="section-heading"><h3 id="breakdown-heading">按工具拆分</h3></div><div class="table-wrap"><table><thead><tr><th>工具</th><th>模型</th><th>请求</th><th>输入</th><th>成本/状态</th></tr></thead><tbody><tr v-for="row in breakdown" :key="`${row.tool}-${row.model}-${row.provider}`"><td>{{ row.tool ?? '—' }}</td><td>{{ row.model ?? '—' }}</td><td>{{ display(row.metrics.request_count) }}</td><td>{{ display(row.metrics.input_tokens) }}</td><td><span :class="costClass('actual', row.metrics.actual)">Actual {{ display(row.metrics.actual) }}</span> <span :class="costClass('estimate', row.metrics.estimate)">Estimate {{ display(row.metrics.estimate) }}</span><small v-if="row.metrics.estimate.formula"> {{ row.metrics.estimate.formula }}</small><small v-if="row.conflict_status === 'conflict'"> Conflict ({{ row.conflict_count }})</small></td></tr><tr v-if="!breakdown.length"><td colspan="5" class="empty">暂无拆分数据</td></tr></tbody></table></div></section>
        <section class="statistics-section" aria-labelledby="quality-heading"><div class="section-heading"><h3 id="quality-heading">数据可靠性</h3></div><dl class="reliability-list"><template v-for="(item, key) in reliability" :key="key"><dt>{{ key }}</dt><dd><span :class="['quality-badge', item.quality === 'exact' ? 'exact' : 'unavailable']">{{ item.availability }}</span> {{ item.reason_code ?? item.source }}</dd></template></dl><div class="quality-counts"><div v-for="item in quality" :key="`${item.source}-${item.quality}`"><span>{{ item.source }} · {{ item.quality }}</span><strong>{{ item.count }}</strong></div></div></section>
      </section>
      <section v-if="conflicts.length" class="statistics-section" aria-labelledby="conflicts-heading"><div class="section-heading"><h3 id="conflicts-heading">观测冲突与关联</h3></div><div class="conflict-list"><details v-for="item in conflicts" :key="item.id"><summary>{{ item.link_kind }} · {{ item.confidence }} · {{ item.created_at }}</summary><pre>{{ JSON.stringify(item.details, null, 2) }}</pre></details></div></section>
    </template>
  </main>
</template>
