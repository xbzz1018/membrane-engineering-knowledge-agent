<script setup lang="ts">
import { ChatDotRound, Connection, Delete, Promotion } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { nextTick, ref } from 'vue'

import { streamSse } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import { useSessionStore } from '../stores/session'
import type { SourceRef } from '../types/domain'

interface Message { role: 'user' | 'assistant'; content: string; sources?: SourceRef[]; streaming?: boolean }

const session = useSessionStore()
const sessionId = ref(`web-${Date.now()}`)
const input = ref('')
const sending = ref(false)
const messages = ref<Message[]>([])
const scroll = ref<HTMLElement>()

async function send() {
  const question = input.value.trim()
  if (!question || sending.value) return
  messages.value.push({ role: 'user', content: question })
  const answer: Message = { role: 'assistant', content: '', sources: [], streaming: true }
  messages.value.push(answer)
  input.value = ''
  sending.value = true
  try {
    await streamSse('/api/v1/chat/stream', {
      method: 'POST', body: JSON.stringify({ project_id: session.currentProjectId, session_id: sessionId.value, message: question }),
    }, (event) => {
      if (event.type === 'token') answer.content += event.content
      if (event.type === 'sources') answer.sources = event.sources
    })
    answer.streaming = false
  } catch (error) {
    answer.streaming = false
    answer.content ||= '问答请求未完成。'
    ElMessage.error(error instanceof Error ? error.message : '问答失败')
  } finally {
    sending.value = false
    await nextTick(); scroll.value?.scrollTo({ top: scroll.value.scrollHeight, behavior: 'smooth' })
  }
}

function newSession() { messages.value = []; sessionId.value = `web-${Date.now()}` }
</script>

<template>
  <PageHeader title="知识问答" description="KnowledgeAgent 会选择资料、膜材、价格或 Evidence 工具，并返回可追溯来源">
    <el-button :icon="Delete" @click="newSession">新建会话</el-button>
  </PageHeader>
  <div class="chat-shell section">
    <div ref="scroll" class="chat-messages">
      <div v-if="!messages.length" class="chat-empty">
        <span><ChatDotRound /></span><h2>查询当前项目的工程知识</h2><p>例如：定位 PTFE 规格来源，或比较资料中的设计版本。</p>
        <div><el-button plain @click="input='当前项目使用了哪些膜材型号？'">膜材型号</el-button><el-button plain @click="input='查找最近版本的设计资料'">设计版本</el-button><el-button plain @click="input='历史价格记录的单位和日期是否可比？'">价格可比性</el-button></div>
      </div>
      <article v-for="(message,index) in messages" :key="index" class="chat-message" :class="message.role">
        <div class="chat-avatar"><el-icon><component :is="message.role === 'user' ? Promotion : Connection" /></el-icon></div>
        <div class="chat-bubble"><div class="chat-role">{{ message.role === 'user' ? '你' : 'KnowledgeAgent' }}</div><p>{{ message.content }}<span v-if="message.streaming" class="cursor" /></p>
          <div v-if="message.sources?.length" class="source-list"><strong>引用来源</strong><button v-for="source in message.sources" :key="source.source_id" type="button"><span>{{ source.title }}</span><small>{{ source.location || source.source_type }} · V{{ source.version || '-' }}</small><code>{{ source.source_id }}</code></button></div>
        </div>
      </article>
    </div>
    <div class="chat-input"><el-input v-model="input" type="textarea" :rows="2" resize="none" maxlength="4000" show-word-limit placeholder="输入工程资料问题，Enter 发送，Shift+Enter 换行" @keydown.enter.exact.prevent="send" /><el-button type="primary" :icon="Promotion" :loading="sending" @click="send">发送</el-button></div>
  </div>
</template>

<style scoped>
.chat-shell{height:calc(100vh - 165px);min-height:560px;display:grid;grid-template-rows:1fr auto;overflow:hidden}.chat-messages{overflow:auto;padding:28px clamp(18px,4vw,60px)}.chat-empty{height:100%;display:flex;align-items:center;justify-content:center;flex-direction:column;text-align:center;color:#687784}.chat-empty>span{width:54px;height:54px;display:grid;place-items:center;border-radius:8px;background:#e7f5f1;color:#0f8f7a;font-size:27px}.chat-empty h2{margin:16px 0 7px;color:#1d2935;font-size:20px}.chat-empty p{margin:0 0 20px}.chat-message{display:grid;grid-template-columns:36px minmax(0,1fr);gap:12px;margin-bottom:26px}.chat-avatar{width:36px;height:36px;display:grid;place-items:center;border-radius:5px;background:#17212b;color:#fff}.chat-message.user .chat-avatar{background:#0f8f7a}.chat-role{font-size:12px;font-weight:700;color:#687784}.chat-bubble>p{margin:6px 0 0;line-height:1.8;white-space:pre-wrap}.source-list{margin-top:16px;padding:12px;background:#f5f8f7;border-left:3px solid #0f8f7a}.source-list>strong{display:block;font-size:12px;margin-bottom:8px}.source-list button{width:100%;border:0;border-top:1px solid #dfe8e5;background:transparent;padding:9px 0;display:grid;grid-template-columns:minmax(0,1fr) auto;text-align:left;gap:3px 12px;cursor:pointer}.source-list small,.source-list code{color:#687784;font-size:11px}.source-list code{grid-column:1/-1}.chat-input{padding:14px 18px;border-top:1px solid #dce3e8;display:grid;grid-template-columns:minmax(0,1fr) 92px;gap:12px;background:#fff}.cursor{display:inline-block;width:7px;height:14px;margin-left:3px;background:#0f8f7a;animation:blink 1s infinite}@keyframes blink{50%{opacity:.2}}@media(max-width:600px){.chat-input{grid-template-columns:1fr}.chat-input .el-button{width:100%}.chat-empty div{display:none}}
</style>
