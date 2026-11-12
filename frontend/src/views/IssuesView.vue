<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import StatusTag from '../components/StatusTag.vue'
import { useSessionStore } from '../stores/session'

const session=useSessionStore();const router=useRouter();const loading=ref(false);const rows=ref<any[]>([]);const severity=ref('');const domain=ref('')
const filtered=computed(()=>rows.value.filter(x=>(!severity.value||x.severity===severity.value)&&(!domain.value||x.domain===domain.value)))
async function load(){loading.value=true;try{const reviews=(await api.get('/api/v1/package-reviews',{params:{project_id:session.currentProjectId,limit:200}})).data;const details=await Promise.all(reviews.map((r:any)=>api.get(`/api/v1/package-reviews/${r.review_id}/issues`)));rows.value=details.flatMap((d,i)=>d.data.issues.map((issue:any)=>({...issue,review_id:reviews[i].review_id,question:reviews[i].question,review_status:reviews[i].status}))) }catch(e){ElMessage.error(e instanceof Error?e.message:'问题单加载失败')}finally{loading.value=false}}
onMounted(load)
</script>
<template><PageHeader title="问题单" description="集中查看资料取证、材料核验、综合审查及业务一致性问题"><el-button :icon="Refresh" @click="load">刷新</el-button></PageHeader><section class="section"><div class="section__body"><div class="toolbar"><el-select v-model="severity" clearable placeholder="严重级别" style="width:130px"><el-option label="冲突" value="conflict"/><el-option label="警告" value="warning"/><el-option label="提示" value="info"/></el-select><el-select v-model="domain" clearable placeholder="领域" style="width:130px"><el-option label="资料检索" value="retrieval"/><el-option label="综合审查" value="review"/><el-option label="设计问题" value="design"/><el-option label="膜材" value="material"/><el-option label="价格" value="price"/><el-option label="跨领域" value="cross_domain"/></el-select><span class="muted">{{filtered.length}} 条</span></div><el-table v-loading="loading" :data="filtered" table-layout="fixed"><el-table-column prop="severity" label="级别" width="90"><template #default="s"><StatusTag :status="s.row.severity"/></template></el-table-column><el-table-column prop="domain" label="领域" width="100"/><el-table-column prop="summary" label="问题摘要" min-width="280"/><el-table-column prop="question" label="审查目标" min-width="220" show-overflow-tooltip/><el-table-column prop="status" label="处理状态" width="100"><template #default="s"><StatusTag :status="s.row.status"/></template></el-table-column><el-table-column label="证据" width="80"><template #default="s">{{s.row.evidence_refs?.length||0}}</template></el-table-column><el-table-column label="操作" width="80" fixed="right"><template #default="s"><el-button link type="primary" @click="router.push(`/reviews/${s.row.review_id}`)">查看</el-button></template></el-table-column></el-table></div></section></template>
