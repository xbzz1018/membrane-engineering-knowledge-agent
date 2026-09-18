<script setup lang="ts">
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import StatusTag from '../components/StatusTag.vue'
import { useSessionStore } from '../stores/session'
import type { DocumentItem, ReviewItem } from '../types/domain'

const session = useSessionStore(); const router = useRouter(); const loading = ref(false)
const reviews = ref<ReviewItem[]>([]); const documents = ref<DocumentItem[]>([]); const dialog = ref(false)
const status = ref(''); const form = reactive({ document_ids: [] as string[], review_mode: 'full', question: '比较资料中的设计方案、膜材规格和价格差异' })
const indexedDocuments = computed(() => documents.value.filter((item) => item.status === 'indexed'))

async function load() {
  loading.value = true
  try {
    const [reviewResponse, documentResponse] = await Promise.all([
      api.get('/api/v1/package-reviews', { params: { project_id: session.currentProjectId, status: status.value || undefined } }),
      api.get('/api/v1/documents', { params: { project_id: session.currentProjectId } }),
    ])
    reviews.value = reviewResponse.data; documents.value = documentResponse.data
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '审查列表加载失败') }
  finally { loading.value = false }
}

async function createReview() {
  if (!form.document_ids.length) return ElMessage.warning('请选择至少一份已索引资料')
  await ElMessageBox.confirm(`将以${form.review_mode === 'full' ? '三领域' : '专项'}模式审查 ${form.document_ids.length} 份资料，确认继续？`, '发起资料审查', { type: 'warning' })
  try {
    const { data } = await api.post('/api/v1/package-reviews', { ...form, project_id: session.currentProjectId })
    ElMessage.success(data.status === 'queued' ? '审查工作流已提交' : '审查已完成')
    dialog.value = false
    await router.push(`/reviews/${data.review_id}`)
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '创建审查失败') }
}
onMounted(load)
</script>

<template>
  <PageHeader title="资料包审查" description="由 Supervisor 规划设计、膜材和价格领域审查，并输出证据化问题单">
    <el-button type="primary" :icon="Plus" @click="dialog=true">发起审查</el-button>
  </PageHeader>
  <section class="section"><div class="section__body">
    <div class="toolbar"><el-select v-model="status" clearable placeholder="全部状态" style="width:150px" @change="load"><el-option label="执行中" value="running" /><el-option label="待审批" value="awaiting_approval" /><el-option label="已批准" value="approved" /><el-option label="已退回" value="rejected" /><el-option label="失败" value="failed" /></el-select><span class="muted">{{ reviews.length }} 项审查</span><span class="spacer" /><el-button :icon="Refresh" @click="load">刷新</el-button></div>
    <el-table v-loading="loading" :data="reviews" table-layout="fixed" @row-dblclick="row => router.push(`/reviews/${row.review_id}`)">
      <el-table-column prop="question" label="审查目标" min-width="280" show-overflow-tooltip />
      <el-table-column prop="review_mode" label="模式" width="100"><template #default="scope">{{ scope.row.review_mode === 'focused' ? '专项' : '三领域' }}</template></el-table-column>
      <el-table-column prop="status" label="状态" width="110"><template #default="scope"><StatusTag :status="scope.row.status" /></template></el-table-column>
      <el-table-column prop="issue_count" label="问题单" width="90" /><el-table-column prop="conflict_count" label="冲突" width="80" />
      <el-table-column prop="engine" label="执行引擎" width="110" /><el-table-column prop="created_at" label="创建时间" width="170"><template #default="scope">{{ scope.row.created_at ? new Date(scope.row.created_at).toLocaleString() : '-' }}</template></el-table-column>
      <el-table-column label="操作" width="80" fixed="right"><template #default="scope"><el-button link type="primary" @click="router.push(`/reviews/${scope.row.review_id}`)">查看</el-button></template></el-table-column>
    </el-table>
  </div></section>

  <el-dialog v-model="dialog" title="发起资料包审查" width="620px">
    <el-form label-position="top"><el-form-item label="审查模式"><el-radio-group v-model="form.review_mode"><el-radio-button value="full">三领域正式审查</el-radio-button><el-radio-button value="focused">专项审查</el-radio-button></el-radio-group><small class="form-help">三领域模式固定执行设计、膜材和价格 Worker；专项模式由 Supervisor 从白名单选择。</small></el-form-item>
      <el-form-item label="选择资料"><el-select v-model="form.document_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="选择 1–20 份已索引资料" style="width:100%"><el-option v-for="item in indexedDocuments" :key="item.id" :label="`${item.filename} · V${item.version}`" :value="item.id" /></el-select></el-form-item>
      <el-form-item label="审查目标"><el-input v-model="form.question" type="textarea" :rows="4" maxlength="2000" show-word-limit /></el-form-item>
    </el-form><template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" @click="createReview">确认发起</el-button></template>
  </el-dialog>
</template>
<style scoped>.form-help{display:block;margin-top:8px;color:#687784;line-height:1.5}</style>
