<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ChatDotRound, Search, Plus, Delete, ArrowRight, Collection } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { request, errorMessage } from '../api'
import type { ChatSession, ChatMessage, KnowledgeBase } from '../types'
import { formatDate } from '../utils'
import PageHeading from '../components/PageHeading.vue'
import StatePanel from '../components/StatePanel.vue'
import MessageItem from '../components/MessageItem.vue'
const route = useRoute(), rows = ref<ChatSession[]>([]), names = ref<Record<string, string>>({})
const loading = ref(true), error = ref(''), search = ref(''), selected = ref(''), messages = ref<ChatMessage[]>([]), messageLoading = ref(false), messageError = ref(''), deleting = ref('')
const filtered = computed(() => rows.value.filter(row => (row.title + ' ' + names.value[row.knowledge_base_id]).toLowerCase().includes(search.value.trim().toLowerCase())))
const active = computed(() => rows.value.find(row => row.id === selected.value))
let sequence = 0
async function select(id: string) {
  selected.value = id; messageLoading.value = true; messageError.value = ''; messages.value = []
  const current = ++sequence
  try { const history = await request<ChatMessage[]>('GET', '/sessions/' + id + '/messages'); if (current === sequence) messages.value = history }
  catch (err) { if (current === sequence) messageError.value = errorMessage(err, '聊天记录加载失败，请重新查看。') }
  finally { if (current === sequence) messageLoading.value = false }
}
async function load() {
  loading.value = true; error.value = ''
  try {
    const [history, kbs] = await Promise.all([request<ChatSession[]>('GET', '/sessions'), request<KnowledgeBase[]>('GET', '/knowledge-bases')])
    rows.value = history; names.value = Object.fromEntries(kbs.map(k => [k.id, k.name]))
    const id = rows.value.find(row => row.id === (selected.value || route.query.session))?.id || rows.value[0]?.id
    if (id) await select(id); else { selected.value = ''; messages.value = [] }
  } catch (err) { error.value = errorMessage(err, '会话列表加载失败，请重新加载。') }
  finally { loading.value = false }
}
async function remove(id: string) {
  if (deleting.value) return
  try { await ElMessageBox.confirm('删除后将无法恢复这段会话及聊天记录，确认继续？', '删除会话', { type:'warning', confirmButtonText:'确认删除', cancelButtonText:'取消' }) } catch { return }
  deleting.value = id
  try { await request('DELETE', '/sessions/' + id); ElMessage.success('会话已删除'); await load() }
  catch (err) { error.value = errorMessage(err, '删除结果尚未确认，请先刷新会话列表。') }
  finally { deleting.value = '' }
}
onMounted(load)
</script>
<template>
  <PageHeading title="会话历史" description="回顾每一次探索，继续未完成的思考。" eyebrow="CONVERSATIONS / 探索记录"><el-button type="primary" :icon="Plus" @click="$router.push('/chat')">开始新会话</el-button></PageHeading>
  <StatePanel v-if="loading" kind="loading" title="正在加载会话" />
  <StatePanel v-else-if="error" kind="error" title="会话暂时未能加载" :description="error"><el-button @click="load">重新加载</el-button></StatePanel>
  <StatePanel v-else-if="!rows.length" kind="empty" title="还没有会话，去探索你的知识库吧" description="每个问题与回答都会保存在这里，方便随时回顾。"><el-button type="primary" @click="$router.push('/chat')">开始智能问答</el-button></StatePanel>
  <div v-else class="history-layout"><aside class="history-list-panel"><div class="history-list-head"><strong>全部会话 <span class="count-badge">{{ rows.length }}</span></strong><el-input v-model="search" aria-label="搜索会话" :prefix-icon="Search" clearable placeholder="搜索会话或知识库" /></div><div class="history-list"><button v-for="row in filtered" :key="row.id" :class="['history-entry', { selected: selected === row.id }]" :aria-pressed="selected === row.id" @click="select(row.id)"><span class="history-entry-icon"><el-icon><ChatDotRound /></el-icon></span><span class="history-entry-body"><strong>{{ row.title }}</strong><span>{{ names[row.knowledge_base_id] || '知识库' }}</span><small>{{ formatDate(row.created_at, true) }} 创建</small></span></button><StatePanel v-if="!filtered.length" kind="empty" title="未找到相关会话" description="试试其他关键词。" /></div></aside>
    <section class="history-preview"><header class="history-preview-head"><div><span class="panel-label"><el-icon><Collection /></el-icon>{{ active ? names[active.knowledge_base_id] || '知识库' : '会话预览' }}</span><h3>{{ active?.title }}</h3></div><div class="actions"><el-button :icon="Delete" :loading="deleting === selected" :disabled="!selected || !!deleting" @click="remove(selected)">删除</el-button><el-button type="primary" :disabled="!selected || messageLoading" @click="$router.push('/chat?session=' + selected)">继续问答 <el-icon><ArrowRight /></el-icon></el-button></div></header>
      <div class="history-messages"><StatePanel v-if="messageLoading" kind="loading" title="正在加载聊天记录" /><StatePanel v-else-if="messageError" kind="error" title="聊天记录暂时未能加载" :description="messageError"><el-button @click="select(selected)">重新加载记录</el-button></StatePanel><template v-else-if="messages.length"><MessageItem v-for="message in messages" :key="message.id" :message="message" /></template><StatePanel v-else kind="empty" title="这段会话还没有消息" description="继续问答，开始新的探索。" /></div>
    </section>
  </div>
</template>
