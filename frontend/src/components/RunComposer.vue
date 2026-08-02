<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useWorkbenchStore } from '../stores/workbench';
import type { ComposeRunRequest } from '../types/workbench';

const store = useWorkbenchStore();
const tool = ref<'codex' | 'claude'>('codex');
const mode = ref<'new' | 'resume' | 'fork'>('new');
const profileId = ref('');
const cwd = ref('E:\\statistics-toolbox-You');
const prompt = ref('请读取当前目录的 AGENTS.md，并告诉我文件第一行内容。不要修改任何文件。');
const model = ref('');
const profiles = computed(() => store.profiles.filter((item) => item.tool === tool.value && item.valid));
const selectedProfile = computed(() => profiles.value.find((item) => item.id === profileId.value));
const sourceSession = computed(() => mode.value === 'new' ? null : store.detail?.session || null);
const sessionLocked = computed(() => Boolean(sourceSession.value));
const capabilitySummary = computed(() => {
  const capabilities = selectedProfile.value?.execution_capabilities;
  if (!capabilities) return '';
  if (tool.value === 'codex') return 'Codex 以只读 sandbox 运行；命令或文件变更会请求单次审批。';
  return 'Claude 支持工具允许/拒绝列表；原生审批请求不会由该 adapter 转发。';
});
const observedCapabilityWarning = computed(() => {
  const observed = selectedProfile.value?.observed_capabilities;
  if (!observed) return '';
  if (observed.status === 'missing') return '当前设备未探测到对应 CLI；请先安装或配置 executable。';
  if (mode.value === 'fork' && observed.features?.app_server === false) return '当前 Codex CLI 未声明 App Server，Fork 不可用。';
  return '';
});
const canSubmit = computed(() => Boolean(
  profileId.value && cwd.value.trim() && prompt.value.trim() && !store.composerBusy
  && (mode.value === 'new' || (sourceSession.value?.id && sourceSession.value.tool === tool.value))
  && !observedCapabilityWarning.value,
));

function onToolChange() { profileId.value = profiles.value[0]?.id || ''; }
watch(profiles, (available) => {
  if (!available.some(profile => profile.id === profileId.value)) {
    profileId.value = available[0]?.id || '';
  }
}, { immediate: true });
function onModeChange() {
  if (mode.value === 'new') return;
  const session = store.detail?.session;
  if (!session) return;
  tool.value = session.tool;
  profileId.value = String(session.profile_id || profileId.value);
}
async function submit() {
  if (!canSubmit.value) return;
  const request: ComposeRunRequest = {
    action: mode.value, tool: tool.value, profile_id: profileId.value, cwd: cwd.value.trim(), cwd_confirmed: true,
    prompt: prompt.value.trim(), model: model.value.trim() || null,
    permission_policy: tool.value === 'codex'
      ? { sandbox: 'read-only', approval_policy: 'on-request' }
      : { permission_mode: 'plan', allowed_tools: ['Read'] },
    budget_policy: { max_turns: 1, max_duration_seconds: 180, max_total_tokens_observed: 20000 },
    session_copy_id: mode.value === 'new' ? null : String(store.detail?.session.id || ''),
    client_request_id: `composer-${Date.now()}`
  };
  const promptSummary = request.prompt.replace(/\s+/g, ' ').slice(0, 160);
  const budgetSummary = 'max_turns=1 (hard), max_duration_seconds=180 (hard), max_total_tokens_observed=20000 (observed_only)';
  const summary = `${request.tool} · ${request.action}\nProfile：${request.profile_id}\n目录：${request.cwd}\n模型：${request.model || '默认'}\n权限：${request.tool === 'codex' ? 'read-only sandbox / on-request approval' : 'Claude plan / Read'}\n预算：${budgetSummary}\nPrompt 摘要：${promptSummary}${request.prompt.length > 160 ? '…' : ''}\n\n确认提交本次运行？`;
  if (!window.confirm(summary)) return;
  try { await store.createRun(request); } catch { /* store exposes the error */ }
}
onToolChange();
</script>

<template>
  <section class="run-composer" aria-label="新建运行">
    <div class="composer-heading">
      <div><p class="eyebrow">Phase 3 · controlled execution</p><h2>新建运行</h2><p class="composer-help">选择工具和目录，提交一条受控 prompt。默认权限只允许读取。</p></div>
      <span class="composer-signal">一次一回合</span>
    </div>
    <div class="composer-grid">
      <label>工具<select v-model="tool" :disabled="sessionLocked" @change="onToolChange"><option value="codex">Codex</option><option value="claude">Claude</option></select></label>
      <label>模式<select v-model="mode" @change="onModeChange"><option value="new">新建</option><option value="resume" :disabled="!store.detail">Resume</option><option value="fork" :disabled="!store.detail">Fork</option></select></label>
      <label>Profile<select v-model="profileId" :disabled="sessionLocked"><option value="" disabled>选择可用 Profile</option><option v-for="profile in profiles" :key="profile.id" :value="profile.id">{{ profile.display_name || profile.id }}</option></select></label>
      <label>模型（可选）<input v-model="model" placeholder="留空使用配置默认值" /></label>
      <label class="wide">项目目录<input v-model="cwd" spellcheck="false" /></label>
      <label class="wide">Prompt<textarea v-model="prompt" rows="3" /></label>
    </div>
    <p v-if="capabilitySummary" class="composer-help">{{ capabilitySummary }}</p>
    <p v-if="observedCapabilityWarning" class="composer-error" role="alert">{{ observedCapabilityWarning }}</p>
    <p v-if="mode !== 'new' && store.detail" class="composer-help">将使用当前选中的会话：{{ store.detail.session.native_session_id }}（工具和 Profile 已锁定）</p>
    <p v-else-if="mode !== 'new'" class="composer-error">请先在左侧选择一个已索引会话，再使用 Resume 或 Fork。</p>
    <p v-if="store.composerError" class="composer-error" role="alert">{{ store.composerError }}</p>
    <div class="composer-footer"><span>只读策略 · 最多 1 回合 · 180 秒</span><button :disabled="!canSubmit" @click="submit">{{ store.composerBusy ? '创建中…' : '创建 Run' }}</button></div>
  </section>
</template>
