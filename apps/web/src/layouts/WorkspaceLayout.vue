<script setup lang="ts">
// 工作区布局壳
// 左侧栏（约 260px，会话列表/功能入口）+ 右侧主区
</script>

<template>
  <div class="workspace-layout">
    <aside class="sidebar">
      <slot name="sidebar" />
    </aside>
    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.workspace-layout {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: 260px;
  border-right: 1px solid #e4e7ed;
  background-color: #f5f7fa;
  overflow-y: auto;
}

.main-content {
  flex: 1;
  overflow-y: auto;
}
</style>
