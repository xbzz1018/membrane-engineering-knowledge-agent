<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status?: string }>()
const labels: Record<string, string> = {
  uploaded: '待解析', indexing: '解析中', indexed: '已索引', failed: '失败', index_failed: '索引失败',
  queued: '排队中', running: '执行中', awaiting_approval: '待审批', decision_pending: '决定待执行', approved: '已批准', rejected: '已退回',
  cancelled: '已取消', completed: '已完成', partial_failed: '部分失败', active: '启用', archived: '已归档',
  pending: '待确认', confirmed: '已确认', resolved: '已解决', dismissed: '已忽略', open: '待处理',
  public: '公开', internal: '内部', restricted: '受限',
}
const type = computed(() => {
  if (['failed', 'index_failed', 'rejected', 'conflict'].includes(props.status || '')) return 'danger'
  if (['indexing', 'running', 'queued'].includes(props.status || '')) return 'primary'
  if (['awaiting_approval', 'decision_pending', 'warning', 'pending', 'partial_failed'].includes(props.status || '')) return 'warning'
  if (['indexed', 'approved', 'completed', 'confirmed', 'resolved', 'active'].includes(props.status || '')) return 'success'
  return 'info'
})
</script>

<template><el-tag :type="type" effect="light" size="small">{{ labels[status || ''] || status || '未知' }}</el-tag></template>
