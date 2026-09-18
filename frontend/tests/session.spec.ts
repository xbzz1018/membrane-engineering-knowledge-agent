import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { TOKEN_KEY } from '../src/api/client'
import { useSessionStore } from '../src/stores/session'

describe('session store', () => {
  beforeEach(() => {
    sessionStorage.clear()
    setActivePinia(createPinia())
  })

  it('starts unauthenticated without a token', () => {
    const store = useSessionStore()
    expect(store.authenticated).toBe(false)
  })

  it('clears credentials and project on logout', () => {
    sessionStorage.setItem(TOKEN_KEY, 'test-token')
    sessionStorage.setItem('membrane.project_id', 'demo-project')
    const store = useSessionStore()
    store.logout()
    expect(store.authenticated).toBe(false)
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(sessionStorage.getItem('membrane.project_id')).toBeNull()
  })
})
