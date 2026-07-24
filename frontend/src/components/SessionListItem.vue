<script setup lang="ts">
import type { SessionRow } from '../types/workbench';

defineProps<{
  session: SessionRow;
  selected: boolean;
}>();

defineEmits<{
  select: [id: string];
}>();
</script>

<template>
  <button
    class="session-item"
    :class="{ selected }"
    @click="$emit('select', session.id)"
  >
    <span class="session-title">{{ session.title || session.native_session_id }}</span>
    <span class="session-meta">{{ session.tool }} · {{ session.event_count }} events</span>
    <span class="session-path">{{ session.transcript_path }}</span>
  </button>
</template>
