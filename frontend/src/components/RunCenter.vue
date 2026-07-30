<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { useWorkbenchStore } from '../stores/workbench';

const store = useWorkbenchStore();
const statusClass = (state: string) => `run-state-${state}`;
const visibleEvents = computed(() => store.runEvents.slice(-200));
const eventPane = ref<HTMLElement | null>(null);
const followEvents = ref(true);
const unseenEvents = ref(0);
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
function eventDetail(event: { payload: Record<string, unknown> }) {
  const payload = event.payload || {};
  if (payload.artifact) return '大输出已归档；可按需查看。';
  return String(payload.text_delta || payload.text || payload.message || payload.raw || payload.reason || payload.state || payload.target_summary || '已记录');
}
function artifact(event: { payload: Record<string, unknown> }) {
  const value = event.payload?.artifact;
  return value && typeof value === 'object' ? value as { artifact_id?: string; size_bytes?: number } : null;
}
function onEventScroll() {
  const pane = eventPane.value;
  if (!pane) return;
  followEvents.value = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 24;
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
</script>

<template>
  <section class="run-center" aria-label="运行中心">
    <div class="run-center-header">
      <h2>运行中心</h2>
      <button class="mini" @click="store.loadRuns">刷新</button>
    </div>
    <div class="run-list" aria-live="polite">
      <section v-for="group in runGroups" :key="group.label" class="run-group">
        <h3>{{ group.label }}</h3>
        <button v-for="run in group.runs" :key="run.id" class="run-row" :class="{ selected: run.id === store.activeRun?.id }" @click="store.openRun(run.id)">
          <span>{{ run.tool }} · {{ run.mode }}</span>
          <span :class="['run-state', statusClass(run.state)]">{{ run.state }}</span>
          <small>{{ run.profile_id }} · {{ run.cwd?.split(/[\\/]/).filter(Boolean).at(-1) || '未指定目录' }}{{ run.model ? ` · ${run.model}` : '' }}</small>
          <small v-if="run.pending_approval_count">审批 {{ run.pending_approval_count }}</small>
        </button>
      </section>
      <span v-if="!store.runs.length" class="empty">暂无运行</span>
    </div>
    <template v-if="store.activeRun">
      <div class="run-detail-header">
        <span>{{ store.activeRun.id }}</span>
        <button v-if="['queued','starting','running','waiting_approval','cancel_requested','cancelling'].includes(store.activeRun.state)" class="mini danger" @click="store.cancelActiveRun">取消</button>
        <button class="mini" @click="store.closeRun">关闭</button>
      </div>
      <p v-if="store.activeRun.failure_message" class="run-failure" role="alert">
        {{ store.activeRun.failure_code || '运行失败' }}：{{ store.activeRun.failure_message }}
      </p>
      <div v-if="store.activeApprovals.length" class="run-approvals">
        <strong>待处理审批</strong>
        <div v-for="approval in store.activeApprovals" :key="approval.id" class="approval-row">
          <span><b>{{ approval.operation }}</b> · {{ approval.target_summary }} · 风险 {{ approval.risk_level }}</span>
          <small>状态：{{ approval.state }}</small>
          <small v-if="approval.reason">{{ approval.reason }}</small>
          <div v-if="approval.state === 'pending'" class="approval-actions">
            <button class="mini" @click="store.decideApproval(approval.id, 'accept')">接受</button>
            <button class="mini" @click="store.decideApproval(approval.id, 'decline')">拒绝</button>
            <button class="mini" @click="store.decideApproval(approval.id, 'cancel')">取消</button>
          </div>
        </div>
      </div>
      <div ref="eventPane" class="run-events" aria-live="polite" @scroll="onEventScroll">
        <div v-for="event in visibleEvents" :key="event.event_id" class="run-event">
          <span>#{{ event.sequence_no }}</span><strong>{{ eventTitle(event) }}</strong>
          <p>{{ eventDetail(event) }}</p>
          <a v-if="artifact(event)?.artifact_id && store.activeRun" :href="`/api/ai-workbench/runs/${store.activeRun.id}/artifacts/${artifact(event)?.artifact_id}`" target="_blank" rel="noopener">查看归档（{{ artifact(event)?.size_bytes }} bytes）</a>
        </div>
        <p v-if="!visibleEvents.length" class="empty">{{ emptyMessage }}</p>
      </div>
      <button v-if="unseenEvents" class="mini run-new-events" @click="scrollToLatest">有 {{ unseenEvents }} 条新事件</button>
    </template>
  </section>
</template>
