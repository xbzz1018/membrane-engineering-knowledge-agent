import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, TOKEN_KEY } from '../api/client'
import type { Principal, Project } from '../types/domain'

export const useSessionStore = defineStore('session', () => {
  const token = ref(sessionStorage.getItem(TOKEN_KEY) || '')
  const principal = ref<Principal | null>(null)
  const projects = ref<Project[]>([])
  const currentProjectId = ref(sessionStorage.getItem('membrane.project_id') || '')
  const ready = ref(false)

  const authenticated = computed(() => Boolean(token.value))
  const currentProject = computed(() => projects.value.find((item) => item.id === currentProjectId.value) || null)
  const canEditCatalog = computed(() => ['admin', 'material_procurement'].includes(principal.value?.role || ''))
  const canReview = computed(() => ['admin', 'reviewer'].includes(principal.value?.role || ''))

  async function login(username: string, password: string) {
    const { data } = await api.post('/api/v1/auth/login', { username, password })
    token.value = data.access_token
    sessionStorage.setItem(TOKEN_KEY, token.value)
    principal.value = data.principal
    await bootstrap()
  }

  async function bootstrap() {
    if (!token.value) return
    const [me, projectResponse] = await Promise.all([
      api.get<Principal>('/api/v1/auth/me'),
      api.get<Project[]>('/api/v1/projects'),
    ])
    principal.value = me.data
    projects.value = projectResponse.data
    if (!projects.value.some((item) => item.id === currentProjectId.value)) {
      currentProjectId.value = projects.value[0]?.id || ''
    }
    sessionStorage.setItem('membrane.project_id', currentProjectId.value)
    ready.value = true
  }

  function selectProject(projectId: string) {
    if (!projects.value.some((item) => item.id === projectId)) return
    currentProjectId.value = projectId
    sessionStorage.setItem('membrane.project_id', projectId)
  }

  function logout() {
    token.value = ''
    principal.value = null
    projects.value = []
    currentProjectId.value = ''
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem('membrane.project_id')
  }

  return {
    token, principal, projects, currentProjectId, currentProject, ready,
    authenticated, canEditCatalog, canReview, login, bootstrap, selectProject, logout,
  }
})
