<script setup lang="ts">
import { Aim, Connection, DocumentChecked, Lock, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useSessionStore } from '../stores/session'

const session = useSessionStore()
const router = useRouter()
const route = useRoute()
const loading = ref(false)
const form = reactive({ username: 'admin', password: '' })

async function submit() {
  if (!form.username || !form.password) return ElMessage.warning('请输入用户名和密码')
  loading.value = true
  try {
    await session.login(form.username, form.password)
    await router.replace(String(route.query.redirect || '/dashboard'))
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-context">
      <div class="login-brand"><span><Aim /></span><strong>膜构智审</strong></div>
      <div class="login-copy">
        <p>企业工程资料工作台</p>
        <h1>让设计、膜材与价格资料<br>在同一条证据链上完成审查</h1>
      </div>
      <div class="login-points">
        <div><el-icon><DocumentChecked /></el-icon><span><strong>可追溯资料</strong><small>保留文件、页码、版本和 Evidence ID</small></span></div>
        <div><el-icon><Connection /></el-icon><span><strong>三领域协同</strong><small>Supervisor 调度设计、膜材和价格审查</small></span></div>
      </div>
      <small class="login-boundary">企业项目空间 · 全流程留痕 · 审查结果可追溯</small>
    </section>
    <section class="login-panel">
      <div class="login-form">
        <div class="login-form__heading"><span>企业账号</span><h2>登录工作台</h2><p>使用已分配的内部账号访问项目资料。</p></div>
        <el-form label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input v-model="form.username" size="large" autocomplete="username" :prefix-icon="User" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" size="large" type="password" show-password autocomplete="current-password" :prefix-icon="Lock" @keyup.enter="submit" />
          </el-form-item>
          <el-button type="primary" size="large" class="login-submit" :loading="loading" @click="submit">进入工作台</el-button>
        </el-form>
        <div class="login-security"><el-icon><Lock /></el-icon><span>登录身份决定项目范围和可用操作，页面不会保存模型 API Key。</span></div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-page { min-height: 100vh; display: grid; grid-template-columns: minmax(420px, 1.1fr) minmax(420px, .9fr); background: #fff; }
.login-context { position: relative; min-height: 100vh; padding: 54px clamp(46px, 7vw, 110px); color: #fff; background: #17212b; display: flex; flex-direction: column; }
.login-context::after { content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 4px; background: #0f8f7a; }
.login-brand { display: flex; align-items: center; gap: 12px; font-size: 19px; }
.login-brand > span { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 6px; background: #0f8f7a; }
.login-copy { margin: auto 0 60px; }
.login-copy p { margin: 0 0 18px; color: #74c8b7; font-size: 14px; font-weight: 650; }
.login-copy h1 { margin: 0; max-width: 720px; font-size: clamp(34px, 4vw, 54px); line-height: 1.3; letter-spacing: 0; }
.login-points { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 20px; border-top: 1px solid #32414d; padding-top: 26px; }
.login-points > div { display: flex; gap: 12px; }
.login-points .el-icon { color: #74c8b7; font-size: 22px; }
.login-points span { display: flex; flex-direction: column; gap: 5px; }
.login-points small { color: #9aabb8; line-height: 1.55; }
.login-boundary { margin-top: 30px; color: #7f909c; }
.login-panel { display: grid; place-items: center; padding: 40px; }
.login-form { width: min(400px, 100%); }
.login-form__heading { margin-bottom: 32px; }
.login-form__heading > span { color: #0f8f7a; font-size: 12px; font-weight: 700; }
.login-form h2 { margin: 8px 0; font-size: 28px; letter-spacing: 0; }
.login-form p { margin: 0; color: #687784; }
.login-submit { width: 100%; margin-top: 8px; }
.login-security { margin-top: 24px; padding: 12px; display: flex; gap: 9px; color: #687784; background: #f4f7f6; font-size: 12px; line-height: 1.55; }
@media (max-width: 860px) { .login-page { grid-template-columns: 1fr; } .login-context { display: none; } .login-panel { min-height: 100vh; padding: 26px; } }
</style>
