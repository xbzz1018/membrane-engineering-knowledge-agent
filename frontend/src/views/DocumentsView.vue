<script setup lang="ts">
import { DocumentAdd, Refresh, Search, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { api, downloadMarkdown } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import StatusTag from '../components/StatusTag.vue'
import { useSessionStore } from '../stores/session'
import type { DocumentItem, SourceRef } from '../types/domain'

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
type DocType = 'design' | 'material' | 'price' | 'other'
interface BusinessMetadata {
  engineering_model: string
  applicable_revision: string
  document_type: DocType
  effective_from: string | null
  effective_to: string | null
  source_note: string
  declared_by?: string
  updated_at?: string
}
const metadataOpen = ref(false)
const metadataLoading = ref(false)
const metadataSaving = ref(false)
const metadataReady = ref(false)
const metadataError = ref('')
const metadataDocument = ref<DocumentItem | null>(null)
const metadata = reactive<BusinessMetadata>({ engineering_model: '', applicable_revision: '', document_type: 'other', effective_from: null, effective_to: null, source_note: '' })
const canDeclare = computed(() => ['admin', 'design_engineer', 'material_procurement'].includes(session.principal?.role || ''))
const businessSearch = reactive({ query: '', engineering_model: '', applicable_revision: '', document_type: '' as DocType | '', effective_on: null as string | null, upload_version: undefined as number | undefined })
const searchLoading = ref(false)
const searched = ref(false)
const searchError = ref('')
const searchSources = ref<SourceRef[]>([])
let projectEpoch = 0
let searchRequest = 0
let metadataRequest = 0
let evidenceRequest = 0
let listRequest = 0
const docTypes = [{ value: 'design', label: '设计资料' }, { value: 'material', label: '材料规格' }, { value: 'price', label: '历史价格' }, { value: 'other', label: '其他' }]

const filtered = computed(() => documents.value.filter((item) => item.filename.toLowerCase().includes(query.value.toLowerCase())))

async function load() {
  const project = session.currentProjectId
  const requestId = ++listRequest
  loading.value = true
  try {
    const response = await api.get<DocumentItem[]>('/api/v1/documents', { params: { project_id: project } })
    if (requestId === listRequest && project === session.currentProjectId) documents.value = response.data
  } catch (error) { if (requestId === listRequest) ElMessage.error(error instanceof Error ? error.message : '资料加载失败') }
  finally { if (requestId === listRequest) loading.value = false }
}

async function editMetadata(item: DocumentItem) {
  const requestId = ++metadataRequest
  const epoch = projectEpoch
  metadataDocument.value = item
  metadataOpen.value = true
  metadataLoading.value = true
  metadataReady.value = false
  metadataError.value = ''
  Object.assign(metadata, { engineering_model: '', applicable_revision: '', document_type: 'other', effective_from: null, effective_to: null, source_note: '', declared_by: '', updated_at: '' })
  try {
    const [doc, declared] = await Promise.all([
      api.get<DocumentItem>(`/api/v1/documents/${item.id}`),
      api.get<{ business_metadata: BusinessMetadata | null }>(`/api/v1/documents/${item.id}/business-metadata`),
    ])
    if (epoch !== projectEpoch || requestId !== metadataRequest) return
    metadataDocument.value = doc.data
    if (declared.data.business_metadata) Object.assign(metadata, declared.data.business_metadata)
    metadataReady.value = true
  } catch (error) { if (requestId === metadataRequest) metadataError.value = error instanceof Error ? error.message : '业务条件加载失败' }
  finally { if (requestId === metadataRequest) metadataLoading.value = false }
}

async function saveMetadata() {
  const doc = metadataDocument.value
  if (!doc || !metadataReady.value || metadataSaving.value) return
  if (!metadata.engineering_model.trim() || !metadata.applicable_revision.trim() || !metadata.source_note.trim()) return ElMessage.warning('请填写型号、适用版次和声明依据')
  if (metadata.effective_to && (!metadata.effective_from || metadata.effective_to < metadata.effective_from)) return ElMessage.warning('结束日期须不早于开始日期')
  const epoch = projectEpoch
  metadataSaving.value = true
  metadataError.value = ''
  try {
    await api.put(`/api/v1/documents/${doc.id}/business-metadata`, {
      engineering_model: metadata.engineering_model.trim(), applicable_revision: metadata.applicable_revision.trim(),
      document_type: metadata.document_type, effective_from: metadata.effective_from || null, effective_to: metadata.effective_to || null,
      source_note: metadata.source_note.trim(), expected_lock_version: doc.lock_version,
    })
    if (epoch !== projectEpoch) return
    ElMessage.success('业务条件已保存')
    metadataOpen.value = false
    await load()
  } catch (error) {
    if (epoch !== projectEpoch) return
    metadataError.value = error instanceof Error ? error.message : '业务条件保存失败'
    // A failed/conflicting save requires a fresh version before retry.
    metadataReady.value = false
  } finally { metadataSaving.value = false }
}

async function searchDocuments() {
  const requestId = ++searchRequest
  const project = session.currentProjectId
  const filters = Object.fromEntries(Object.entries(businessSearch).filter(([key, value]) => key !== 'query' && value !== '' && value != null))
  searchSources.value = []
  searchError.value = ''
  searched.value = false
  if (!businessSearch.query.trim() && !Object.keys(filters).length) return ElMessage.warning('请输入检索内容或至少一个业务条件')
  searchLoading.value = true
  try {
    const response = await api.post<{ sources: SourceRef[] }>('/api/v1/documents/search', { project_id: project, query: businessSearch.query.trim(), filters, limit: 8 })
    if (requestId !== searchRequest || project !== session.currentProjectId) return
    searchSources.value = response.data.sources
    searched.value = true
  } catch (error) { if (requestId === searchRequest) searchError.value = error instanceof Error ? error.message : '检索失败' }
  finally { if (requestId === searchRequest) searchLoading.value = false }
}

function sourceDocument(source: SourceRef) { return documents.value.find(item => item.id === source.source_id.split(':')[0]) }

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
  const requestId = ++evidenceRequest
  activeDocument.value = item
  evidenceOpen.value = true
  evidence.value = []
  try {
    const response = await api.get(`/api/v1/documents/${item.id}/evidence`)
    if (requestId === evidenceRequest) evidence.value = response.data
  } catch (error) { if (requestId === evidenceRequest) ElMessage.error(error instanceof Error ? error.message : 'Evidence加载失败') }
}

