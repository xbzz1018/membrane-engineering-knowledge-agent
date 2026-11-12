<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { api, downloadArtifact } from '../api/client'
import { useSessionStore } from '../stores/session'
import StatusTag from './StatusTag.vue'

interface Requirements {
  project_name: string; building_area_m2: number | null; location: string; purpose: string
  preferred_membrane: string; applicable_revision: string; notes: string
}
interface Content {
  requirements: Requirements
  sections: Array<{ section_id: string; title: string; content: string; origin: 'proposed' }>
  source_quotes: Array<{ purpose: string; evidence_id: string; quote: string }>
}
interface Artifact { id: string; format: string; status: string; download_url: string }
interface Plan {
  plan_id: string; project_id: string; version: number; current_version: number; lock_version: number; status: string
  requirements: Requirements; content: Content | null; content_hash: string; manifest_hash: string; error_type: string
  review: { id: string; result: { issues: Array<{ target_path: string; message: string }> } } | null
  artifacts: Artifact[]
  source_manifest: { evidence: Array<{ evidence_id: string; filename: string; location: string; version: string }> } | null
}

const props = defineProps<{ modelValue: boolean; planId?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const session = useSessionStore()
const open = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
const plans = ref<Plan[]>([])
const selected = ref<Plan | null>(null)
const draft = ref<Content | null>(null)
const editing = ref(false)
const busy = ref(false)
const loading = ref(false)
const loadError = ref('')
const revisionReason = ref('')
let sequence = 0
let timer: ReturnType<typeof setTimeout> | undefined
const canWrite = computed(() => ['admin', 'design_engineer', 'material_procurement'].includes(session.principal?.role || ''))
const editable = computed(() => selected.value && ['awaiting_approval', 'needs_revision', 'approved', 'rejected'].includes(selected.value.status))
const active = new Set(['queued', 'generating', 'generated', 'reviewing', 'decision_pending'])

function stopPolling() { clearTimeout(timer) }
function errorMessage(error: unknown) { return error instanceof Error ? error.message : '操作失败' }
function cloneContent(content: Content): Content { return JSON.parse(JSON.stringify(content)) as Content }

async function load(planId = selected.value?.plan_id || props.planId) {
  const requestSequence = ++sequence
  const projectId = session.currentProjectId
  stopPolling()
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await api.get<Plan[]>(`/api/v1/projects/${projectId}/plans`)
    if (requestSequence !== sequence || projectId !== session.currentProjectId) return
    plans.value = data
    const next = data.find(item => item.plan_id === planId) || data[0] || null
    selected.value = next
    if (!editing.value) draft.value = next?.content ? cloneContent(next.content) : null
    if (open.value && next && (active.has(next.status) || next.artifacts.some(item => ['queued', 'rendering'].includes(item.status)))) {
      timer = setTimeout(() => void load(next.plan_id), 5000)
    }
  } catch (error) {
    if (requestSequence === sequence) loadError.value = errorMessage(error)
  } finally {
    if (requestSequence === sequence) loading.value = false
  }
}

async function operate(operation: (plan: Plan) => Promise<unknown>) {
  if (!selected.value || busy.value) return
  const plan = selected.value
  busy.value = true
  stopPolling()
  try {
    await operation(plan)
    if (plan.project_id === session.currentProjectId) await load(plan.plan_id)
  } catch (error) {
    ElMessage.error(errorMessage(error))
    if (plan.project_id === session.currentProjectId) await load(plan.plan_id)
  } finally { busy.value = false }
}

function startEditing() {
  if (!selected.value?.content) return
  draft.value = cloneContent(selected.value.content)
  revisionReason.value = ''
  editing.value = true
}

async function revise() {
  if (!draft.value || !revisionReason.value.trim()) { ElMessage.warning('请填写修订原因'); return }
  const content = cloneContent(draft.value)
  const reason = revisionReason.value
  await operate(async plan => {
    await api.post(`/api/v1/plans/${plan.plan_id}/revisions`, {
      request_id: crypto.randomUUID(), base_version: plan.version, expected_lock_version: plan.lock_version, content, reason,
    })
    editing.value = false
    ElMessage.success('已保存新版本并提交审查，原批准不适用于新版本')
  })
}

