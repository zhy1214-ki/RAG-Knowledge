<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from './stores/auth'
import { House, Collection, Document, ChatDotRound, Clock, SwitchButton, ArrowRight } from '@element-plus/icons-vue'
const route = useRoute(), router = useRouter(), auth = useAuth()
const menus = [
  { path: '/', text: '系统首页', icon: House }, { path: '/knowledge', text: '知识库管理', icon: Collection },
  { path: '/documents', text: '文档管理', icon: Document }, { path: '/chat', text: 'AI 智能问答', icon: ChatDotRound },
  { path: '/history', text: '会话历史', icon: Clock },
]
function logout() { auth.logout(); router.push('/login') }
</script>
<template>
  <router-view v-if="route.path === '/login'" />
  <div v-else :class="['app-layout', { 'is-chat-route': route.path === '/chat' }]">
    <aside class="sidebar">
      <router-link to="/" class="brand" aria-label="知序首页"><span class="brand-mark">知</span><span class="brand-type">知序<span>KNOWLEDGE WORKSPACE</span></span></router-link>
      <div class="nav-label">工作空间</div>
      <nav aria-label="主导航"><router-link v-for="menu in menus" :key="menu.path" :to="menu.path" :class="{ active: route.path === menu.path }"><el-icon><component :is="menu.icon" /></el-icon><span>{{ menu.text }}</span><span v-if="menu.path === '/chat'" class="nav-ai">AI</span></router-link></nav>
      <div class="sidebar-bottom"><div class="workspace-note"><span class="note-icon">✦</span><strong>让知识，流动起来</strong><p>每一次提问，都从可靠的<br>原始文档出发。</p><router-link to="/chat">开始探索 <el-icon><ArrowRight /></el-icon></router-link></div>
        <div class="sidebar-profile"><span class="avatar">{{ auth.username.slice(0, 1).toUpperCase() || 'U' }}</span><div><strong>{{ auth.username || '我的账号' }}</strong><span>个人工作空间</span></div></div>
      </div>
    </aside>
    <div class="workspace">
      <header class="topbar"><div class="breadcrumb"><span class="workspace-crumb">工作空间</span><span class="crumb-divider">/</span><strong>{{ route.meta.title }}</strong></div><div class="account"><span class="workspace-pill"><span></span>我的知识空间</span><el-button text :icon="SwitchButton" @click="logout">退出</el-button></div></header>
      <main class="content"><router-view /></main><footer>知序 Knowledge · 让每一个答案，都有据可查</footer>
    </div>
  </div>
</template>
