<script setup lang="ts">
defineProps<{ title: string; description: string; eyebrow?: string }>()
</script>
<template>
  <header class="page-head">
    <div class="page-heading"><p v-if="eyebrow" class="eyebrow">{{ eyebrow }}</p><h2>{{ title }}</h2><p class="muted">{{ description }}</p></div>
    <div class="actions"><slot /></div>
  </header>
</template>
