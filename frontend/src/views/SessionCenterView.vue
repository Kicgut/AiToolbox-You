<script setup lang="ts">
import { computed } from 'vue';
import SessionInspector from '../components/SessionInspector.vue';
import SessionListItem from '../components/SessionListItem.vue';
import TimelineEvent from '../components/TimelineEvent.vue';
import { useWorkbenchStore } from '../stores/workbench';
import { pretty } from '../utils/event-rendering';
import workbenchMark from '../assets/brand/you-mark.png';
import emptyWorkbench from '../assets/illustrations/empty-workbench.png';

const store = useWorkbenchStore();

store.init();

const visibleSessions = computed(() =>
  store.sessions.slice(store.virtualStart, store.virtualStart + 70)
);
const topSpacer = computed(() => `${store.virtualStart * 86}px`);
const bottomSpacer = computed(() => {
  const hidden = Math.max(0, store.sessions.length - store.virtualStart - 70);
  return `${hidden * 86}px`;
});

function formatTime(value: number | null): string {
  if (!value) return '—';
  return new Date(value * 1000).toLocaleString();
}

function onSessionScroll(event: Event): void {
  const target = event.target as HTMLElement;
  store.updateVirtualStart(target.scrollTop, 86);
}
</script>

<template>
  <main class="session-page">
    <header class="session-page-header">
      <div><p class="page-kicker">本地会话索引</p><h1>会话中心</h1><p>统一检索并检查本地 Codex、Claude 会话。</p></div>
      <div class="page-actions"><button class="button-secondary" @click="store.scan" :disabled="store.scanning">{{ store.scanning ? '扫描中' : '扫描会话' }}</button><RouterLink class="button-primary" to="/runs">新建运行</RouterLink></div>
    </header>
    <section class="workspace">
    <aside class="sessions-pane">
      <div class="toolbar">
        <select v-model="store.tool" @change="store.loadSessions" aria-label="工具筛选">
          <option value="">全部工具</option>
          <option value="codex">Codex</option>
          <option value="claude">Claude</option>
        </select>
        <button class="toolbar-scan" @click="store.scan" :disabled="store.scanning">{{ store.scanning ? '扫描中' : '扫描' }}</button>
      </div>
      <button class="secondary" @click="store.reconcile" :disabled="store.scanning">增量扫描</button>
      <input class="search" v-model="store.search" @keydown.enter="store.loadSessions" placeholder="搜索标题、路径或 Session ID" />
      <button class="secondary" @click="store.loadSessions">应用筛选</button>

      <div class="manual-profile">
        <select v-model="store.manualTool" aria-label="手动目录工具">
          <option value="codex">Codex</option>
          <option value="claude">Claude</option>
        </select>
        <input v-model="store.manualRoot" placeholder="添加配置根目录" />
        <button class="secondary" @click="store.addManualProfile">添加</button>
      </div>

      <div v-if="store.error" class="notice error">
        {{ store.error }}
        <button class="mini" @click="store.init">重试</button>
      </div>
      <div v-if="store.scanSummary" class="notice">
        {{ pretty(store.scanSummary) }}
      </div>
      <div class="notice search-controls">
        <span>
          全文索引
          {{ store.searchStatus?.consent_state === 'recommended_pending'
            ? '建议开启（待确认）'
            : store.searchStatus?.consent_state === 'user_declined'
              ? '已拒绝'
              : store.searchStatus?.indexing_enabled ? '已开启' : '已关闭' }}
          · 已有 {{ store.searchStatus?.indexed_events || 0 }} 条
        </span>
        <button class="mini" @click="store.toggleSearchIndexing">
          {{ store.searchStatus?.indexing_enabled ? '关闭未来索引' : '开启未来索引' }}
        </button>
        <button class="mini" @click="store.rebuildSearch">重建</button>
        <button class="mini quiet" @click="store.clearSearch">清空已有索引</button>
      </div>

      <section class="profile-strip">
        <div v-for="profile in store.profiles" :key="profile.id" class="profile-row" :class="{ bad: !profile.valid }">
          <span>{{ profile.tool }}</span>
          <small>{{ profile.valid ? '可用' : profile.reason }}</small>
        </div>
      </section>

      <div class="session-list" aria-live="polite" @scroll="onSessionScroll">
        <div v-if="store.loading" class="state-message state-message--compact" role="status">
          <img class="state-brand-mark" :src="workbenchMark" alt="" />
          <span>正在加载会话…</span>
        </div>
        <div :style="{ height: topSpacer }"></div>
        <SessionListItem
          v-for="session in visibleSessions"
          :key="session.id"
          :session="session"
          :selected="session.id === store.selectedId"
          @select="store.selectSession"
        />
        <div :style="{ height: bottomSpacer }"></div>
        <div v-if="!store.loading && !store.sessions.length && !store.error" class="empty-state empty-state--list">
          <img :src="emptyWorkbench" alt="" />
          <div>
            <h2>{{ store.search || store.tool ? '没有匹配的会话' : '还没有已索引会话' }}</h2>
            <p>{{ store.search || store.tool ? '调整筛选条件，或重新扫描本地会话。' : '扫描 Codex 或 Claude 的本地目录后，会话会显示在这里。' }}</p>
            <button type="button" class="button-secondary empty-state-action" :disabled="store.scanning" @click="store.scan">{{ store.scanning ? '正在扫描…' : '扫描会话' }}</button>
          </div>
        </div>
      </div>
    </aside>

    <section class="timeline-pane">
      <div v-if="!store.detail" class="empty center">选择一个会话查看时间线</div>
      <template v-else>
        <div class="timeline-header">
          <div>
            <h2>{{ store.detail.session.title || store.detail.session.native_session_id }}</h2>
            <p>{{ store.detail.session.tool }} · {{ formatTime(store.detail.session.updated_at) }}</p>
          </div>
          <span class="badge">{{ store.detail.session.divergence_status }}</span>
          <button class="secondary inspector-toggle" @click="store.inspectorOpen = !store.inspectorOpen">检查器</button>
        </div>
        <div class="timeline">
          <TimelineEvent
            v-for="event in store.detail.events"
            :key="event.id"
            :event="event"
          />
        </div>
      </template>
    </section>

    <SessionInspector :detail="store.detail" :open="store.inspectorOpen" />
    </section>
  </main>
</template>
