<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock, ArrowRight, Document, ChatDotRound, CircleCheck } from '@element-plus/icons-vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuth } from '../stores/auth'
import { request, errorMessage } from '../api'
const router = useRouter(), auth = useAuth(), formRef = ref<FormInstance>()
const register = ref(false), busy = ref(false), error = ref('')
const form = reactive({ username: '', password: '' })
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }, { pattern: /^[a-zA-Z0-9_-]{3,64}$/, message: '使用 3–64 位字母、数字、下划线或短横线', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }, { min: 8, max: 128, message: '密码需要 8–128 位字符', trigger: 'blur' }],
}
function switchMode() { if (busy.value) return; register.value = !register.value; error.value = ''; formRef.value?.clearValidate() }
async function submit() {
  if (busy.value || !await formRef.value?.validate().catch(() => false)) return
  busy.value = true; error.value = ''
  try {
    if (register.value) {
      await request('POST', '/auth/register', form)
      register.value = false
      ElMessage.success('账号已创建，正在为你登录')
    }
    await auth.login(form.username, form.password)
    await router.push('/')
  } catch (err) { error.value = errorMessage(err, '暂时无法登录，请稍后再试。') }
  finally { busy.value = false }
}
</script>
<template>
  <div class="login-page">
    <section class="login-art">
      <div class="brand"><span class="brand-mark">知</span><span class="brand-type">知序<span>KNOWLEDGE WORKSPACE</span></span></div>
      <div class="login-story"><span class="login-eyebrow"><span></span>你的团队知识工作空间</span><h1>知识不止于存储，<br>更在于<span>找到答案。</span></h1><p>把分散的文档整理成清晰的知识，<br>让每一次提问，都得到有据可查的回答。</p>
        <div class="login-diagram" aria-hidden="true"><div class="diagram-document"><el-icon><Document /></el-icon><span>团队文档</span><i></i><i></i><i></i></div><span class="diagram-connector">········</span><span class="diagram-core">知</span><span class="diagram-connector">········</span><div class="diagram-answer"><el-icon><ChatDotRound /></el-icon><strong>可靠的答案</strong><span><el-icon><CircleCheck /></el-icon>附带原文引用</span></div></div>
        <div class="login-features"><span><el-icon><CircleCheck /></el-icon>集中管理</span><span><el-icon><CircleCheck /></el-icon>自然语言提问</span><span><el-icon><CircleCheck /></el-icon>来源可追溯</span></div>
      </div>
      <p class="login-copyright">知序 · KNOWLEDGE, CONNECTED.</p>
    </section>
    <section class="login-form-wrap"><div class="login-form"><span class="eyebrow">WELCOME TO ZHIXU</span><h2>{{ register ? '创建你的账号' : '欢迎回来' }}</h2><p class="muted">{{ register ? '开启属于你的知识工作空间' : '登录知序，继续探索团队知识' }}</p>
      <el-alert v-if="error" class="inline-alert" :title="error" type="error" :closable="false" show-icon />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名" prop="username"><el-input v-model="form.username" aria-label="用户名" :prefix-icon="User" size="large" placeholder="输入用户名" maxlength="64" autocomplete="username" :disabled="busy" /></el-form-item>
        <el-form-item label="密码" prop="password"><el-input v-model="form.password" aria-label="密码" :prefix-icon="Lock" type="password" show-password size="large" placeholder="输入至少 8 位密码" maxlength="128" :autocomplete="register ? 'new-password' : 'current-password'" :disabled="busy" /></el-form-item>
        <el-button native-type="submit" type="primary" :loading="busy" :disabled="busy" class="login-submit">{{ register ? '注册并进入' : '登 录' }}<el-icon v-if="!busy"><ArrowRight /></el-icon></el-button>
      </el-form>
      <button type="button" class="login-switch" :disabled="busy" @click="switchMode">{{ register ? '已有账号？返回登录' : '还没有账号？创建账号' }}</button>
      <div class="login-trust"><el-icon><Lock /></el-icon>你的知识空间，仅由你的账号访问</div>
    </div></section>
  </div>
</template>
