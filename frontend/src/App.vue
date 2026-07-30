<script setup lang="ts">
import { BarChart3, Home, MessageSquareText, Network } from '@lucide/vue';
</script>

<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <aside class="side-nav">
      <RouterLink class="brand" to="/"><span class="brand-mark">A</span><span>AI 编程工作台</span></RouterLink>
      <nav aria-label="主导航" class="nav-list">
        <RouterLink to="/"><Home :size="18" aria-hidden="true" />总览</RouterLink>
        <RouterLink to="/sessions"><MessageSquareText :size="18" aria-hidden="true" />会话中心</RouterLink>
        <RouterLink to="/statistics"><BarChart3 :size="18" aria-hidden="true" />用量统计</RouterLink>
        <RouterLink to="/traffic"><Network :size="18" aria-hidden="true" />代理流量</RouterLink>
      </nav>
      <div class="nav-footer"><span class="status-dot"></span>本地运行中</div>
    </aside>
    <main id="main-content" class="app-content"><RouterView /></main>
  </div>
</template>
