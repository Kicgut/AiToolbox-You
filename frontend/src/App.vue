<template>
  <div class="shell">
    <header class="topbar">
      <div>
        <h1>AI 编程工作台</h1>
        <p>本地会话、运行与自动化中心</p>
      </div>
      <nav aria-label="主导航">
        <RouterLink to="/">总览</RouterLink>
        <RouterLink to="/sessions">会话</RouterLink>
        <a href="/traffic">代理流量</a>
        <RouterLink to="/statistics">统计</RouterLink>
      </nav>
    </header>
    <RouterView />
  </div>
</template>
