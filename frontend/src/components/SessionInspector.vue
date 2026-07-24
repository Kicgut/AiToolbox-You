<script setup lang="ts">
import type { SessionDetail } from '../types/workbench';
import { pretty } from '../utils/event-rendering';

defineProps<{
  detail: SessionDetail | null;
  open: boolean;
}>();
</script>

<template>
  <aside class="inspector-pane" :class="{ open }">
    <h2>检查器</h2>
    <template v-if="detail">
      <dl>
        <dt>Session ID</dt><dd>{{ detail.session.native_session_id }}</dd>
        <dt>索引状态</dt><dd>{{ detail.session.index_status }}</dd>
        <dt>事件数</dt><dd>{{ detail.session.event_count }}</dd>
        <dt>Profile</dt><dd>{{ detail.profile?.display_name || detail.session.profile_id }}</dd>
        <dt>Transcript</dt><dd>{{ detail.session.transcript_path }}</dd>
      </dl>
      <h3>副本</h3>
      <div v-for="copy in detail.copies" :key="copy.id as string" class="copy-row">
        <span>{{ copy.divergence_status }}</span>
        <small>{{ copy.event_count }} events</small>
      </div>
      <h3>差异摘要</h3>
      <pre>{{ pretty(detail.diffSummary) }}</pre>
    </template>
    <div v-else class="empty">会话元数据会显示在这里。</div>
  </aside>
</template>
