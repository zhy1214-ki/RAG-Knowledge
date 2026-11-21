<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import python from 'highlight.js/lib/languages/python'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import json from 'highlight.js/lib/languages/json'
import bash from 'highlight.js/lib/languages/bash'
import sql from 'highlight.js/lib/languages/sql'
import { ElMessage } from 'element-plus'
const props = defineProps<{ content: string }>()
for (const [name, grammar] of Object.entries({ python, javascript, typescript, json, bash, sql })) hljs.registerLanguage(name, grammar)
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
md.renderer.rules.fence = (tokens, index) => {
  const token = tokens[index]!, language = token.info.trim().split(/\s+/)[0] || 'text'
  const code = hljs.getLanguage(language) ? hljs.highlight(token.content, { language, ignoreIllegals: true }).value : md.utils.escapeHtml(token.content)
  return '<div class="code-block"><div class="code-toolbar"><span>' + md.utils.escapeHtml(language) + '</span><button type="button" class="code-copy" aria-label="复制代码">复制代码</button></div><pre><code class="hljs">' + code + '</code></pre></div>'
}
// Untrusted answers cannot load remote images or render raw HTML.
md.renderer.rules.image = (tokens, index) => '<span class="markdown-image-note">[图片：' + md.utils.escapeHtml(tokens[index]?.content || '未加载') + ']</span>'
md.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index]!.attrSet('target', '_blank'); tokens[index]!.attrSet('rel', 'noopener noreferrer')
  return renderer.renderToken(tokens, index, options)
}
md.renderer.rules.table_open = () => '<div class="markdown-table-scroll"><table>'
md.renderer.rules.table_close = () => '</table></div>'
const html = computed(() => DOMPurify.sanitize(md.render(props.content), {
  USE_PROFILES: { html: true }, ADD_ATTR: ['target'], FORBID_TAGS: ['img'], FORBID_ATTR: ['style', 'id', 'name'],
}))
async function copyCode(event: MouseEvent) {
  if (!(event.target instanceof Element)) return
  const button = event.target.closest<HTMLButtonElement>('.code-copy')
  if (!button) return
  const code = button.closest('.code-block')?.querySelector('code')?.textContent || ''
  try { await navigator.clipboard.writeText(code); ElMessage.success('代码已复制') }
  catch { ElMessage.warning('浏览器未允许复制，请手动选择代码') }
}
</script>
<template><div class="markdown-content" @click="copyCode" v-html="html" /></template>
