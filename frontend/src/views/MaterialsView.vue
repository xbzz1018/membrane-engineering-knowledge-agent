<script setup lang="ts">
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { api } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import StatusTag from '../components/StatusTag.vue'
import { useSessionStore } from '../stores/session'
import type { CatalogItem, PageResult } from '../types/domain'

const session = useSessionStore()
const loading = ref(false)
const items = ref<CatalogItem[]>([])
const total = ref(0)
const query = ref('')
const status = ref('active')
const dialog = ref(false)
const editing = ref<CatalogItem | null>(null)
const form = reactive<any>({})

function resetForm(item?: CatalogItem) {
  editing.value = item || null
  Object.keys(form).forEach((key) => delete form[key])
  Object.assign(form, item || {
    manufacturer: '', material: '', product_reference: '', specification: '', application: '',
    source_url: '', source_version: '', source_page: 1, source_page_count: 1,
    license: '', retrieved_at: new Date().toISOString(), source_sha256: '', visibility: 'public', synthetic: false,
  })
  dialog.value = true
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get<PageResult<CatalogItem>>('/api/v1/material-specs', {
      params: { project_id: session.currentProjectId, query: query.value, status: status.value, page_size: 100 },
    })
    items.value = data.items
    total.value = data.total
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '规格加载失败') }
  finally { loading.value = false }
}

async function save() {
  try {
    const payload = { ...form }
    if (editing.value) {
      payload.expected_lock_version = editing.value.lock_version
      await api.patch(`/api/v1/material-specs/${editing.value.spec_id}`, payload, { params: { project_id: session.currentProjectId } })
    } else {
      await api.post('/api/v1/material-specs', payload, { params: { project_id: session.currentProjectId } })
    }
    ElMessage.success(editing.value ? '规格已更新' : '规格已新增')
    dialog.value = false
    await load()
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '保存失败') }
}

async function archive(item: CatalogItem) {
  await ElMessageBox.confirm(`确认归档 ${item.product_reference || item.material}？`, '归档规格', { type: 'warning' })
  try {
    await api.post(`/api/v1/material-specs/${item.spec_id}/archive`, { expected_lock_version: item.lock_version }, { params: { project_id: session.currentProjectId } })
    ElMessage.success('规格已归档')
    await load()
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '归档失败') }
}

onMounted(load)
</script>

<template>
  <PageHeader title="膜材规格" description="维护企业级膜材目录，并保留来源、版本和许可信息">
    <el-button v-if="session.canEditCatalog" type="primary" :icon="Plus" @click="resetForm()">新增规格</el-button>
  </PageHeader>
  <section class="section"><div class="section__body">
    <div class="toolbar">
      <el-input v-model="query" :prefix-icon="Search" clearable placeholder="型号、厂家或规格" style="width: 300px" @keyup.enter="load" />
      <el-select v-model="status" style="width: 120px" @change="load"><el-option label="启用" value="active" /><el-option label="已归档" value="archived" /></el-select>
      <el-button @click="load">查询</el-button><span class="muted">{{ total }} 条</span><span class="spacer" /><el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>
    <el-table v-loading="loading" :data="items" table-layout="fixed">
      <el-table-column prop="product_reference" label="型号" width="150" />
      <el-table-column prop="manufacturer" label="厂家" min-width="160" show-overflow-tooltip />
      <el-table-column prop="material" label="膜材" width="110" />
      <el-table-column prop="specification" label="规格" min-width="260" show-overflow-tooltip />
      <el-table-column prop="application" label="适用场景" min-width="150" show-overflow-tooltip />
      <el-table-column prop="source_version" label="来源版本" width="110" />
      <el-table-column prop="visibility" label="分级" width="86"><template #default="scope"><StatusTag :status="scope.row.visibility" /></template></el-table-column>
      <el-table-column prop="status" label="状态" width="86"><template #default="scope"><StatusTag :status="scope.row.status" /></template></el-table-column>
      <el-table-column v-if="session.canEditCatalog" label="操作" width="120" fixed="right"><template #default="scope"><el-button link type="primary" @click="resetForm(scope.row)">编辑</el-button><el-button v-if="scope.row.status === 'active'" link type="danger" @click="archive(scope.row)">归档</el-button></template></el-table-column>
    </el-table>
  </div></section>

  <el-dialog v-model="dialog" :title="editing ? '编辑膜材规格' : '新增膜材规格'" width="720px">
    <el-form label-position="top"><div class="dialog-grid">
      <el-form-item label="厂家"><el-input v-model="form.manufacturer" /></el-form-item>
      <el-form-item label="产品型号"><el-input v-model="form.product_reference" /></el-form-item>
      <el-form-item label="膜材类型"><el-input v-model="form.material" /></el-form-item>
      <el-form-item label="适用场景"><el-input v-model="form.application" /></el-form-item>
      <el-form-item class="wide" label="规格说明"><el-input v-model="form.specification" type="textarea" :rows="3" /></el-form-item>
      <el-form-item class="wide" label="来源 URL"><el-input v-model="form.source_url" /></el-form-item>
      <el-form-item label="来源版本"><el-input v-model="form.source_version" /></el-form-item>
      <el-form-item label="资料分级"><el-select v-model="form.visibility"><el-option label="公开" value="public" /><el-option label="内部" value="internal" /><el-option label="受限" value="restricted" /></el-select></el-form-item>
      <el-form-item label="来源页"><el-input-number v-model="form.source_page" :min="1" /></el-form-item>
      <el-form-item label="PDF 总页数"><el-input-number v-model="form.source_page_count" :min="1" /></el-form-item>
      <el-form-item class="wide" label="许可说明"><el-input v-model="form.license" /></el-form-item>
      <el-form-item class="wide" label="源文件 SHA-256"><el-input v-model="form.source_sha256" class="mono" maxlength="64" /></el-form-item>
    </div></el-form>
    <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
  </el-dialog>
</template>

<style scoped>.dialog-grid { display:grid; grid-template-columns:1fr 1fr; gap:0 16px; }.wide{grid-column:1/-1}@media(max-width:600px){.dialog-grid{grid-template-columns:1fr}.wide{grid-column:auto}}</style>
