<script setup lang="ts">
import { ref } from 'vue';
import { BarChart3, Home, MessageSquareText, Network, PlayCircle, CalendarClock, Settings } from '@lucide/vue';
import workbenchMark from './assets/brand/you-mark.png';

const navOpen = ref(false);
</script>

<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <button class="nav-menu-button" type="button" :aria-expanded="navOpen" aria-controls="workbench-navigation" @click="navOpen = !navOpen">菜单</button>
    <button v-if="navOpen" class="nav-scrim" type="button" aria-label="关闭导航" @click="navOpen = false"></button>
    <aside id="workbench-navigation" class="side-nav" :class="{ open: navOpen }">
      <RouterLink class="brand" to="/"><img class="brand-mark" :src="workbenchMark" alt="" /><span>AI 编程工作台</span></RouterLink>
      <nav aria-label="主导航" class="nav-list" @click="navOpen = false">
        <RouterLink to="/"><Home :size="18" aria-hidden="true" />总览</RouterLink>
      <RouterLink to="/sessions"><MessageSquareText :size="18" aria-hidden="true" />会话中心</RouterLink>
      <RouterLink to="/runs"><PlayCircle :size="18" aria-hidden="true" />运行中心</RouterLink>
      <span class="nav-disabled" aria-disabled="true"><CalendarClock :size="18" aria-hidden="true" />自动任务<small>待开发 · Phase 4</small></span>
      <RouterLink to="/statistics"><BarChart3 :size="18" aria-hidden="true" />用量统计</RouterLink>
      <span class="nav-divider" aria-hidden="true"></span>
      <RouterLink to="/traffic"><Network :size="18" aria-hidden="true" />代理流量</RouterLink>
      <RouterLink to="/settings"><Settings :size="18" aria-hidden="true" />设置</RouterLink>
      </nav>
      <div class="nav-footer"><span class="status-dot"></span>本地运行中</div>
    </aside>
    <main id="main-content" class="app-content"><RouterView /></main>
  </div>
</template>
