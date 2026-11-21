<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Collection, Document, Plus, ChatDotRound, ArrowRight, Promotion, MagicStick } from '@element-plus/icons-vue'
import { request, errorMessage } from '../api'
import type { KnowledgeBase, ChatSession, ChatMessage } from '../types'
import PageHeading from '../components/PageHeading.vue'
import StatePanel from '../components/StatePanel.vue'
import MessageItem from '../components/MessageItem.vue'
const route = useRoute(), router = useRouter()
const kbs = ref<KnowledgeBase[]>([]), sessions = ref<ChatSession[]>([]), kb = ref(''), session = ref('')
const messages = ref<ChatMessage[]>([]), question = ref(''), busy = ref(false), uncertain = ref(false), mode = ref('')
const initialLoading = ref(true), historyLoading = ref(false), loadError = ref(''), sendError = ref(''), pendingQuestion = ref(''), scroll = ref<HTMLElement>()
const locked = computed(() => busy.value || initialLoading.value || historyLoading.value)
const currentKB = computed(() => kbs.value.find(item => item.id === kb.value))
const currentTitle = computed(() => sessions.value.find(item => item.id === session.value)?.title || '新的探索')
const suggestions = ['这份文档主要介绍了什么？', '有哪些需要注意的操作步骤？', '帮我梳理一下关键要点']
let historySequence = 0
async function bottom() { await nextTick(); scroll.value?.scrollTo({ top: scroll.value.scrollHeight, behavior: 'smooth' }) }
function reset() { if (busy.value) return; historySequence++; session.value = ''; messages.value = []; question.value = ''; pendingQuestion.value = ''; uncertain.value = false; sendError.value = ''; loadError.value = ''; historyLoading.value = false }
function newSession() { reset(); void router.replace('/chat' + (kb.value ? '?kb=' + kb.value : '')) }
async function openSession(id: string) {
  if (busy.value) return
  if (id === session.value && uncertain.value) { await refresh(); return }
  const sequence = ++historySequence; historyLoading.value = true; loadError.value = ''
  try {
    const data = await request<ChatSession>('GET', '/sessions/' + id)
    const history = await request<ChatMessage[]>('GET', '/sessions/' + id + '/messages')
    if (sequence !== historySequence) return
    session.value = data.id; kb.value = data.knowledge_base_id; messages.value = history
    uncertain.value = false; sendError.value = ''; pendingQuestion.value = ''; question.value = ''
  } catch (err) { if (sequence === historySequence) loadError.value = errorMessage(err, '会话暂时无法加载，请从历史记录重新查看。') }
  finally { if (sequence === historySequence) { historyLoading.value = false; await bottom() } }
}
async function refresh() {
  if (!session.value || busy.value || historyLoading.value) return
  historyLoading.value = true; loadError.value = ''
  try { messages.value = await request('GET', '/sessions/' + session.value + '/messages'); pendingQuestion.value = '' }
  catch (err) { loadError.value = errorMessage(err, '会话记录暂时无法加载，请稍后查看。') }
  finally { historyLoading.value = false; await bottom() }
}
async function send() {
  const text = question.value.trim()
  if (!text || !kb.value || locked.value || uncertain.value) return
  busy.value = true; sendError.value = ''; pendingQuestion.value = text; await bottom()
  try {
    if (!session.value) {
      const data = await request<ChatSession>('POST', '/sessions', { knowledge_base_id: kb.value })
      session.value = data.id; sessions.value.unshift(data)
    }
    const answer = await request<ChatMessage>('POST', '/sessions/' + session.value + '/messages', { question: text })
    messages.value.push({ id:'user-' + answer.id, role:'user', content:text, citations:[] }, answer)
    const row = sessions.value.find(item => item.id === session.value); if (row && row.title === '新会话') row.title = text
    question.value = ''; pendingQuestion.value = ''; await bottom()
  } catch (err) { uncertain.value = true; sendError.value = errorMessage(err, '请求未能完成，请先查看已有会话记录。') }
  finally { busy.value = false; await bottom() }
}
function keydown(event: KeyboardEvent) { if (event.ctrlKey && event.key === 'Enter' && !event.isComposing) { event.preventDefault(); void send() } }
async function initialize() {
  initialLoading.value = true; loadError.value = ''
  try {
    const [health, knowledge, history] = await Promise.all([request<{ model_backend: string }>('GET', '/health'), request<KnowledgeBase[]>('GET', '/knowledge-bases'), request<ChatSession[]>('GET', '/sessions')])
    mode.value = health.model_backend; kbs.value = knowledge; sessions.value = history
    kb.value = knowledge.find(item => item.id === route.query.kb)?.id || knowledge[0]?.id || ''
    if (typeof route.query.session === 'string') await openSession(route.query.session)
  } catch (err) { loadError.value = errorMessage(err, '工作空间暂时无法加载，请重新加载。') }
  finally { initialLoading.value = false; await bottom() }
}
function chooseSession(id: string) { if (!busy.value) void router.replace('/chat?session=' + id) }
watch(() => route.query.session, id => { if (typeof id === 'string' && id !== session.value) void openSession(id); else if (!id && session.value && !busy.value) reset() })
onMounted(initialize)
</script>
<template>
  <PageHeading title="AI 智能问答" description="向知识提问，让答案回到原文。" eyebrow="ASK YOUR KNOWLEDGE / 智能探索"><span v-if="mode === 'mock'" class="mode-badge"><i></i>离线演示模式</span></PageHeading>
  <div class="chat-workspace">
    <aside class="chat-sidepanel"><div class="chat-source-picker"><span class="panel-label"><el-icon><Collection /></el-icon>对话知识库</span><el-select v-model="kb" aria-label="对话知识库" :disabled="locked" placeholder="请选择知识库" @change="newSession"><el-option v-for="item in kbs" :key="item.id" :label="item.name" :value="item.id" /></el-select><p>{{ currentKB?.description || '选择一个知识库，从你的文档中寻找答案。' }}</p><el-button link type="primary" :icon="Document" :disabled="!kb || busy" @click="$router.push('/documents?kb=' + kb)">管理文档 <el-icon><ArrowRight /></el-icon></el-button></div>
      <el-button class="new-chat-button" :icon="Plus" :disabled="locked" @click="newSession">新建会话</el-button><div class="chat-session-label">最近会话 <router-link to="/history">查看全部</router-link></div>
      <div class="chat-session-list"><button v-for="item in sessions.slice(0, 8)" :key="item.id" :class="{ selected: session === item.id }" :disabled="busy" @click="chooseSession(item.id)"><el-icon><ChatDotRound /></el-icon><span>{{ item.title }}</span></button><p v-if="!sessions.length && !initialLoading" class="muted">你的对话会保存在这里。</p></div>
      <div class="chat-side-tip"><span>✦</span><strong>好问题，从具体开始</strong><p>描述你的场景，或明确想了解的内容，让知识更容易被找到。</p></div>
    </aside>
    <section class="chat-layout"><div class="chat-toolbar"><div><span class="assistant-mark">✦</span><div><strong>知序知识助手</strong><span>{{ session ? currentTitle : '每一次探索，都从一个问题开始' }}</span></div></div><span class="subtle-pill">基于文档回答</span></div>
      <div ref="scroll" class="chat-scroll" aria-label="聊天记录" :aria-busy="locked">
        <StatePanel v-if="initialLoading || historyLoading" kind="loading" :title="historyLoading ? '正在加载会话记录' : '正在连接知识空间'" />
        <StatePanel v-else-if="loadError" kind="error" title="暂时无法加载内容" :description="loadError"><el-button @click="session ? refresh() : initialize()">重新加载</el-button></StatePanel>
        <div v-else-if="!messages.length && !pendingQuestion" class="chat-empty"><div class="sparkle"><el-icon><MagicStick /></el-icon></div><span class="eyebrow">KNOWLEDGE AT YOUR FINGERTIPS</span><h3>有什么想了解的？</h3><p>从一个具体的问题开始，<br>一起探索文档里的答案。</p><div class="suggestion-list"><button v-for="text in suggestions" :key="text" :disabled="locked || !kb || uncertain" @click="question = text"><span>{{ text }}</span><el-icon><ArrowRight /></el-icon></button></div><el-button v-if="!kbs.length" type="primary" @click="$router.push('/knowledge')">先创建知识库</el-button></div>
        <template v-else><MessageItem v-for="message in messages" :key="message.id" :message="message" /><MessageItem v-if="pendingQuestion" :message="{ id:'pending-user', role:'user', content:pendingQuestion, citations:[] }" /></template>
        <div v-if="busy" class="answer-loading" role="status"><span class="assistant-mark">✦</span><div><strong>正在检索知识并生成回答…</strong><span class="typing-dots"><i></i><i></i><i></i></span></div></div>
      </div>
      <div class="composer"><el-alert v-if="uncertain" title="请求失败或结果尚未确认，已暂停发送。请先查看会话记录，避免重复提交。" :description="sendError" type="warning" :closable="false" show-icon class="send-error" /><div v-if="uncertain" class="uncertain-actions"><el-button v-if="session" :disabled="locked" @click="refresh">查看会话记录</el-button><el-button v-else @click="$router.push('/history')">前往会话历史</el-button><span>仅查看记录，不会自动重发问题。</span></div>
        <div class="composer-box"><el-input v-model="question" aria-label="问题" type="textarea" :autosize="{ minRows:2, maxRows:5 }" placeholder="输入你的问题，例如：这份文档的关键步骤是什么？" maxlength="4000" :disabled="locked || uncertain || !kb" @keydown="keydown" /><div class="composer-bottom"><span><kbd>Ctrl</kbd> + <kbd>Enter</kbd> 发送<span v-if="question.length" class="question-length">{{ question.length }} / 4000</span></span><el-button type="primary" :icon="Promotion" :loading="busy" :disabled="locked || uncertain || !question.trim() || !kb" @click="send">发送</el-button></div></div>
        <p class="composer-note">{{ mode === 'mock' ? '当前为离线演示，回答由检索片段生成。' : '回答基于当前知识库，请结合原文核实。' }} 引用可展开查看原文。</p>
      </div>
    </section>
  </div>
</template>
