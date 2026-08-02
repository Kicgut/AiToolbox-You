<script setup lang="ts">
import { onMounted } from 'vue';
import { RefreshCw } from '@lucide/vue';
import RunCenter from '../components/RunCenter.vue';
import RunComposer from '../components/RunComposer.vue';
import { useWorkbenchStore } from '../stores/workbench';

const store = useWorkbenchStore();

onMounted(() => {
  store.init();
  store.loadRuns();
});
</script>

<template>
  <main class="run-page page-frame">
    <header class="page-header run-page-header">
      <div>
        <p class="page-kicker">受控执行</p>
        <h1>运行中心</h1>
        <p>创建、观察并处理由服务端确认的受控运行与一次性审批。</p>
      </div>
      <div class="page-actions">
        <button class="button-secondary" type="button" @click="store.loadRuns">
          <RefreshCw :size="16" aria-hidden="true" /> 刷新
        </button>
        <a class="button-primary" href="#new-run">新建运行</a>
      </div>
    </header>

    <section id="new-run" class="run-composer-surface" aria-label="新建运行">
      <RunComposer />
    </section>
    <section class="run-workspace" aria-label="运行队列与详情">
      <RunCenter />
    </section>
  </main>
</template>
