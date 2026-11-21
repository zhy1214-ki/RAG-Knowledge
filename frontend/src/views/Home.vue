<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Collection, Document, ChatDotRound, ArrowRight, Plus, Upload, MagicStick } from '@element-plus/icons-vue'
import { request } from '../api'
import { useAuth } from '../stores/auth'
import type { KnowledgeBase, ChatSession, DocumentRow } from '../types'
import { formatDate } from '../utils'
import PageHeading from '../components/PageHeading.vue'
import StatePanel from '../components/StatePanel.vue'
const auth = useAuth(), kbs = ref<KnowledgeBase[]>([]), sessions = ref<ChatSession[]>([])
const loading = ref(true), error = ref(''), kbCount = ref<number | null>(null), sessionCount = ref<number | null>(null), docCount = ref<number | null>(null)
async function load() {
  loading.value = true; error.value = ''; kbCount.value = sessionCount.value = docCount.value = null
  const [knowledge, history] = await Promise.allSettled([request<KnowledgeBase[]>('GET', '/knowledge-bases'), request<ChatSession[]>('GET', '/sessions')])
  if (knowledge.status === 'fulfilled') {
    kbs.value = knowledge.value; kbCount.value = knowledge.value.length
    const docs = await Promise.allSettled(knowledge.value.map(k => request<DocumentRow[]>('GET', '/knowledge-bases/' + k.id + '/documents')))
    if (docs.every(d => d.status === 'fulfilled')) docCount.value = docs.reduce((total, result) => total + (result.status === 'fulfilled' ? result.value.length : 0), 0)
    else error.value = '部分文档数据暂时无法加载，未确认的统计以「—」显示。'
  } else { kbs.value = []; error.value = '知识库数据暂时无法加载，未确认的统计以「—」显示。' }
  if (history.status === 'fulfilled') { sessions.value = history.value; sessionCount.value = history.value.length }
  else { sessions.value = []; error.value = '部分数据暂时无法加载，未确认的统计以「—」显示。' }
  loading.value = false
}
onMounted(load)
</script>
<template>
  <PageHeading :title="'你好，' + auth.username" description="从这里整理知识，发现新的答案。" eyebrow="OVERVIEW / 工作台"><el-button type="primary" :icon="MagicStick" @click="$router.push('/chat')">开始智能问答</el-button></PageHeading>
  <section class="hero"><div><span class="hero-kicker">让知识，成为团队的共同语言</span><h1>知识汇聚于此，<br>答案<span>触手可及。</span></h1><p>上传文档，用自然语言探索你的知识库。<br>不止获得答案，更能找到答案的依据。</p><el-button @click="$router.push('/knowledge')">整理我的知识库 <el-icon><ArrowRight /></el-icon></el-button></div>
    <div class="hero-visual" aria-hidden="true"><div class="hero-orbit orbit-one"></div><div class="hero-orbit orbit-two"></div><div class="hero-doc"><el-icon><Document /></el-icon><span>原始文档</span><i></i><i></i></div><div class="hero-core"><span>✦</span></div><div class="hero-answer"><span class="hero-check">✓</span><div><strong>每个答案，都有来源</strong><span>连接文档与知识的价值</span></div></div><span class="hero-dot dot-one"></span><span class="hero-dot dot-two"></span></div>
  </section>
  <el-alert v-if="error" type="warning" :closable="false" show-icon class="inline-alert"><template #title>{{ error }}</template><el-button link type="primary" :disabled="loading" @click="load">刷新数据</el-button></el-alert>
  <div class="stats" :aria-busy="loading">
    <router-link v-for="stat in [{ label:'知识库', value:kbCount, note:'按主题组织团队知识', icon:Collection, path:'/knowledge', color:'blue' },{ label:'已上传文档', value:docCount, note:'让经验沉淀为共同资产', icon:Document, path:'/documents', color:'violet' },{ label:'问答会话', value:sessionCount, note:'留住每一次有价值的探索', icon:ChatDotRound, path:'/history', color:'teal' }]" :key="stat.label" :to="stat.path" :class="['stat-card', stat.color]"><div class="stat-top"><span>{{ stat.label }}</span><el-icon class="stat-icon"><component :is="stat.icon" /></el-icon></div><div class="stat-value">{{ stat.value === null ? '—' : stat.value }}</div><div class="stat-bottom"><span>{{ stat.note }}</span><el-icon><ArrowRight /></el-icon></div></router-link>
  </div>
  <div class="home-columns"><section><div class="section-title"><div><h3>我的知识库</h3><span class="muted">为每个主题，留一个清晰的空间</span></div><el-button link type="primary" @click="$router.push('/knowledge')">查看全部 <el-icon><ArrowRight /></el-icon></el-button></div>
    <StatePanel v-if="loading" kind="loading" title="正在加载知识空间" />
    <div v-else-if="kbs.length" class="home-kb-list"><router-link v-for="kb in kbs.slice(0, 4)" :key="kb.id" :to="'/documents?kb=' + kb.id" class="home-kb-row"><span class="folder-icon"><el-icon><Collection /></el-icon></span><div><strong>{{ kb.name }}</strong><p>{{ kb.description || '添加文档，让知识在这里积累。' }}</p></div><el-icon><ArrowRight /></el-icon></router-link></div>
    <StatePanel v-else :kind="kbCount === null ? 'error' : 'empty'" :title="kbCount === null ? '知识库暂时未能加载' : '从第一个知识库开始'" description="把相关的文档放在一起，让查找更简单。"><el-button type="primary" :icon="Plus" @click="$router.push('/knowledge')">创建知识库</el-button></StatePanel>
  </section><section><div class="section-title"><div><h3>最近的探索</h3><span class="muted">继续上一次的思考</span></div><el-button link type="primary" @click="$router.push('/history')">全部会话</el-button></div>
    <div v-if="sessions.length" class="recent-sessions"><router-link v-for="session in sessions.slice(0, 4)" :key="session.id" :to="'/chat?session=' + session.id"><span class="recent-chat-icon"><el-icon><ChatDotRound /></el-icon></span><div><strong>{{ session.title }}</strong><span>{{ formatDate(session.created_at, true) }} 创建</span></div><el-icon><ArrowRight /></el-icon></router-link></div>
    <StatePanel v-else :kind="loading ? 'loading' : sessionCount === null ? 'error' : 'empty'" :title="loading ? '正在加载会话' : sessionCount === null ? '会话暂时未能加载' : '你的探索，从一个问题开始'" description="问答会话会保存在这里，方便随时回顾。" />
  </section></div>
  <div class="quick-start"><span class="quick-start-label">快速开始</span><button @click="$router.push('/knowledge')"><span>01</span><el-icon><Collection /></el-icon>创建知识库</button><i></i><button @click="$router.push('/documents')"><span>02</span><el-icon><Upload /></el-icon>上传文档</button><i></i><button @click="$router.push('/chat')"><span>03</span><el-icon><MagicStick /></el-icon>开始提问</button></div>
</template>
