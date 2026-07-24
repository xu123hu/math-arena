<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

function enterRole(role: string) {
  localStorage.setItem('token', 'dev-token')
  localStorage.setItem('role', role)
  router.push(`/${role}`)
}
</script>

<template>
  <div class="role-select-page">
    <div class="role-card-wrap">
      <h1 class="rs-title">选择角色</h1>
      <p class="rs-sub">M0-M1 智能测试平台</p>
      <div class="role-cards">
        <div class="role-card" @click="enterRole('student')">
          <span class="role-icon">🎓</span>
          <h3>学生</h3>
          <p>苏格拉底式启发引导，精准攻克薄弱知识点</p>
        </div>
        <div class="role-card" @click="enterRole('teacher')">
          <span class="role-icon">📚</span>
          <h3>教师</h3>
          <p>智能备课、精准学情诊断与教学策略调整</p>
        </div>
        <div class="role-card" @click="enterRole('research')">
          <span class="role-icon">🔬</span>
          <h3>科研人员</h3>
          <p>论文解析、LaTeX 排版与教育数据挖掘</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.role-select-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: #0f172a;
}
.role-card-wrap {
  text-align: center;
  color: #e2e8f0;
}
.rs-title {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 4px;
}
.rs-sub {
  font-size: 13px;
  color: #64748b;
  letter-spacing: 0.15em;
  margin-bottom: 36px;
}
.role-cards {
  display: flex;
  gap: 16px;
}
.role-card {
  flex: 1;
  padding: 28px 20px;
  background: rgba(30, 41, 59, 0.7);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.3s ease;
  width: 180px;
}
.role-card:hover {
  transform: translateY(-4px);
  border-color: rgba(99, 102, 241, 0.4);
  box-shadow: 0 12px 40px rgba(99, 102, 241, 0.15);
}
.role-icon {
  font-size: 36px;
  display: block;
  margin-bottom: 12px;
}
.role-card h3 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 8px;
}
.role-card p {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.6;
}
</style>
