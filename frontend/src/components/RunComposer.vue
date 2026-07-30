<script setup lang="ts">
import { computed, ref } from 'vue';
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
const canSubmit = computed(() => Boolean(
  profileId.value && cwd.value.trim() && prompt.value.trim() && !store.composerBusy
  && (mode.value === 'new' || store.detail?.session.id),
));

function onToolChange() { profileId.value = profiles.value[0]?.id || ''; }
function onModeChange() {
  if (mode.value === 'new') return;
  const session = store.detail?.session;
  if (!session || session.tool !== tool.value) return;
  profileId.value = String(session.profile_id || profileId.value);
}
async function submit() {
  if (!canSubmit.value) return;
  const request: ComposeRunRequest = {
    action: mode.value, tool: tool.value, profile_id: profileId.value, cwd: cwd.value.trim(),
    prompt: prompt.value.trim(), model: model.value.trim() || null,
    permission_policy: { permission_mode: 'read_only', allowed_tools: ['read'] },
    budget_policy: { max_turns: 1, max_duration_seconds: 180, max_total_tokens: 20000 },
    session_copy_id: mode.value === 'new' ? null : String(store.detail?.session.id || ''),
    client_request_id: `composer-${Date.now()}`
  };
  const summary = `${request.tool} · ${request.action}\n目录：${request.cwd}\n模型：${request.model || '默认'}\n权限：只读\n预算：最多 1 回合 / 180 秒\n\n确认提交本次运行？`;
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
      <label>工具<select v-model="tool" @change="onToolChange"><option value="codex">Codex</option><option value="claude">Claude</option></select></label>
      <label>模式<select v-model="mode" @change="onModeChange"><option value="new">新建</option><option value="resume" :disabled="!store.detail">Resume</option><option value="fork" :disabled="!store.detail">Fork</option></select></label>
      <label>Profile<select v-model="profileId"><option value="" disabled>选择可用 Profile</option><option v-for="profile in profiles" :key="profile.id" :value="profile.id">{{ profile.display_name || profile.id }}</option></select></label>
      <label>模型（可选）<input v-model="model" placeholder="留空使用配置默认值" /></label>
      <label class="wide">项目目录<input v-model="cwd" spellcheck="false" /></label>
      <label class="wide">Prompt<textarea v-model="prompt" rows="3" /></label>
    </div>
    <p v-if="mode !== 'new' && store.detail" class="composer-help">将使用当前选中的会话：{{ store.detail.session.native_session_id }}</p>
    <p v-else-if="mode !== 'new'" class="composer-error">请先在左侧选择一个已索引会话，再使用 Resume 或 Fork。</p>
    <p v-if="store.composerError" class="composer-error" role="alert">{{ store.composerError }}</p>
    <div class="composer-footer"><span>只读策略 · 最多 1 回合 · 180 秒</span><button :disabled="!canSubmit" @click="submit">{{ store.composerBusy ? '创建中…' : '创建 Run' }}</button></div>
  </section>
</template>