async function decide(decision: 'approved' | 'rejected') {
  const plan = selected.value
  if (!plan?.review) return
  let reason: string
  try {
    const answer = await ElMessageBox.prompt(
      `本次决定仅针对 v${plan.version}。请核对需求、建议和原始依据，并填写处理说明。`,
      decision === 'approved' ? '批准当前方案' : '退回当前方案',
      { inputValidator: value => Boolean(value?.trim()) || '请填写处理说明', confirmButtonText: '确认', cancelButtonText: '取消' },
    )
    reason = answer.value
  } catch { return }
  if (plan.project_id !== session.currentProjectId || selected.value?.plan_id !== plan.plan_id) return
  const review = plan.review
  await operate(async () => {
    await api.post(`/api/v1/plans/${plan.plan_id}/versions/${plan.version}/decision`, {
      command_id: crypto.randomUUID(), expected_lock_version: plan.lock_version, review_id: review.id,
      content_hash: plan.content_hash, manifest_hash: plan.manifest_hash, decision, reason,
    })
    ElMessage.success('决定已提交，以最新方案状态为准')
  })
}

async function exportFiles() {
  await operate(plan => api.post(`/api/v1/plans/${plan.plan_id}/versions/${plan.version}/exports`, { formats: ['md', 'docx'] }))
}

async function download(file: Artifact) {
  try { await downloadArtifact(file.download_url, `项目初步方案-v${selected.value?.version}.${file.format}`) }
  catch (error) { ElMessage.error(errorMessage(error)) }
}

watch(() => [props.modelValue, props.planId, session.currentProjectId] as const, ([visible], previous) => {
  sequence++
  stopPolling()
  if (!visible) editing.value = false
  if (previous && previous[2] !== session.currentProjectId) { selected.value = null; plans.value = []; editing.value = false }
  if (visible) void load(props.planId)
}, { immediate: true })
onBeforeUnmount(() => { sequence++; stopPolling() })
</script>

