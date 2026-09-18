<script setup lang="ts">
import { CircleCheck, Document, Operation, Warning } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import StatusTag from '../components/StatusTag.vue'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()
const router = useRouter()
const loading = ref(true)
const data = ref<any>(null)

const runningReviews = computed(() => (data.value?.reviews?.by_status?.running || 0) + (data.value?.reviews?.by_status?.queued || 0))
const waitingReviews = computed(() => data.value?.reviews?.by_status?.awaiting_approval || 0)
const budgetPercent = computed(() => {
  const budget = data.value?.budget
  if (!budget?.daily_token_limit) return 0
  return Math.min(100, Math.round(((budget.used_tokens + budget.reserved_tokens) / budget.daily_token_limit) * 100))
})

async function load() {
  if (!session.currentProjectId) return
  loading.value = true
  try {
    data.value = (await api.get(`/api/v1/projects/${session.currentProjectId}/dashboard`)).data
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '总览加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="项目总览" :description="`${session.currentProject?.name || '当前项目'}的资料、审查与风险状态`">
    <el-button @click="router.push('/documents')">查看资料</el-button>
    <el-button type="primary" @click="router.push('/reviews')">发起审查</el-button>
  </PageHeader>

  <el-skeleton :loading="loading" animated :rows="8">
    <div class="metric-grid">
      <div class="metric" @click="router.push('/documents')">
        <div class="metric__top"><span>工程资料</span><span class="metric__icon"><Document /></span></div>
        <strong>{{ data?.documents?.total || 0 }}</strong><small>已索引 {{ data?.documents?.by_status?.indexed || 0 }} 份</small>
      </div>
      <div class="metric" @click="router.push('/reviews')">
        <div class="metric__top"><span>执行中审查</span><span class="metric__icon"><Operation /></span></div>
        <strong>{{ runningReviews }}</strong><small>待审批 {{ waitingReviews }} 项</small>
      </div>
      <div class="metric" @click="router.push('/issues')">
        <div class="metric__top"><span>待处理问题</span><span class="metric__icon"><Warning /></span></div>
        <strong>{{ data?.issues?.open || 0 }}</strong><small>冲突 {{ data?.issues?.by_severity?.conflict || 0 }} 项</small>
      </div>
      <div class="metric">
        <div class="metric__top"><span>Token 预算</span><span class="metric__icon"><CircleCheck /></span></div>
        <strong>{{ budgetPercent }}%</strong><small>当日已用及预留</small>
      </div>
    </div>

    <div v-if="data?.issues?.by_severity?.conflict" class="risk-strip">
      当前项目存在 {{ data.issues.by_severity.conflict }} 条冲突问题，建议审核人优先处理。
    </div>

    <div class="split-grid" style="margin-top: 16px">
      <section class="section">
        <div class="section__header"><h2>最近审查</h2><el-button text type="primary" @click="router.push('/reviews')">全部审查</el-button></div>
        <el-table :data="data?.recent_reviews || []" table-layout="fixed">
          <el-table-column prop="question" label="审查目标" min-width="260" show-overflow-tooltip />
          <el-table-column prop="review_mode" label="模式" width="90">
            <template #default="scope">{{ scope.row.review_mode === 'full' ? '三领域' : '专项' }}</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="110"><template #default="scope"><StatusTag :status="scope.row.status" /></template></el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="170"><template #default="scope">{{ new Date(scope.row.created_at).toLocaleString() }}</template></el-table-column>
          <el-table-column label="" width="70"><template #default="scope"><el-button link type="primary" @click="router.push(`/reviews/${scope.row.review_id}`)">查看</el-button></template></el-table-column>
        </el-table>
      </section>

      <section class="section">
        <div class="section__header"><h2>服务状态</h2><span class="muted">实时依赖探测</span></div>
        <div class="health-list">
          <div v-for="(item, name) in data?.dependencies || {}" :key="name">
            <span>{{ name }}</span><StatusTag :status="item.healthy ? 'completed' : 'failed'" />
          </div>
        </div>
      </section>
    </div>

    <section class="section">
      <div class="section__header"><h2>最近批量导入</h2><el-button text type="primary" @click="router.push('/batches')">查看批次</el-button></div>
      <el-table :data="data?.recent_batches || []" table-layout="fixed">
        <el-table-column prop="batch_id" label="批次编号" min-width="220"><template #default="scope"><span class="mono">{{ scope.row.batch_id }}</span></template></el-table-column>
        <el-table-column prop="document_count" label="资料数" width="90" />
        <el-table-column prop="completed_count" label="完成" width="90" />
        <el-table-column prop="failed_count" label="失败" width="90" />
        <el-table-column prop="status" label="状态" width="120"><template #default="scope"><StatusTag :status="scope.row.status" /></template></el-table-column>
      </el-table>
    </section>
  </el-skeleton>
</template>

<style scoped>
.metric { cursor: pointer; }
.health-list { padding: 6px 18px; }
.health-list > div { min-height: 43px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #edf0f2; text-transform: capitalize; }
.health-list > div:last-child { border-bottom: 0; }
</style>
