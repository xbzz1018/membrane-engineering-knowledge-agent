<script setup lang="ts">
import { CircleCheck, CloseBold, Refresh, VideoPause } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { api } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import StatusTag from '../components/StatusTag.vue'
import { useSessionStore } from '../stores/session'
import type { ReviewItem, ReviewIssue } from '../types/domain'

const route=useRoute(); const session=useSessionStore(); const reviewId=String(route.params.reviewId); const loading=ref(false)
const review=ref<ReviewItem|null>(null); const workers=ref<any>({}); const trace=ref<any[]>([]); const rejectOpen=ref(false); const rejectReason=ref('')
const canDecide=computed(()=>session.canReview && ['awaiting_approval','completed'].includes(review.value?.status||''))

let pollTimer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let refreshing = false
async function load(quiet = false) {
  if (refreshing || disposed) return
  refreshing = true
  clearTimeout(pollTimer)
  if (!quiet) loading.value = true
  try {
    const [r, w, t] = await Promise.all([
      api.get(`/api/v1/package-reviews/${reviewId}`),
      api.get(`/api/v1/package-reviews/${reviewId}/workers`),
      api.get(`/api/v1/package-reviews/${reviewId}/trace`),
    ])
    if (!disposed) { review.value = r.data; workers.value = w.data; trace.value = t.data.runs || [] }
  } catch (e) { if (!quiet && !disposed) ElMessage.error(e instanceof Error ? e.message : '审查加载失败') }
  finally {
    refreshing = false
    loading.value = false
    if (!disposed && ['queued', 'running', 'awaiting_approval', 'decision_pending'].includes(review.value?.status || '')) {
      pollTimer = setTimeout(() => { void load(true) }, 6000)
    }
  }
}
async function issueStatus(issue:ReviewIssue,status:string){if(!review.value)return;try{const reason=status==='dismissed'?(await ElMessageBox.prompt('填写忽略该问题的业务原因','处理说明',{inputValidator:(value:string)=>Boolean(value.trim())||'请填写原因'})).value:'';const {data}=await api.patch(`/api/v1/package-reviews/${reviewId}/issues/${issue.issue_id}`,{status,reason,expected_lock_version:review.value.lock_version});review.value.lock_version=data.lock_version;issue.status=data.issue.status;ElMessage.success('问题单状态已更新')}catch(e:any){if(e==='cancel'||e==='close')return;if(e.status===409)await load();ElMessage.error(e instanceof Error?e.message:'更新失败')}}
async function approve(){if(!review.value)return;try{await ElMessageBox.confirm('批准后该审查将进入最终状态，确认继续？','批准审查',{type:'warning'});await api.post(`/api/v1/package-reviews/${reviewId}/decision`,{decision:'approved',expected_lock_version:review.value.lock_version});ElMessage.success('批准请求已提交');await load()}catch(e){if(e==='cancel'||e==='close')return;ElMessage.error(e instanceof Error?e.message:'批准失败')}}
async function reject(){if(!review.value)return;try{await api.post(`/api/v1/package-reviews/${reviewId}/decision`,{decision:'rejected',expected_lock_version:review.value.lock_version,reason:rejectReason.value});ElMessage.success('退回请求已提交');rejectOpen.value=false;await load()}catch(e){ElMessage.error(e instanceof Error?e.message:'退回失败')}}
async function cancel(){await ElMessageBox.confirm('确认取消尚未完成的审查？','取消审查',{type:'warning'});try{await api.post(`/api/v1/workflows/package-review:${reviewId}/cancel`);ElMessage.success('取消请求已提交');await load()}catch(e){ElMessage.error(e instanceof Error?e.message:'取消失败')}}
onMounted(() => { void load() })
onBeforeUnmount(() => { disposed = true; clearTimeout(pollTimer) })
</script>

