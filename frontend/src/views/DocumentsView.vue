<script setup lang="ts">
import { DocumentAdd, Refresh, Search, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { api } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import StatusTag from '../components/StatusTag.vue'
import { useSessionStore } from '../stores/session'
import type { DocumentItem } from '../types/domain'

const session = useSessionStore()
const loading = ref(false)
const documents = ref<DocumentItem[]>([])
const query = ref('')
const uploadOpen = ref(false)
const evidenceOpen = ref(false)
const evidence = ref<any[]>([])
const activeDocument = ref<DocumentItem | null>(null)
const selected = ref<DocumentItem[]>([])
const file = ref<File | null>(null)
const upload = reactive({ classification: 'public', parseMethod: 'auto', version: 1 })

const filtered = computed(() => documents.value.filter((item) => item.filename.toLowerCase().includes(query.value.toLowerCase())))

async function load() {
  loading.value = true
  try {
    documents.value = (await api.get('/api/v1/documents', { params: { project_id: session.currentProjectId } })).data
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '资料加载失败') }
  finally { loading.value = false }
}

function chooseFile(item: UploadFile) { file.value = item.raw || null }

async function submitUpload() {
  if (!file.value) return ElMessage.warning('请选择文件')
  const form = new FormData()
  form.append('file', file.value)
  form.append('project_id', session.currentProjectId)
  form.append('data_classification', upload.classification)
  form.append('parse_method', upload.parseMethod)
  form.append('version', String(upload.version))
  try {
    await api.post('/api/v1/documents/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } })
    ElMessage.success('资料已上传')
    uploadOpen.value = false
    file.value = null
    await load()
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '上传失败') }
}

async function indexDocument(item: DocumentItem) {
  try {
    const { data } = await api.post(`/api/v1/documents/${item.id}/index`)
    ElMessage.success(data.workflow_id ? '已提交解析工作流' : '资料索引完成')
    await load()
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '索引失败') }
}

async function batchIndex() {
  if (!selected.value.length) return ElMessage.warning('请选择资料')
  await ElMessageBox.confirm(`将 ${selected.value.length} 份资料提交批量导入？`, '批量导入', { type: 'warning' })
  try {
    await api.post('/api/v1/batch-imports', {
      project_id: session.currentProjectId,
      document_ids: selected.value.map((item) => item.id),
    })
    ElMessage.success('批量导入已提交')
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '批量提交失败') }
}

async function showEvidence(item: DocumentItem) {
  activeDocument.value = item
  evidenceOpen.value = true
  evidence.value = []
  try { evidence.value = (await api.get(`/api/v1/documents/${item.id}/evidence`)).data }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : 'Evidence加载失败') }
}

onMounted(load)
</script>

<template>
  <PageHeader title="工程资料" description="上传、解析并核对项目资料的 Evidence 与业务版本">
    <el-button :icon="Upload" :disabled="!selected.length" @click="batchIndex">批量导入</el-button>
    <el-button type="primary" :icon="DocumentAdd" @click="uploadOpen = true">上传资料</el-button>
  </PageHeader>
  <section class="section">
    <div class="section__body">
      <div class="toolbar">
        <el-input v-model="query" :prefix-icon="Search" clearable placeholder="按文件名筛选" style="width: 280px" />
        <span class="muted">共 {{ filtered.length }} 份资料</span><span class="spacer" />
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
      <el-table v-loading="loading" :data="filtered" row-key="id" table-layout="fixed" @selection-change="selected = $event">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="filename" label="文件" min-width="250" show-overflow-tooltip />
        <el-table-column prop="version" label="版本" width="76"><template #default="scope">V{{ scope.row.version }}</template></el-table-column>
        <el-table-column prop="data_classification" label="分级" width="90"><template #default="scope"><StatusTag :status="scope.row.data_classification" /></template></el-table-column>
        <el-table-column prop="parse_method" label="解析方式" width="90" />
        <el-table-column prop="parser" label="解析器" width="130" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="110"><template #default="scope"><StatusTag :status="scope.row.status" /></template></el-table-column>
        <el-table-column prop="sha256" label="SHA-256" min-width="150"><template #default="scope"><span class="mono">{{ scope.row.sha256.slice(0, 12) }}…</span></template></el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="showEvidence(scope.row)">Evidence</el-button>
            <el-button link :disabled="scope.row.status === 'indexing'" @click="indexDocument(scope.row)">{{ scope.row.status === 'indexed' ? '重新索引' : '索引' }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>

  <el-dialog v-model="uploadOpen" title="上传工程资料" width="520px">
    <el-form label-position="top">
      <el-form-item label="文件">
        <el-upload drag :auto-upload="false" :limit="1" :on-change="chooseFile" :on-remove="() => file = null" accept=".pdf,.docx,.xlsx,.xlsm,.txt,.md">
          <el-icon size="30"><Upload /></el-icon><div>拖放文件到此处，或点击选择</div><small class="muted">PDF、DOCX、XLSX，最大 25MB</small>
        </el-upload>
      </el-form-item>
      <div class="form-grid">
        <el-form-item label="资料分级"><el-select v-model="upload.classification"><el-option label="公开" value="public" /><el-option label="内部" value="internal" /><el-option label="受限" value="restricted" /></el-select></el-form-item>
        <el-form-item label="解析方式"><el-select v-model="upload.parseMethod"><el-option label="自动识别" value="auto" /><el-option label="文本优先" value="text" /><el-option label="强制 OCR" value="ocr" /></el-select></el-form-item>
        <el-form-item label="业务版本"><el-input-number v-model="upload.version" :min="1" /></el-form-item>
      </div>
    </el-form>
    <template #footer><el-button @click="uploadOpen = false">取消</el-button><el-button type="primary" @click="submitUpload">上传</el-button></template>
  </el-dialog>

  <el-drawer v-model="evidenceOpen" :title="activeDocument?.filename || 'Evidence'" size="min(720px, 92vw)">
    <div v-if="!evidence.length" class="empty-line">暂无 Evidence，资料可能尚未完成解析。</div>
    <div v-for="item in evidence" :key="item.id" class="evidence-item">
      <div><span class="mono">{{ item.id }}</span><StatusTag :status="item.status" /></div>
      <small>{{ item.location || `第${item.page_number}页` }} · {{ item.source_kind }} · OCR {{ item.ocr_used ? '是' : '否' }}</small>
      <p>{{ item.text }}</p>
    </div>
  </el-drawer>
</template>

<style scoped>
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }
.evidence-item { padding: 14px 0; border-bottom: 1px solid #e2e7eb; }
.evidence-item > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.evidence-item small { display: block; color: #687784; margin-top: 7px; }
.evidence-item p { margin: 10px 0 0; line-height: 1.7; white-space: pre-wrap; }
@media (max-width: 520px) { .form-grid { grid-template-columns: 1fr; } }
</style>
