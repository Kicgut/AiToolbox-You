<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { Download, RefreshCw, ShieldCheck } from '@lucide/vue';
import { api } from '../api/client';
import type { RepositoryUpdateStatus } from '../types/workbench';

const status = ref<RepositoryUpdateStatus | null>(null);
const loading = ref(false);
const applying = ref(false);
const autoUpdate = ref(false);
const error = ref('');
const notice = ref('');

async function check(): Promise<void> {
  loading.value = true;
  error.value = '';
  notice.value = '';
  try {
    status.value = await api.get<RepositoryUpdateStatus>('/api/ai-workbench/repository-update?refresh=true');
    autoUpdate.value = status.value.auto_update_enabled;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法检查更新。';
  } finally {
    loading.value = false;
  }
}

async function saveAutoUpdate(): Promise<void> {
  error.value = '';
  try {
    const settings = await api.patch<{ auto_update_enabled: boolean }>('/api/ai-workbench/repository-update/settings', {
      auto_update_enabled: autoUpdate.value
    });
    autoUpdate.value = settings.auto_update_enabled;
    notice.value = settings.auto_update_enabled
      ? '已启用：下一次通过 run.bat 启动时，会在启动前安全检查并快进更新。'
      : '已关闭自动更新；仍可随时手动检查。';
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '保存更新设置失败。';
  }
}

async function apply(): Promise<void> {
  applying.value = true;
  error.value = '';
  notice.value = '';
  try {
    const result = await api.post<RepositoryUpdateStatus>('/api/ai-workbench/repository-update/apply');
    status.value = result;
    notice.value = result.message || (result.restart_required ? '更新完成，请重启应用。' : '已是最新版本。');
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '更新未完成。';
  } finally {
    applying.value = false;
  }
}

onMounted(() => { void check(); });
</script>

<template>
  <main class="settings-page page-frame">
    <header class="page-header">
      <div>
        <p class="page-kicker">本地安装</p>
        <h1>设置</h1>
        <p>仅更新当前仓库的官方 main 分支；不会升级 Codex、Claude 或其他外部软件。</p>
      </div>
      <button class="quiet" type="button" :disabled="loading" @click="check"><RefreshCw :size="16" aria-hidden="true" />{{ loading ? '检查中…' : '检查更新' }}</button>
    </header>

    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice success" role="status">{{ notice }}</p>

    <section class="settings-card" aria-labelledby="repository-update-heading">
      <div class="settings-card-heading">
        <div><p class="eyebrow">Repository update</p><h2 id="repository-update-heading">仓库更新</h2></div>
        <span :class="['quality-badge', status?.repository_available ? 'exact' : 'unavailable']">{{ status?.repository_available ? '可用' : '不可用' }}</span>
      </div>
      <dl v-if="status?.repository_available" class="settings-facts">
        <dt>分支</dt><dd>{{ status.branch }}</dd>
        <dt>远端</dt><dd>{{ status.origin }}</dd>
        <dt>本地改动</dt><dd>{{ status.worktree_clean ? '无' : `检测到 ${status.changed_file_count} 项；更新已保护性禁用` }}</dd>
        <dt>远端提交</dt><dd>{{ status.checked ? `落后 ${status.behind ?? 0}，领先 ${status.ahead ?? 0}` : '尚未检查' }}</dd>
      </dl>
      <p v-else class="settings-muted">{{ status?.message || '正在检查当前安装是否为受支持的 Git 克隆。' }}</p>

      <div class="update-action">
        <div><strong>{{ status?.update_available ? '发现可用更新' : '当前没有可应用的更新' }}</strong><p>手动更新要求工作树干净、位于 main 分支且没有进行中的运行任务。</p></div>
        <button type="button" :disabled="!status?.can_apply || applying" @click="apply"><Download :size="16" aria-hidden="true" />{{ applying ? '正在更新…' : '下载并应用' }}</button>
      </div>
    </section>

    <section class="settings-card" aria-labelledby="automatic-update-heading">
      <div class="settings-card-heading"><div><p class="eyebrow">Startup policy</p><h2 id="automatic-update-heading">自动更新</h2></div><ShieldCheck :size="22" aria-hidden="true" /></div>
      <label class="settings-toggle"><input v-model="autoUpdate" type="checkbox" @change="saveAutoUpdate" /><span>下次启动前自动安全更新</span></label>
      <p class="settings-muted">自动更新只在通过 <code>run.bat</code> 启动应用前运行。存在未提交改动、分支偏离或远端不受信任时会跳过，不覆盖本地文件。</p>
    </section>
  </main>
</template>