<template><PageHeader title="审查详情" :description="reviewId"><el-button :icon="Refresh" @click="load()">刷新</el-button><el-button v-if="['queued','running','awaiting_approval'].includes(review?.status||'')" :icon="VideoPause" @click="cancel">取消</el-button><el-button v-if="canDecide" type="danger" plain :icon="CloseBold" @click="rejectOpen=true">退回</el-button><el-button v-if="canDecide" type="primary" :icon="CircleCheck" @click="approve">批准</el-button></PageHeader>
  <el-skeleton :loading="loading" animated :rows="10"><template v-if="review"><div class="review-summary section"><div><span>状态</span><StatusTag :status="review.status" /></div><div><span>审查模式</span><strong>{{review.review_mode==='focused'?'专项':'三领域'}}</strong></div><div><span>执行引擎</span><strong>{{review.engine}}</strong></div><div><span>锁版本</span><strong>V{{review.lock_version}}</strong></div></div>
  <div class="split-grid" style="margin-top:16px"><section class="section"><div class="section__header"><h2>Supervisor 审查计划</h2><span class="muted">只负责规划，不修改事实</span></div><div class="section__body"><pre class="code-block">{{JSON.stringify(review.review_plan||workers.review_plan||{},null,2)}}</pre></div></section><section class="section"><div class="section__header"><h2>领域 Worker</h2></div><div class="worker-list"><div v-for="name in ['design','material','price']" :key="name"><span><strong>{{({design:'设计审查',material:'膜材审查',price:'价格审查'} as any)[name]}}</strong><small>{{workers.workers?.[name]?.findings?.length||0}} 条发现</small></span><StatusTag :status="workers.workers?.[name]?'completed':'pending'" /></div></div></section></div>
  <section class="section"><div class="section__header"><h2>工程问题单</h2><span class="muted">{{review.issues?.length||0}} 条</span></div><el-table :data="review.issues||[]" table-layout="fixed"><el-table-column prop="severity" label="级别" width="90"><template #default="s"><StatusTag :status="s.row.severity" /></template></el-table-column><el-table-column prop="domain" label="领域" width="90"/><el-table-column prop="summary" label="问题" min-width="260"/><el-table-column prop="actual_value" label="实际值" min-width="150" show-overflow-tooltip/><el-table-column prop="expected_value" label="预期值" min-width="150" show-overflow-tooltip/><el-table-column prop="status" label="状态" width="90"><template #default="s"><StatusTag :status="s.row.status" /></template></el-table-column><el-table-column v-if="canDecide" label="处理" width="140" fixed="right"><template #default="s"><el-button link type="primary" @click="issueStatus(s.row,'resolved')">解决</el-button><el-button link @click="issueStatus(s.row,'dismissed')">忽略</el-button></template></el-table-column></el-table></section>
  <section class="section"><div class="section__header"><h2>审查报告</h2><StatusTag :status="review.status" /></div><div class="report-body">{{review.report||'报告尚未生成。'}}</div></section>
  <section class="section"><div class="section__header"><h2>证据引用</h2><span class="muted">{{review.sources?.length||0}} 条</span></div><el-table :data="review.sources||[]"><el-table-column prop="title" label="文件/来源" min-width="220"/><el-table-column prop="location" label="位置" width="150"/><el-table-column prop="version" label="版本" width="100"/><el-table-column prop="source_id" label="Evidence ID" min-width="250"><template #default="s"><span class="mono">{{s.row.source_id}}</span></template></el-table-column></el-table></section>
  <section class="section"><div class="section__header"><h2>运行轨迹</h2><span class="muted">仅安全摘要，不保存隐藏推理</span></div><el-table :data="trace"><el-table-column prop="run_type" label="类型"/><el-table-column prop="status" label="状态"><template #default="s"><StatusTag :status="s.row.status"/></template></el-table-column><el-table-column prop="model" label="模型"/><el-table-column prop="input_tokens" label="输入Token"/><el-table-column prop="output_tokens" label="输出Token"/><el-table-column prop="latency_ms" label="耗时(ms)"/></el-table></section></template></el-skeleton>
  <el-dialog v-model="rejectOpen" title="退回审查" width="480px"><el-input v-model="rejectReason" type="textarea" :rows="4" placeholder="填写退回原因"/><template #footer><el-button @click="rejectOpen=false">取消</el-button><el-button type="danger" :disabled="!rejectReason.trim()" @click="reject">确认退回</el-button></template></el-dialog>
</template>

<style scoped>.review-summary{display:grid;grid-template-columns:repeat(4,1fr);padding:16px 20px}.review-summary>div{display:flex;flex-direction:column;gap:8px;border-right:1px solid #e2e7eb;padding:0 18px}.review-summary>div:last-child{border:0}.review-summary span{color:#687784;font-size:12px}.worker-list{padding:4px 18px}.worker-list>div{min-height:62px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #edf0f2}.worker-list span{display:flex;flex-direction:column;gap:4px}.worker-list small{color:#687784}.report-body{padding:20px;line-height:1.85;white-space:pre-wrap}.section{margin-top:16px}@media(max-width:700px){.review-summary{grid-template-columns:1fr 1fr;gap:18px}.review-summary>div{border:0;padding:0}}</style>
