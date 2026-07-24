<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

function goRole(role: string) {
  localStorage.setItem('token', 'dev-token')
  localStorage.setItem('role', role)
  router.push('/role-select')
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">数学垂类大模型</h1>
      <p class="login-sub">M0-M1 智能测试平台</p>

      <el-form label-position="top" class="login-form">
        <el-form-item label="手机号">
          <el-input placeholder="请输入 11 位手机号" maxlength="11" />
        </el-form-item>
        <el-form-item label="验证码">
          <div class="code-row">
            <el-input placeholder="6 位验证码" maxlength="6" />
            <el-button type="primary" plain>获取验证码</el-button>
          </div>
          <div class="code-hint">开发环境固定 <b>123456</b></div>
        </el-form-item>
        <el-button type="primary" class="login-btn" @click="goRole('student')">登 录</el-button>
      </el-form>

      <div class="role-shortcuts">
        <span>快速进入：</span>
        <el-button text type="primary" @click="goRole('student')">学生</el-button>
        <el-button text type="primary" @click="goRole('teacher')">教师</el-button>
        <el-button text type="primary" @click="goRole('research')">科研人员</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: #0f172a;
}
.login-card {
  width: 420px;
  padding: 40px;
  background: rgba(15, 23, 42, 0.85);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 16px;
  color: #e2e8f0;
}
.login-title {
  text-align: center;
  font-size: 24px;
  font-weight: 700;
  margin-bottom: 4px;
}
.login-sub {
  text-align: center;
  font-size: 12px;
  color: #64748b;
  letter-spacing: 0.15em;
  margin-bottom: 32px;
}
.login-form {
  margin-bottom: 20px;
}
.code-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.code-hint {
  font-size: 12px;
  color: #64748b;
  margin-top: 4px;
}
.code-hint b { color: #818cf8; }
.login-btn {
  width: 100%;
  margin-top: 8px;
}
.role-shortcuts {
  text-align: center;
  font-size: 13px;
  color: #64748b;
}
</style>
