import { createRouter, createWebHistory } from 'vue-router'
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../views/Login.vue'), meta: { title: '欢迎登录' } },
    { path: '/', component: () => import('../views/Home.vue'), meta: { title: '工作台' } },
    { path: '/knowledge', component: () => import('../views/Knowledge.vue'), meta: { title: '知识库管理' } },
    { path: '/documents', component: () => import('../views/Documents.vue'), meta: { title: '文档管理' } },
    { path: '/chat', component: () => import('../views/Chat.vue'), meta: { title: 'AI 智能问答' } },
    { path: '/history', component: () => import('../views/History.vue'), meta: { title: '会话历史' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
router.beforeEach(to => {
  if (to.path !== '/login' && !sessionStorage.getItem('token')) return '/login'
})
export default router
