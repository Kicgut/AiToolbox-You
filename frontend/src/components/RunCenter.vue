<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { useWorkbenchStore } from '../stores/workbench';
import emptyWorkbench from '../assets/illustrations/empty-workbench.png';

const store = useWorkbenchStore();
const statusClass = (state: string) => `run-state-${state}`;
const activeView = ref<'conversation' | 'activity' | 'diagnostics' | 'audit'>('conversation');
const views = [
  { id: 'conversation', label: '对话' },
  { id: 'activity', label: '工具活动' },
  { id: 'diagnostics', label: '诊断' },
  { id: 'audit', label: '审计' },
] as const;
function viewForEvent(event: { event_type: string }) {
  if (event.event_type.startsWith('message.')) return 'conversation';
  if (event.event_type.startsWith('tool.') || event.event_type.startsWith('command.') || event.event_type.startsWith('file.') || event.event_type.startsWith('approval.')) return 'activity';
  if (event.event_type.startsWith('diagnostic.') || event.event_type === 'unknown' || event.event_type === 'error') return 'diagnostics';
  return 'audit';
}
const visibleEvents = computed(() => store.runEvents.filter(event => viewForEvent(event) === activeView.value));
const EVENT_ROW_HEIGHT = 84;
const EVENT_WINDOW_SIZE = 120;
const eventVirtualStart = ref(0);
const renderedEvents = computed(() => visibleEvents.value.slice(eventVirtualStart.value, eventVirtualStart.value + EVENT_WINDOW_SIZE));
const topEventSpacer = computed(() => eventVirtualStart.value * EVENT_ROW_HEIGHT);
const bottomEventSpacer = computed(() => Math.max(0, visibleEvents.value.length - eventVirtualStart.value - renderedEvents.value.length) * EVENT_ROW_HEIGHT);
const eventCounts = computed(() => Object.fromEntries(views.map(view => [view.id, store.runEvents.filter(event => viewForEvent(event) === view.id).length])) as Record<typeof activeView.value, number>);
const eventPane = ref<HTMLElement | null>(null);
const followEvents = ref(true);
const unseenEvents = ref(0);
const diagnosticCopyStatus = ref('');
const failureNotice = ref<HTMLElement | null>(null);
const approvalNotice = ref<HTMLElement | null>(null);
const runGroups = computed(() => {
  const groups = [
    ['队列', ['queued']], ['运行中', ['starting', 'running', 'cancel_requested', 'cancelling']],
    ['等待审批', ['waiting_approval']], ['最近结束', ['succeeded', 'failed', 'cancelled', 'interrupted']],
  ] as const;
  return groups.map(([label, states]) => ({ label, runs: store.runs.filter(run => states.includes(run.state as never)) })).filter(group => group.runs.length);
});
const emptyMessage = computed(() => {
  const state = store.activeRun?.state;
  if (state === 'queued') return '已排队，正在等待运行协调器领取。';
  if (state === 'starting') return '正在启动并完成协议握手。';
  if (state === 'waiting_approval') return '运行正在等待一次性审批决定。';
  if (state === 'running') return '运行中，尚未收到可展示的输出。';
  if (state === 'cancel_requested' || state === 'cancelling') return '正在停止受管进程树。';
  return '此运行没有可展示的事件。';
});
function eventTitle(event: { event_type: string }) {
  const titles: Record<string, string> = {
    'run.status_changed': '运行状态', 'message.delta': '回复片段', 'message.completed': '回复完成',
    'tool.started': '工具开始', 'tool.output': '工具输出', 'tool.completed': '工具完成',
    'command.output': '命令输出', 'file.changed': '文件变更', 'approval.required': '需要审批',
    'approval.resolved': '审批已处理', 'diagnostic.stderr': '诊断输出', 'error': '错误',
    'run.completed': '运行完成', 'run.failed': '运行失败',
  };
  return titles[event.event_type] || event.event_type;
}
function runDuration(run: { created_at?: string | null; started_at?: string | null; finished_at?: string | null }) {
  const start = Date.parse(run.started_at || run.created_at || '');
  if (!Number.isFinite(start)) return '';
  const end = Date.parse(run.finished_at || '') || Date.now();
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`;
}
function stillHandshaking(run: { state: string; started_at?: string | null; created_at?: string | null }) {
  if (run.state !== 'starting') return false;
  const started = Date.parse(run.started_at || run.created_at || '');
  return Number.isFinite(started) && Date.now() - started > 10_000;
}
function eventDetail(event: { payload: Record<string, unknown> }) {
  const payload = event.payload || {};
  if (payload.artifact) return '大输出已归档；可按需查看。';
  return String(payload.text_delta || payload.delta || payload.text || payload.message || payload.output || payload.raw || payload.reason || payload.state || payload.target_summary || '已记录');
}
function artifact(event: { payload: Record<string, unknown> }) {
  const value = event.payload?.artifact;
  return value && typeof value === 'object' ? value as { artifact_id?: string; size_bytes?: number } : null;
}
function redactDiagnostic(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redactDiagnostic);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) =>
      /token|secret|password|cookie|authorization|api_?key|environment|env_vars|envvars/i.test(key) || key === 'env'
        ? [key, '[redacted]'] : [key, redactDiagnostic(item)],
    ));
  }
  return value;
}
async function copyDiagnostic(event: { sequence_no: number; event_type: string; payload: Record<string, unknown> }) {
  const diagnostic = { sequence_no: event.sequence_no, event_type: event.event_type, payload: redactDiagnostic(event.payload) };
  try {
    await navigator.clipboard.writeText(JSON.stringify(diagnostic, null, 2));
    diagnosticCopyStatus.value = '已复制：事件类型、序号和脱敏 payload；不含环境变量或凭据。';
  } catch {
    diagnosticCopyStatus.value = '浏览器未允许复制；复制范围仍限于脱敏事件字段。';
  }
}
function canDecideApproval() {
  try {
    return JSON.parse(store.activeRun?.capabilities_snapshot_json || '{}').native_approval !== false;
  } catch {
    return true;
  }
}
function onEventScroll() {
  const pane = eventPane.value;
  if (!pane) return;
  followEvents.value = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 24;
  const maxStart = Math.max(0, visibleEvents.value.length - EVENT_WINDOW_SIZE);
  eventVirtualStart.value = Math.min(maxStart, Math.max(0, Math.floor(pane.scrollTop / EVENT_ROW_HEIGHT) - 8));
  if (followEvents.value) unseenEvents.value = 0;
}
async function scrollToLatest() {
  await nextTick();
  eventPane.value?.scrollTo({ top: eventPane.value.scrollHeight, behavior: 'smooth' });
  followEvents.value = true;
  unseenEvents.value = 0;
}
watch(() => visibleEvents.value.length, async (current, previous) => {
  if (current <= previous) return;
  if (followEvents.value) await scrollToLatest();
  else unseenEvents.value += current - previous;
});
watch(activeView, () => { eventVirtualStart.value = 0; });
watch(() => `${store.activeRun?.state || ''}:${store.activeApprovals.filter(item => item.state === 'pending').length}`, async (value, previous) => {
  if (!previous || value === previous) return;
  await nextTick();
  if (['failed', 'cancelled', 'interrupted'].includes(store.activeRun?.state || '')) failureNotice.value?.focus();
  else if (store.activeRun?.state === 'waiting_approval') approvalNotice.value?.focus();
});
</script>

<template>
  <section class="run-center" aria-label="运行中心">
    <div class="run-center-header">
      <h2>运行中心</h2>
      <button class="mini" @click="store.loadRuns">刷新</button>
    </div>
    <div class="run-grid">
    <aside class="run-queue-panel">
    <div class="run-list">
      <section v-for="group in runGroups" :key="group.label" class="run-group">
        <h3>{{ group.label }}</h3>
        <button v-for="run in group.runs" :key="run.id" class="run-row" :class="{ selected: run.id === store.activeRun?.id }" @click="store.openRun(run.id)">
          <span>{{ run.tool }} · {{ run.mode }}</span>
          <span :class="['run-state', statusClass(run.state)]">{{ run.state }}</span>
          <small>{{ run.profile_id }} · {{ run.cwd?.split(/[\\/]/).filter(Boolean).at(-1) || '未指定目录' }}{{ run.model ? ` · ${run.model}` : '' }}{{ runDuration(run) ? ` · ${runDuration(run)}` : '' }}</small>
          <small v-if="run.pending_approval_count">审批 {{ run.pending_approval_count }}</small>
          <small v-if="run.latest_event_type">最新：{{ run.latest_event_type }}</small>
          <small v-if="stillHandshaking(run)">仍在握手；打开详情查看诊断。</small>
        </button>
      </section>
      <div v-if="!store.runs.length" class="empty-state empty-state--list empty-state--runs">
        <img :src="emptyWorkbench" alt="" />
        <div><h3>还没有运行</h3><p>新建一次受控运行后，可在这里查看活动流与审批记录。</p><a class="button-primary empty-state-action" href="#new-run">新建运行</a></div>
      </div>
    </div>
    </aside>
    <section class="run-activity-panel">
    <template v-if="store.activeRun">
      <div class="run-detail-header">
        <span>{{ store.activeRun.id }}</span>
        <small v-if="store.activeRun.native_thread_id || store.activeRun.native_session_id">原生会话：{{ store.activeRun.native_thread_id || store.activeRun.native_session_id }}</small>
        <small v-if="store.runConnection === 'connecting'">正在连接实时流…</small>
        <small v-else-if="store.runConnection === 'offline'" class="run-connection-offline">实时流已断开；正在通过安全轮询恢复。</small>
        <button v-if="['queued','starting','running','waiting_approval','cancel_requested','cancelling'].includes(store.activeRun.state)" class="mini danger" @click="store.cancelActiveRun">取消</button>
        <button class="mini" @click="store.closeRun">关闭</button>
      </div>
      <p v-if="store.activeRun.failure_message" ref="failureNotice" class="run-failure" role="alert" tabindex="-1">
        {{ store.activeRun.failure_code || '运行失败' }}：{{ store.activeRun.failure_message }}
      </p>
      <dl v-if="store.activeRun.budget_limits?.length" class="approval-evidence run-budget-evidence">
        <template v-for="limit in store.activeRun.budget_limits" :key="limit.name">
          <dt>{{ limit.name }}</dt><dd>{{ limit.value ?? 'unavailable' }} <small>({{ limit.strength }} · {{ limit.availability }})</small></dd>
        </template>
      </dl>
      <div v-if="store.activeApprovals.length" ref="approvalNotice" class="run-approvals" tabindex="-1">
        <strong>待处理审批</strong>
        <div v-for="approval in store.activeApprovals" :key="approval.id" class="approval-row">
          <span><b>{{ approval.operation }}</b> · {{ approval.target_summary }} · 风险 {{ approval.risk_level }}</span>
          <small>状态：{{ approval.state }}</small>
          <small v-if="approval.reason">{{ approval.reason }}</small>
          <dl class="approval-evidence">
            <template v-if="approval.command_argv?.length"><dt>命令参数</dt><dd><code v-for="(part, index) in approval.command_argv" :key="`${approval.id}-argv-${index}`">{{ part }}</code></dd></template>
            <template v-if="approval.cwd"><dt>工作目录</dt><dd><code>{{ approval.cwd }}</code></dd></template>
            <template v-if="approval.affected_paths?.length"><dt>受影响路径</dt><dd><code v-for="path in approval.affected_paths" :key="`${approval.id}-${path}`">{{ path }}</code></dd></template>
            <template v-if="approval.network_targets?.length"><dt>网络目标</dt><dd><code v-for="target in approval.network_targets" :key="`${approval.id}-${target}`">{{ target }}</code></dd></template>
            <template v-if="approval.expires_at"><dt>有效期至</dt><dd>{{ approval.expires_at }}</dd></template>
            <dt>授权范围</dt><dd>仅当前原生请求（{{ approval.native_request_id }}），不会扩展到后续操作。</dd>
          </dl>
          <div v-if="approval.state === 'pending' && canDecideApproval()" class="approval-actions">
            <button class="mini" @click="store.decideApproval(approval.id, 'accept')">接受</button>
            <button class="mini" @click="store.decideApproval(approval.id, 'decline')">拒绝</button>
            <button class="mini" @click="store.decideApproval(approval.id, 'cancel')">取消</button>
          </div>
          <small v-else-if="approval.state === 'pending'">当前 adapter 无法把审批决定交付给原生进程。</small>
        </div>
      </div>
      <div class="run-detail-tabs" role="tablist" aria-label="运行详情视图">
        <button v-for="view in views" :id="`run-view-${view.id}`" :key="view.id" class="run-detail-tab" :class="{ active: activeView === view.id }"
          role="tab" :aria-selected="activeView === view.id" :aria-controls="`run-panel-${view.id}`" @click="activeView = view.id">
          {{ view.label }} <span>{{ eventCounts[view.id] }}</span>
        </button>
      </div>
      <p class="sr-only" role="status" aria-live="polite">运行状态：{{ store.activeRun.state }}</p>
      <p v-if="diagnosticCopyStatus" class="sr-only" role="status">{{ diagnosticCopyStatus }}</p>
      <div :id="`run-panel-${activeView}`" ref="eventPane" class="run-events" role="tabpanel" :aria-labelledby="`run-view-${activeView}`" aria-live="off" @scroll="onEventScroll">
        <button v-if="store.runHistoryAvailable" class="mini run-history" :disabled="store.runHistoryLoading" @click="store.loadMoreRunEvents">
          {{ store.runHistoryLoading ? '正在加载事件…' : '加载更多事件' }}
        </button>
        <div v-if="topEventSpacer" class="run-event-spacer" :style="{ height: `${topEventSpacer}px` }" aria-hidden="true" />
        <div v-for="event in renderedEvents" :key="event.event_id" class="run-event">
          <span>#{{ event.sequence_no }}</span><strong>{{ eventTitle(event) }}</strong>
          <p>{{ eventDetail(event) }}</p>
          <button v-if="activeView === 'diagnostics'" class="mini" @click="copyDiagnostic(event)">复制脱敏诊断</button>
          <a v-if="artifact(event)?.artifact_id && store.activeRun" :href="`/api/ai-workbench/runs/${store.activeRun.id}/artifacts/${artifact(event)?.artifact_id}`" target="_blank" rel="noopener">查看归档（{{ artifact(event)?.size_bytes }} bytes）</a>
        </div>
        <div v-if="bottomEventSpacer" class="run-event-spacer" :style="{ height: `${bottomEventSpacer}px` }" aria-hidden="true" />
        <p v-if="!visibleEvents.length" class="empty">{{ emptyMessage }}</p>
      </div>
      <button v-if="unseenEvents" class="mini run-new-events" @click="scrollToLatest">有 {{ unseenEvents }} 条新事件</button>
    </template>
    <p v-else class="empty run-no-selection">从左侧选择一个运行，查看结构化活动流与审批记录。</p>
    </section>
    </div>
  </section>
</template>
