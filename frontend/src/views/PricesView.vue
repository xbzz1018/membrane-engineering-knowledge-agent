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
    project_id: session.currentProjectId, material: '', specification: '', unit: 'CNY/m2', min_price: 0,
    max_price: 0, currency: 'CNY', region: '', effective_date: new Date().toISOString().slice(0, 10),
    source_url: 'synthetic://manual-reference', source_version: 'v1', license: 'Project-generated synthetic record.',
    retrieved_at: new Date().toISOString(), source_sha256: '', visibility: 'public', synthetic: true,
    disclaimer: '历史参考数据，不构成正式报价。',
  })
  dialog.value = true
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get<PageResult<CatalogItem>>('/api/v1/price-records', {
      params: { project_id: session.currentProjectId, query: query.value, status: status.value, page_size: 100 },
    })
    items.value = data.items; total.value = data.total
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '价格加载失败') }
  finally { loading.value = false }
}

async function save() {
  try {
    const payload = { ...form }
    if (editing.value) {
      payload.expected_lock_version = editing.value.lock_version
      await api.patch(`/api/v1/price-records/${editing.value.price_id}`, payload, { params: { project_id: session.currentProjectId } })
    } else await api.post('/api/v1/price-records', payload, { params: { project_id: session.currentProjectId } })
    ElMessage.success(editing.value ? '历史价格已更新' : '历史价格已新增')
    dialog.value = false; await load()
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '保存失败') }
}

async function archive(item: CatalogItem) {
  await ElMessageBox.confirm(`确认归档 ${item.material} ${item.effective_date} 的历史价格？`, '归档记录', { type: 'warning' })
  try {
    await api.post(`/api/v1/price-records/${item.price_id}/archive`, { expected_lock_version: item.lock_version }, { params: { project_id: session.currentProjectId } })
    ElMessage.success('记录已归档'); await load()
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '归档失败') }
}

onMounted(load)
</script>

<template>
  <PageHeader title="历史价格" description="按地区、日期、币种和单位维护可比较的历史参考记录">
    <el-button v-if="session.canEditCatalog" type="primary" :icon="Plus" @click="resetForm()">新增记录</el-button>
  </PageHeader>
  <div class="risk-strip">历史价格仅用于工程资料比对，不构成市场价格、正式报价或采购承诺。</div>
  <section class="section"><div class="section__body">
    <div class="toolbar"><el-input v-model="query" :prefix-icon="Search" clearable placeholder="膜材、地区或日期" style="width:300px" @keyup.enter="load" /><el-select v-model="status" style="width:120px" @change="load"><el-option label="启用" value="active" /><el-option label="已归档" value="archived" /></el-select><el-button @click="load">查询</el-button><span class="muted">{{ total }} 条</span><span class="spacer" /><el-button :icon="Refresh" @click="load">刷新</el-button></div>
    <el-table v-loading="loading" :data="items" table-layout="fixed">
      <el-table-column prop="material" label="膜材" width="120" />
      <el-table-column prop="specification" label="规格" min-width="210" show-overflow-tooltip />
      <el-table-column label="价格区间" width="165"><template #default="scope">{{ scope.row.currency }} {{ scope.row.min_price }}–{{ scope.row.max_price }}</template></el-table-column>
      <el-table-column prop="unit" label="单位" width="100" />
      <el-table-column prop="region" label="地区" width="100" />
      <el-table-column prop="effective_date" label="日期" width="115" />
      <el-table-column prop="synthetic" label="数据性质" width="100"><template #default="scope"><el-tag :type="scope.row.synthetic ? 'warning' : 'info'">{{ scope.row.synthetic ? 'synthetic' : '历史记录' }}</el-tag></template></el-table-column>
      <el-table-column prop="status" label="状态" width="86"><template #default="scope"><StatusTag :status="scope.row.status" /></template></el-table-column>
      <el-table-column v-if="session.canEditCatalog" label="操作" width="120" fixed="right"><template #default="scope"><el-button link type="primary" @click="resetForm(scope.row)">编辑</el-button><el-button v-if="scope.row.status === 'active'" link type="danger" @click="archive(scope.row)">归档</el-button></template></el-table-column>
    </el-table>
  </div></section>

  <el-dialog v-model="dialog" :title="editing ? '编辑历史价格' : '新增历史价格'" width="720px">
    <el-form label-position="top"><div class="dialog-grid">
      <el-form-item label="膜材"><el-input v-model="form.material" /></el-form-item><el-form-item label="规格"><el-input v-model="form.specification" /></el-form-item>
      <el-form-item label="最低价"><el-input-number v-model="form.min_price" :min="0" :precision="2" /></el-form-item><el-form-item label="最高价"><el-input-number v-model="form.max_price" :min="0" :precision="2" /></el-form-item>
      <el-form-item label="币种"><el-input v-model="form.currency" /></el-form-item><el-form-item label="单位"><el-input v-model="form.unit" /></el-form-item>
      <el-form-item label="地区"><el-input v-model="form.region" /></el-form-item><el-form-item label="生效日期"><el-date-picker v-model="form.effective_date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="资料分级"><el-select v-model="form.visibility"><el-option label="公开" value="public" /><el-option label="内部" value="internal" /><el-option label="受限" value="restricted" /></el-select></el-form-item><el-form-item label="数据性质"><el-switch v-model="form.synthetic" active-text="synthetic" inactive-text="历史记录" /></el-form-item>
      <el-form-item class="wide" label="来源 URL"><el-input v-model="form.source_url" /></el-form-item><el-form-item label="来源版本"><el-input v-model="form.source_version" /></el-form-item><el-form-item label="抓取时间"><el-input v-model="form.retrieved_at" /></el-form-item>
      <el-form-item class="wide" label="许可说明"><el-input v-model="form.license" /></el-form-item><el-form-item class="wide" label="源文件 SHA-256"><el-input v-model="form.source_sha256" class="mono" maxlength="64" /></el-form-item>
    </div></el-form><template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
  </el-dialog>
</template>

<style scoped>.risk-strip{margin-bottom:16px}.dialog-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}.wide{grid-column:1/-1}@media(max-width:600px){.dialog-grid{grid-template-columns:1fr}.wide{grid-column:auto}}</style>
