<script setup lang="ts">
import { Document, MagicStick, UserFilled } from '@element-plus/icons-vue'
import MarkdownContent from './MarkdownContent.vue'
import type { ChatMessage, Citation } from '../types'
defineProps<{ message: ChatMessage }>()
function location(source: Citation) {
  const loc = source.source_location
  return loc?.format === 'pdf' && Number.isInteger(loc.page) && Number(loc.page) > 0
    ? ' · 第 ' + loc.page + ' 页' : loc?.section ? ' · ' + loc.section : ''
}
</script>
<template>
  <article :class="['chat-message', message.role]">
    <span class="message-avatar"><el-icon><UserFilled v-if="message.role === 'user'" /><MagicStick v-else /></el-icon></span>
    <div class="message-body">
      <div class="message-label">{{ message.role === 'user' ? '你' : '知序 · 知识助手' }}<span v-if="message.role === 'assistant' && message.citations?.length" class="grounded-label">有据可查</span></div>
      <div class="bubble"><MarkdownContent v-if="message.role === 'assistant'" :content="message.content" /><p v-else class="user-content">{{ message.content }}</p></div>
      <div v-if="message.citations?.length" class="citations"><div class="citation-heading">参考来源 <span>{{ message.citations.length }} 段原文</span></div>
        <el-collapse>
          <el-collapse-item v-for="(source, i) in message.citations" :key="source.chunk_id" :name="source.chunk_id">
            <template #title><el-icon class="source-icon"><Document /></el-icon><span class="source-title">[{{ source.source_id || Number(i) + 1 }}] {{ source.source_name }}{{ location(source) }}</span></template>
            <div class="citation"><p class="source-text">{{ source.text }}</p><p class="source-id">文档 ID：{{ source.document_id }}</p></div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>
  </article>
</template>
