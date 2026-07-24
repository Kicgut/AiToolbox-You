<script setup lang="ts">
import type { EventRow } from '../types/workbench';
import { pretty, renderEventHtml } from '../utils/event-rendering';

defineProps<{
  event: EventRow;
}>();
</script>

<template>
  <article class="event" :data-type="event.event_type">
    <header>
      <span>{{ event.sequence_no }} · {{ event.event_type }}</span>
      <strong>{{ event.role || event.data_quality }}</strong>
    </header>
    <div class="event-body" v-html="renderEventHtml(event)"></div>
    <details v-if="event.raw_json">
      <summary>Raw</summary>
      <pre>{{ pretty(event.raw_json) }}</pre>
    </details>
  </article>
</template>
