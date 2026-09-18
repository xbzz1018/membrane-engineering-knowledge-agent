<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'

import { api } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import StatusTag from '../components/StatusTag.vue'
import { useSessionStore } from '../stores/session'

const session=useSessionStore();const loading=ref(false);const items=ref<any[]>([]);const status=ref('')
async function load(){loading.value=true;try{items.value=(await api.get('/api/v1/batch-imports',{params:{project_id:session.currentProjectId,status:status.value,page_size:100}})).data.items}catch(e){ElMessage.error(e instanceof Error?e.message:'批次加载失败')}finally{loading.value=false}}
onMounted(load)
</script>
<template><PageHeader title="批量导入" description="查看 Temporal 批次进度、失败项和可恢复状态"><el-button :icon="Refresh" @click="load">刷新</el-button></PageHeader><section class="section"><div class="section__body"><div class="toolbar"><el-select v-model="status" clearable placeholder="全部状态" style="width:150px" @change="load"><el-option label="排队中" value="queued"/><el-option label="执行中" value="running"/><el-option label="已完成" value="completed"/><el-option label="部分失败" value="partial_failed"/><el-option label="失败" value="failed"/></el-select><span class="muted">{{items.length}} 个批次</span></div><el-table v-loading="loading" :data="items" table-layout="fixed"><el-table-column prop="batch_id" label="批次编号" min-width="240"><template #default="s"><span class="mono">{{s.row.batch_id}}</span></template></el-table-column><el-table-column prop="document_count" label="资料" width="80"/><el-table-column prop="completed_count" label="完成" width="80"/><el-table-column prop="failed_count" label="失败" width="80"/><el-table-column prop="skipped_count" label="跳过" width="80"/><el-table-column label="进度" min-width="180"><template #default="s"><el-progress :percentage="s.row.document_count?Math.round(((s.row.completed_count+s.row.failed_count+s.row.skipped_count)/s.row.document_count)*100):0" :stroke-width="8"/></template></el-table-column><el-table-column prop="status" label="状态" width="110"><template #default="s"><StatusTag :status="s.row.status"/></template></el-table-column><el-table-column prop="created_at" label="创建时间" width="170"><template #default="s">{{new Date(s.row.created_at).toLocaleString()}}</template></el-table-column></el-table></div></section></template>
