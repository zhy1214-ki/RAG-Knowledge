<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Collection, Plus, Search, Document, EditPen, Delete, Calendar, ArrowRight } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { request, errorMessage } from '../api'
import type { KnowledgeBase } from '../types'
import { formatDate } from '../utils'
import PageHeading from '../components/PageHeading.vue'
import StatePanel from '../components/StatePanel.vue'
const rows = ref<KnowledgeBase[]>([]), loading = ref(true), error = ref(''), search = ref('')
const dialog = ref(false), selected = ref(''), saving = ref(false), deleting = ref(''), formError = ref('')
const formRef = ref<FormInstance>(), form = ref({ name: '', description: '' })
const rules: FormRules = { name: [{ required: true, whitespace: true, message: '请填写知识库名称', trigger: 'blur' }, { max: 120, message: '名称最多 120 个字符', trigger: 'blur' }] }
const filtered = computed(() => rows.value.filter(row => (row.name + ' ' + row.description).toLowerCase().includes(search.value.trim().toLowerCase())))
async function load() { loading.value = true; error.value = ''; try { rows.value = await request('GET', '/knowledge-bases') } catch (err) { error.value = errorMessage(err, '知识库加载失败，请刷新重试。') } finally { loading.value = false } }
function edit(row?: KnowledgeBase) { selected.value = row?.id || ''; form.value = { name: row?.name || '', description: row?.description || '' }; formError.value = ''; dialog.value = true }
async function save() {
  if (saving.value || !await formRef.value?.validate().catch(() => false)) return
  saving.value = true; formError.value = ''
  try { await request(selected.value ? 'PUT' : 'POST', '/knowledge-bases' + (selected.value ? '/' + selected.value : ''), { name: form.value.name.trim(), description: form.value.description }); dialog.value = false; ElMessage.success(selected.value ? '知识库已更新' : '知识库已创建'); await load() }
  catch (err) { formError.value = errorMessage(err, '暂时无法保存，请检查列表后再操作。') }
  finally { saving.value = false }
}
async function remove(row: KnowledgeBase) {
  if (deleting.value) return
  try { await ElMessageBox.confirm('将删除「' + row.name + '」及关联的文档、索引和会话，此操作无法撤销。', '删除知识库', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }) } catch { return }
  deleting.value = row.id
  try { await request('DELETE', '/knowledge-bases/' + row.id); ElMessage.success('知识库已删除'); await load() }
  catch (err) { error.value = errorMessage(err, '删除结果尚未确认，请先刷新列表。') }
  finally { deleting.value = '' }
}
onMounted(load)
</script>
<template>
  <PageHeading title="知识库管理" description="按主题组织文档，构建清晰、可靠的知识空间。" eyebrow="KNOWLEDGE / 知识资产"><el-button type="primary" :icon="Plus" @click="edit()">创建知识库</el-button></PageHeading>
  <div class="collection-toolbar"><span class="section-count">全部知识库 <b>{{ loading ? '—' : rows.length }}</b></span><el-input v-model="search" aria-label="搜索知识库" :prefix-icon="Search" clearable placeholder="搜索知识库名称或描述" /></div>
  <StatePanel v-if="loading" kind="loading" title="正在加载知识库" description="让相关的文档，汇聚在一起。" />
  <StatePanel v-else-if="error" kind="error" title="知识库暂时未能加载" :description="error"><el-button type="primary" @click="load">重新加载</el-button></StatePanel>
  <div v-else-if="filtered.length" class="kb-grid"><el-card v-for="row in filtered" :key="row.id" class="kb-card" shadow="never"><div class="kb-card-top"><span class="folder-icon"><el-icon><Collection /></el-icon></span><span class="subtle-pill">知识空间</span></div><h3 class="kb-name">{{ row.name }}</h3><p class="kb-description">{{ row.description || '还没有描述，添加一段介绍，帮助你快速了解这个知识库。' }}</p><div class="kb-meta"><el-icon><Calendar /></el-icon>{{ formatDate(row.created_at) }} 创建</div><div class="kb-card-actions"><el-button type="primary" link :icon="Document" @click="$router.push('/documents?kb=' + row.id)">文档</el-button><el-button link :icon="EditPen" @click="edit(row)">编辑</el-button><el-button link type="danger" :icon="Delete" :loading="deleting === row.id" :disabled="!!deleting" @click="remove(row)">删除</el-button><el-icon class="card-arrow"><ArrowRight /></el-icon></div></el-card></div>
  <StatePanel v-else kind="empty" :title="search ? '没有找到相关知识库' : '创建第一个知识库，开始整理知识'" :description="search ? '换一个关键词，或清空搜索条件。' : '按产品、项目或团队分类，让每一份文档都有自己的位置。'"><el-button v-if="search" @click="search = ''">清空搜索</el-button><el-button v-else type="primary" :icon="Plus" @click="edit()">创建知识库</el-button></StatePanel>
  <div class="page-tip"><el-icon><Collection /></el-icon>小建议：一个知识库聚焦一个主题，提问时更容易找到准确的依据。</div>
  <el-dialog v-model="dialog" :title="selected ? '编辑知识库' : '创建知识库'" width="520px" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" @closed="formRef?.clearValidate()"><p class="dialog-intro">为相关文档建立一个清晰的空间。</p><el-alert v-if="formError" :title="formError" type="error" :closable="false" class="inline-alert" show-icon /><el-form ref="formRef" :model="form" :rules="rules" label-position="top" :disabled="saving" @submit.prevent="save"><el-form-item label="名称" prop="name"><el-input v-model="form.name" aria-label="知识库名称" maxlength="120" placeholder="例如：产品使用指南" /></el-form-item><el-form-item label="描述"><el-input v-model="form.description" aria-label="知识库描述" type="textarea" :rows="4" maxlength="4000" placeholder="简单介绍这里会收录哪些内容…" show-word-limit /></el-form-item></el-form><template #footer><el-button :disabled="saving" @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template></el-dialog>
</template>