async function exportMarkdown(item: DocumentItem) {
  try { await downloadMarkdown(`/api/v1/documents/${item.id}/markdown`, `${item.filename}.md`) }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : '资料导出失败') }
}

onMounted(load)
watch(() => session.currentProjectId, () => {
  projectEpoch += 1
  searchRequest += 1
  metadataRequest += 1
  evidenceRequest += 1
  documents.value = []
  selected.value = []
  evidence.value = []
  evidenceOpen.value = false
  metadataOpen.value = false
  metadataReady.value = false
  metadataLoading.value = false
  uploadOpen.value = false
  file.value = null
  searchLoading.value = false
  searched.value = false
  searchSources.value = []
  searchError.value = ''
  void load()
})
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
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="scope">
            <el-button link :disabled="scope.row.status!=='indexed'" @click="exportMarkdown(scope.row)">Markdown</el-button><el-button link type="primary" @click="showEvidence(scope.row)">Evidence</el-button>
            <el-button v-if="canDeclare" link type="primary" @click="editMetadata(scope.row)">业务条件</el-button>
            <el-button link :disabled="scope.row.status === 'indexing'" @click="indexDocument(scope.row)">{{ scope.row.status === 'indexed' ? '重新索引' : '索引' }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>

  <section class="section" aria-label="条件检索">
    <div class="section__body">
      <h3>条件检索</h3>
      <el-form label-position="top" @submit.prevent="searchDocuments">
        <div class="search-grid">
          <el-form-item label="检索内容"><el-input v-model="businessSearch.query" clearable placeholder="例如：名义厚度、适用要求" /></el-form-item>
          <el-form-item label="工程型号"><el-input v-model="businessSearch.engineering_model" clearable placeholder="PTFE-502" /></el-form-item>
          <el-form-item label="适用版次"><el-input v-model="businessSearch.applicable_revision" clearable placeholder="R1" /></el-form-item>
          <el-form-item label="资料类型"><el-select v-model="businessSearch.document_type" clearable><el-option v-for="item in docTypes" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
          <el-form-item label="业务生效日期"><el-date-picker v-model="businessSearch.effective_on" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" /></el-form-item>
          <el-form-item label="上传版本"><el-input-number v-model="businessSearch.upload_version" :min="1" :precision="0" placeholder="不限" /></el-form-item>
        </div>
        <el-button type="primary" :icon="Search" :loading="searchLoading" native-type="submit">检索资料</el-button>
        <small class="muted search-note">按已声明的业务条件精确筛选，当前检索公开资料。</small>
      </el-form>
      <el-alert v-if="searchError" :title="searchError" type="error" :closable="false" show-icon class="result-alert" />
      <div v-if="searched && !searchSources.length" class="empty-line" role="status">没有符合条件的可引用资料，请核对型号、版次和生效日期。</div>
      <div v-for="source in searchSources" :key="source.source_id" class="evidence-item">
        <div><strong>{{ source.title }}</strong><el-button v-if="sourceDocument(source)" link type="primary" @click="showEvidence(sourceDocument(source)!)">查看证据</el-button></div>
        <small>{{ source.location }} · 上传版本 {{ source.version }} · {{ source.source_id }}</small>
        <p>{{ source.excerpt }}</p>
      </div>
    </div>
  </section>

  <el-dialog v-model="metadataOpen" title="资料业务条件" width="min(640px, 94vw)" :close-on-click-modal="!metadataSaving" :show-close="!metadataSaving" :close-on-press-escape="!metadataSaving">
    <div v-loading="metadataLoading">
      <p class="muted">{{ metadataDocument?.filename }} · 用户声明</p>
      <el-alert v-if="metadataError" :title="metadataError" type="error" :closable="false" show-icon />
      <el-form label-position="top" :disabled="!metadataReady || metadataSaving">
        <div class="form-grid">
          <el-form-item label="工程型号" required><el-input v-model="metadata.engineering_model" maxlength="128" /></el-form-item>
          <el-form-item label="适用版次" required><el-input v-model="metadata.applicable_revision" maxlength="128" /></el-form-item>
          <el-form-item label="资料类型" required><el-select v-model="metadata.document_type"><el-option v-for="item in docTypes" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
          <el-form-item label="生效开始日期"><el-date-picker v-model="metadata.effective_from" type="date" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item>
          <el-form-item label="生效结束日期"><el-date-picker v-model="metadata.effective_to" type="date" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item>
        </div>
        <el-form-item label="声明依据" required><el-input v-model="metadata.source_note" type="textarea" :rows="3" maxlength="1000" show-word-limit placeholder="例如：规格书第2页，产品型号与适用修订说明" /></el-form-item>
      </el-form>
      <small v-if="metadata.declared_by" class="muted">声明人 {{ metadata.declared_by }} · {{ metadata.updated_at }}</small>
    </div>
    <template #footer>
      <el-button :disabled="metadataSaving || metadataLoading" @click="metadataDocument && editMetadata(metadataDocument)">重新加载</el-button>
      <el-button :disabled="metadataSaving" @click="metadataOpen = false">取消</el-button>
      <el-button type="primary" :disabled="!metadataReady" :loading="metadataSaving" @click="saveMetadata">保存条件</el-button>
    </template>
  </el-dialog>

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
.search-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 14px; }
.search-note { margin-left: 12px; }
.result-alert { margin-top: 16px; }
.evidence-item { padding: 14px 0; border-bottom: 1px solid #e2e7eb; }
.evidence-item > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.evidence-item small { display: block; color: #687784; margin-top: 7px; }
.evidence-item p { margin: 10px 0 0; line-height: 1.7; white-space: pre-wrap; }
@media (max-width: 760px) { .search-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 520px) { .form-grid, .search-grid { grid-template-columns: 1fr; } .search-note { display: block; margin: 10px 0; } }
</style>
