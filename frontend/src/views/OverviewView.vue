<template>
  <main class="overview">
    <section class="overview-heading">
      <p class="eyebrow">本地 AI 编程工具</p>
      <h2>总览</h2>
      <p>从这里进入已上线功能；后续能力会按 Phase 逐步开放。</p>
    </section>
    <section class="feature-grid" aria-label="功能入口">
      <RouterLink class="feature-card available" to="/sessions">
        <span class="feature-status">已上线 · Phase 1</span>
        <h3>会话中心</h3>
        <p>浏览、搜索并检查 Codex 与 Claude 的本地会话记录。</p>
      </RouterLink>
      <a class="feature-card available" href="/traffic">
        <span class="feature-status">已上线 · 辅助功能</span>
        <h3>代理流量监控</h3>
        <p>查看 Clash/Mihomo 的代理与直连流量。</p>
      </a>
      <div class="feature-card disabled" aria-disabled="true">
        <span class="feature-status">Phase 2</span>
        <h3>用量统计</h3>
        <p>Token、成本、性能与数据质量统计。</p>
      </div>
      <div class="feature-card disabled" aria-disabled="true">
        <span class="feature-status">Phase 4</span>
        <h3>自动任务</h3>
        <p>多步骤提示词、定时计划与恢复策略。</p>
      </div>
      <div class="feature-card disabled" aria-disabled="true">
        <span class="feature-status">Phase 3</span>
        <h3>运行中心</h3>
        <p>实时输出、审批、取消与断线恢复。</p>
      </div>
      <div class="feature-card disabled" aria-disabled="true">
        <span class="feature-status">Phase 1 · P1-14</span>
        <h3>设置</h3>
        <p>管理本地索引、数据保留与功能偏好。</p>
      </div>
    </section>
  </main>
</template>
