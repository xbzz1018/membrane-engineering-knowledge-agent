<script setup lang="ts">
import {
  Aim, Box, ChatDotRound, Coin, Collection, DataAnalysis, Document, Expand, Fold,
  Grid, List, Memo, Operation, Setting, SwitchButton, UploadFilled, User,
} from '@element-plus/icons-vue'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useSessionStore } from '../stores/session'

const session = useSessionStore()
const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const mobileOpen = ref(false)

const title = computed(() => String(route.meta.title || '膜构智审'))
const roleLabel = computed(() => ({
  admin: '系统管理员', design_engineer: '设计工程师', material_procurement: '膜材采购', reviewer: '项目审核人',
}[session.principal?.role || 'admin']))

const menus = computed(() => [
  { path: '/dashboard', label: '项目总览', icon: Grid },
  { path: '/documents', label: '工程资料', icon: Document },
  { path: '/materials', label: '膜材规格', icon: Box },
  { path: '/prices', label: '历史价格', icon: Coin },
  { path: '/chat', label: '知识问答', icon: ChatDotRound },
  { path: '/reviews', label: '资料包审查', icon: Operation },
  { path: '/issues', label: '问题单', icon: List },
  { path: '/batches', label: '批量导入', icon: UploadFilled },
  { path: '/memories', label: '长期记忆', icon: Memo },
  { path: '/agents', label: '智能体运行', icon: DataAnalysis },
  ...(session.principal?.role === 'admin' ? [{ path: '/admin', label: '系统管理', icon: Setting }] : []),
])

function go(path: string) {
  mobileOpen.value = false
  void router.push(path)
}

function logout() {
  session.logout()
  void router.replace('/login')
}
</script>

<template>
  <div class="app-shell" :class="{ 'is-collapsed': collapsed }">
    <aside class="app-sidebar" :class="{ 'is-mobile-open': mobileOpen }">
      <button class="brand" type="button" @click="go('/dashboard')">
        <span class="brand__mark"><Aim /></span>
        <span v-if="!collapsed" class="brand__text"><strong>膜构智审</strong><small>工程资料审查平台</small></span>
      </button>
      <nav class="nav-list" aria-label="主导航">
        <button
          v-for="item in menus" :key="item.path" type="button" class="nav-item"
          :class="{ active: route.path === item.path || (item.path === '/reviews' && route.path.startsWith('/reviews/')) }"
          :title="collapsed ? item.label : undefined" @click="go(item.path)"
        >
          <el-icon><component :is="item.icon" /></el-icon><span v-if="!collapsed">{{ item.label }}</span>
        </button>
      </nav>
      <button class="sidebar-collapse" type="button" @click="collapsed = !collapsed">
        <el-icon><component :is="collapsed ? Expand : Fold" /></el-icon><span v-if="!collapsed">收起导航</span>
      </button>
    </aside>
    <button v-if="mobileOpen" class="mobile-scrim" aria-label="关闭菜单" @click="mobileOpen = false" />

    <main class="app-main">
      <header class="topbar">
        <div class="topbar__left">
          <el-button class="mobile-menu" text :icon="Collection" @click="mobileOpen = true" />
          <div><span class="eyebrow">当前工作区</span><strong>{{ title }}</strong></div>
        </div>
        <div class="topbar__right">
          <el-select
            :model-value="session.currentProjectId" class="project-select" placeholder="选择项目"
            @change="session.selectProject"
          >
            <el-option v-for="project in session.projects" :key="project.id" :label="project.name" :value="project.id" />
          </el-select>
          <div class="user-summary"><el-icon><User /></el-icon><span><strong>{{ session.principal?.username }}</strong><small>{{ roleLabel }}</small></span></div>
          <el-tooltip content="退出登录" placement="bottom">
            <el-button circle text :icon="SwitchButton" @click="logout" />
          </el-tooltip>
        </div>
      </header>
      <section class="app-content"><router-view :key="`${route.path}:${session.currentProjectId}`" /></section>
    </main>
  </div>
</template>
