<script setup lang="ts">
import { Loading, FolderOpened, Warning } from '@element-plus/icons-vue'
defineProps<{ kind: 'loading' | 'empty' | 'error'; title: string; description?: string }>()
</script>
<template>
  <div :class="['state-panel', 'state-' + kind]" :role="kind === 'error' ? 'alert' : 'status'" :aria-busy="kind === 'loading'">
    <span class="state-icon"><el-icon :class="{ spinning: kind === 'loading' }"><component :is="kind === 'loading' ? Loading : kind === 'error' ? Warning : FolderOpened" /></el-icon></span>
    <h3>{{ title }}</h3><p v-if="description" class="muted">{{ description }}</p><div v-if="$slots.default" class="state-actions"><slot /></div>
  </div>
</template>