<template>
  <el-drawer v-model="open" title="项目初步方案" size="min(940px,96vw)">
    <div class="plan-toolbar">
      <el-select :model-value="selected?.plan_id" placeholder="选择当前项目方案" @change="id => { editing = false; void load(id) }">
        <el-option v-for="item in plans" :key="item.plan_id" :value="item.plan_id" :label="`${item.requirements.project_name} · v${item.version}`" />
      </el-select>
      <el-button :loading="loading" @click="load()">刷新</el-button>
    </div>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon />
    <el-empty v-if="!selected && !loading" description="当前项目暂无方案。请在对话中明确提出生成需求，包含面积、地点及膜材偏好。" />
    <template v-if="selected">
      <div class="plan-toolbar"><strong>{{ selected.requirements.project_name }}</strong><span>v{{ selected.version }}</span><StatusTag :status="selected.status" /></div>
      <p class="muted">初步方案供业务讨论。来源原文与建议分别列示；修改后重新审查，人工批准只对同一版本有效。</p>
      <el-alert v-if="selected.error_type" :title="`任务执行失败（${selected.error_type}），没有成功结果。可重试或重新发起。`" type="error" :closable="false" />
      <el-alert v-if="selected.status === 'decision_pending'" title="决定已保存，等待工作流执行；尚不能导出。" type="warning" :closable="false" />
      <el-button v-if="canWrite && ['failed', 'queued'].includes(selected.status)" :loading="busy" @click="operate(plan => api.post(`/api/v1/plans/${plan.plan_id}/versions/${plan.version}/generate`))">重试任务</el-button>
      <h3>用户声明需求</h3>
      <el-form v-if="editing && draft" label-width="100px">
        <el-form-item label="方案名称"><el-input v-model="draft.requirements.project_name" maxlength="160" /></el-form-item>
        <el-form-item label="面积 m²"><el-input-number v-model="draft.requirements.building_area_m2" :min="0.01" :max="1000000" /></el-form-item>
        <el-form-item label="项目地点"><el-input v-model="draft.requirements.location" maxlength="300" /></el-form-item>
        <el-form-item label="使用用途"><el-input v-model="draft.requirements.purpose" maxlength="200" /></el-form-item>
        <el-form-item label="膜材偏好"><el-input v-model="draft.requirements.preferred_membrane" maxlength="100" /></el-form-item>
        <el-form-item label="适用版次"><el-input v-model="draft.requirements.applicable_revision" maxlength="100" /></el-form-item>
        <el-form-item label="补充需求"><el-input v-model="draft.requirements.notes" type="textarea" :rows="3" maxlength="4000" /></el-form-item>
      </el-form>
      <el-descriptions v-else :column="2" border>
        <el-descriptions-item label="面积">{{ selected.requirements.building_area_m2 ?? '待确认' }} m²</el-descriptions-item>
        <el-descriptions-item label="地点">{{ selected.requirements.location || '待确认' }}</el-descriptions-item>
        <el-descriptions-item label="用途">{{ selected.requirements.purpose }}</el-descriptions-item>
        <el-descriptions-item label="膜材偏好">{{ selected.requirements.preferred_membrane || '待确认' }}</el-descriptions-item>
        <el-descriptions-item label="适用版次">{{ selected.requirements.applicable_revision || '待确认' }}</el-descriptions-item>
        <el-descriptions-item label="需求说明">{{ selected.requirements.notes || '无' }}</el-descriptions-item>
      </el-descriptions>
      <template v-if="draft">
        <div v-for="section in draft.sections" :key="section.section_id" class="plan-section">
          <h3>{{ section.title }} <small class="muted">方案建议</small></h3>
          <el-input v-if="editing" v-model="section.content" type="textarea" :rows="4" maxlength="4000" />
          <p v-else>{{ section.content }}</p>
        </div>
        <h3>原始依据</h3>
        <el-empty v-if="!draft.source_quotes.length" description="未取得可引用依据，不能批准" />
        <div v-for="(quote, index) in draft.source_quotes" :key="index" class="plan-evidence">
          <strong>{{ quote.purpose === 'history' ? '资料参考' : '材料依据' }}</strong>
          <p>{{ selected.source_manifest?.evidence.find(item => item.evidence_id === quote.evidence_id)?.filename }} · {{ selected.source_manifest?.evidence.find(item => item.evidence_id === quote.evidence_id)?.location }}</p>
          <p>{{ quote.quote }}</p><code>{{ quote.evidence_id }}</code>
        </div>
      </template>
      <template v-if="selected.review">
        <h3>审查结果</h3>
        <p v-if="!selected.review.result.issues.length">已实现的自动检查通过，仍需审核人核对内容与适用性。</p>
        <el-alert v-for="(issue,index) in selected.review.result.issues" :key="index" :title="issue.message" type="warning" :closable="false" class="plan-issue" />
      </template>
      <div class="plan-actions">
        <template v-if="editing">
          <el-input v-model="revisionReason" placeholder="填写修订原因" maxlength="1000" />
          <el-button type="primary" :loading="busy" @click="revise">保存新版本并审查</el-button>
          <el-button @click="editing = false; load()">取消修改</el-button>
        </template>
        <template v-else>
          <el-button v-if="canWrite && editable" :disabled="busy" @click="startEditing">修改形成新版本</el-button>
          <el-button v-if="session.canReview && selected.status === 'awaiting_approval'" type="primary" :loading="busy" @click="decide('approved')">批准当前版本</el-button>
          <el-button v-if="session.canReview && ['awaiting_approval', 'needs_revision'].includes(selected.status)" :loading="busy" @click="decide('rejected')">退回</el-button>
          <el-button v-if="selected.status === 'approved'" type="primary" :loading="busy" @click="exportFiles">生成 Markdown 和 Word</el-button>
          <el-button v-for="file in selected.artifacts" :key="file.id" :disabled="selected.status !== 'approved' || file.status !== 'published'" @click="download(file)">{{ file.format.toUpperCase() }} · {{ file.status === 'published' ? '下载' : file.status }}</el-button>
        </template>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.plan-toolbar{display:flex;align-items:center;gap:12px;margin-bottom:16px}.plan-toolbar .el-select{flex:1}.plan-section p,.plan-evidence p{white-space:pre-wrap;line-height:1.8}.plan-section small{font-size:12px;font-weight:400}.plan-evidence{padding:14px;margin-bottom:12px;background:#f5f8f7;border-left:3px solid #0f8f7a}.plan-evidence code{overflow-wrap:anywhere;font-size:11px;color:#687784}.plan-issue{margin:8px 0}.plan-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:22px;padding:16px 0;border-top:1px solid #dce3e8}.plan-actions .el-input{width:100%}.plan-actions .el-button{margin-left:0}
</style>
