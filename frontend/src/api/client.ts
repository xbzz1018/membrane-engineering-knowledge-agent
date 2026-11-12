import axios, { AxiosError } from 'axios'

export const TOKEN_KEY = 'membrane.access_token'
export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8080'

export class ApiError extends Error {
  constructor(message: string, public status = 0, public detail: unknown = null) {
    super(message)
  }
}

export const api = axios.create({
  baseURL: apiBaseUrl,
  timeout: Number(import.meta.env.VITE_REQUEST_TIMEOUT_MS || 30000),
})

api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: unknown }>) => {
    const status = error.response?.status || 0
    const detail = error.response?.data?.detail
    const message = typeof detail === 'string' ? detail : error.message || '请求失败'
    if (status === 401) {
      sessionStorage.removeItem(TOKEN_KEY)
      window.dispatchEvent(new CustomEvent('auth-expired'))
    }
    return Promise.reject(new ApiError(message, status, detail))
  },
)

export async function streamSse(
  path: string,
  init: RequestInit,
  onEvent: (payload: any) => void,
): Promise<void> {
  const token = sessionStorage.getItem(TOKEN_KEY)
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers || {}),
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new ApiError(payload.detail || `请求失败（${response.status}）`, response.status, payload)
  }
  const reader = response.body?.getReader()
  if (!reader) throw new ApiError('浏览器不支持流式响应')
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const event of events) {
      const line = event.split('\n').find((item) => item.startsWith('data:'))
      if (line) onEvent(JSON.parse(line.slice(5).trim()))
    }
  }
}


export async function downloadMarkdown(path: string, filename: string): Promise<void> {
  const { data } = await api.get<string>(path, { responseType: 'text' })
  const url = URL.createObjectURL(new Blob([data], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function downloadArtifact(path: string, filename: string): Promise<void> {
  const { data } = await api.get<Blob>(path, { responseType: 'blob' })
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
