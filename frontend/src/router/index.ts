import { createRouter, createWebHistory } from 'vue-router'

import AppLayout from '../layouts/AppLayout.vue'
import { useSessionStore } from '../stores/session'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', redirect: '/dashboard' },
        { path: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '项目总览' } },
        { path: 'documents', component: () => import('../views/DocumentsView.vue'), meta: { title: '工程资料' } },
        { path: 'materials', component: () => import('../views/MaterialsView.vue'), meta: { title: '膜材规格' } },
        { path: 'prices', component: () => import('../views/PricesView.vue'), meta: { title: '历史价格' } },
        { path: 'chat', component: () => import('../views/ChatView.vue'), meta: { title: '知识问答' } },
        { path: 'reviews', component: () => import('../views/ReviewsView.vue'), meta: { title: '资料包审查' } },
        { path: 'reviews/:reviewId', component: () => import('../views/ReviewDetailView.vue'), meta: { title: '审查详情' } },
        { path: 'issues', component: () => import('../views/IssuesView.vue'), meta: { title: '问题单' } },
        { path: 'batches', component: () => import('../views/BatchesView.vue'), meta: { title: '批量导入' } },
        { path: 'memories', component: () => import('../views/MemoriesView.vue'), meta: { title: '长期记忆' } },
        { path: 'agents', component: () => import('../views/AgentsView.vue'), meta: { title: '智能体运行' } },
        { path: 'admin', component: () => import('../views/AdminView.vue'), meta: { title: '系统管理', roles: ['admin'] } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const session = useSessionStore()
  if (to.meta.public) return session.authenticated ? '/dashboard' : true
  if (!session.authenticated) return `/login?redirect=${encodeURIComponent(to.fullPath)}`
  if (!session.ready) {
    try {
      await session.bootstrap()
    } catch {
      session.logout()
      return '/login'
    }
  }
  const roles = to.meta.roles as string[] | undefined
  if (roles && !roles.includes(session.principal?.role || '')) return '/dashboard'
  return true
})

window.addEventListener('auth-expired', () => {
  const session = useSessionStore()
  session.logout()
  void router.replace('/login')
})

export default router
