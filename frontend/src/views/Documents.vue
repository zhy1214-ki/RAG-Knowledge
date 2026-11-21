<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { UploadFilled, Upload, Refresh, Search, Document, Delete, ChatDotRound } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { request, api, errorMessage } from '../api'
import type { DocumentRow, KnowledgeBase } from '../types'
import { fileSize } from '../utils'
import PageHeading from '../components/PageHeading.vue'
import StatePanel from '../components/StatePanel.vue'
const route = useRoute(), kbs = ref<KnowledgeBase[]>([]), kb = ref(''), rows = ref<DocumentRow[]>([])
const loading = ref(true), error = ref(''), uploading = ref(false), uploadUncertain = ref(false), picker = ref<HTMLInputElement>()
const search = ref(''), status = ref(''), deleting = ref(''), dragging = ref(false)
const uploadProgress = ref<number | null>(null), uploadingName = ref('')
const labels: Record<string, string> = { uploaded:'等待处理', processing:'解析与索引中', indexed:'已索引', failed:'处理失败', deleting:'等待重试删除' }
const reasons: Record<string, string> = { PARSE_ERROR:'无法提取文本，请检查文件；扫描 PDF 需先 OCR。', EMBEDDING_ERROR:'向量生成服务不可用，请先查看处理状态。', VECTOR_ERROR:'向量数据库暂不可用，请稍后查看处理状态。', PROCESS_INTERRUPTED:'处理被中断，请检查已有文档后再操作。', INTERNAL_ERROR:'文档处理异常，请检查文件或联系管理员。' }
const pending = computed(() => rows.value.some(row => ['uploaded', 'processing'].includes(row.status)))
const filtered = computed(() => rows.value.filter(row => row.name.toLowerCase().includes(search.value.trim().toLowerCase()) && (!status.value || row.status === status.value)))
const canUpload = computed(() => !!kb.value && !loading.value && !uploading.value && !uploadUncertain.value)
let timer: ReturnType<typeof setInterval> | undefined, sequence = 0, fetching = false, disposed = false
async function load(visible = true) {
  const id = kb.value, current = ++sequence
  if (visible) loading.value = true
  fetching = true; error.value = ''
  try { const data = id ? await request<DocumentRow[]>('GET', '/knowledge-bases/' + id + '/documents') : []; if (!disposed && current === sequence && id === kb.value) rows.value = data }
  catch (err) { if (!disposed && current === sequence) error.value = errorMessage(err, '文档列表加载失败，请刷新查看处理状态。') }
  finally { if (current === sequence) { loading.value = false; fetching = false } }
}
async function initialize() {
  loading.value = true; error.value = ''
  try { kbs.value = await request('GET', '/knowledge-bases'); kb.value = kbs.value.find(k => k.id === route.query.kb)?.id || kbs.value[0]?.id || ''; await load() }
  catch (err) { error.value = errorMessage(err, '暂时无法加载知识库，请刷新重试。'); loading.value = false }
}
async function change() { rows.value = []; search.value = ''; status.value = ''; uploadUncertain.value = false; await load() }
async function uploadFile(file?: File) {
  if (!file || !canUpload.value) return
  if (!/\.(pdf|docx|txt|md)$/i.test(file.name) || file.size > 20 * 1024 * 1024 || !file.size) { ElMessage.warning('请选择非空且不超过 20 MB 的 PDF、DOCX、TXT 或 Markdown'); return }
  uploading.value = true; uploadingName.value = file.name; uploadProgress.value = null
  try {
    const form = new FormData(); form.append('file', file)
    const response = await api.post('/knowledge-bases/' + kb.value + '/documents', form, { onUploadProgress(progress) {
      uploadProgress.value = progress.total ? Math.min(100, Math.round(progress.loaded * 100 / progress.total)) : null
    } })
    sequence++; fetching = false
    rows.value = [response.data.data, ...rows.value]; ElMessage.success('上传成功，正在解析文档')
  } catch { uploadUncertain.value = true }
  finally { uploading.value = false }
}
async function upload(event: Event) { const input = event.target as HTMLInputElement; await uploadFile(input.files?.[0]); input.value = '' }
async function drop(event: DragEvent) { dragging.value = false; const files = event.dataTransfer?.files; if (files && files.length > 1) { ElMessage.warning('每次上传一份文档，便于确认处理结果。'); return } await uploadFile(files?.[0]) }
async function remove(row: DocumentRow) {
  if (deleting.value) return
  try { await ElMessageBox.confirm('将删除「' + row.name + '」及其向量索引，此操作无法撤销。', '删除文档', { type:'warning', confirmButtonText:'确认删除', cancelButtonText:'取消' }) } catch { return }
  deleting.value = row.id
  try { await request('DELETE', '/knowledge-bases/' + kb.value + '/documents/' + row.id); ElMessage.success('文档已删除'); await load() }
  catch (err) { error.value = errorMessage(err, '删除结果尚未确认，请先刷新文档列表。') }
  finally { deleting.value = '' }
}
onMounted(async () => { await initialize(); if (disposed) return; timer = setInterval(() => { if (pending.value && !fetching && !error.value) void load(false) }, 1500) })
onUnmounted(() => { disposed = true; clearInterval(timer); sequence++ })
</script>
<template>
  <PageHeading title="文档管理" description="把文档转化为可检索的知识，让回答有源可溯。" eyebrow="DOCUMENTS / 知识来源"><el-button :icon="Refresh" :disabled="uploading || loading" @click="kbs.length ? load() : initialize()">刷新文档列表</el-button><el-button type="primary" :icon="Upload" :disabled="!canUpload" :loading="uploading" @click="picker?.click()">上传文档</el-button><input ref="picker" type="file" hidden accept=".pdf,.docx,.txt,.md" @change="upload" /></PageHeading>
  <div class="document-selector"><div><span class="field-label">当前知识库</span><el-select v-model="kb" aria-label="当前知识库" :disabled="uploading || loading" placeholder="请选择知识库" @change="change"><el-option v-for="item in kbs" :key="item.id" :label="item.name" :value="item.id" /></el-select></div><el-button link type="primary" :icon="ChatDotRound" :disabled="!kb" @click="$router.push('/chat?kb=' + kb)">去知识库提问</el-button></div>
  <section :class="['upload-zone', { dragging, 'upload-zone-disabled': !canUpload }]" @dragover.prevent="dragging = canUpload" @dragleave.prevent="dragging = false" @drop.prevent="drop">
    <span class="upload-symbol"><el-icon><UploadFilled /></el-icon></span><div class="upload-zone-text"><h3>{{ uploading ? '正在上传文档' : '把你的知识，带到这里' }}</h3><p>{{ uploading ? uploadingName : '拖拽一份文档到这里，或选择本地文件上传' }}</p><span>PDF · DOCX · TXT · Markdown<span class="dot-separator">·</span>单个文件不超过 20 MB</span></div><el-button plain :disabled="!canUpload" @click="picker?.click()">选择文件</el-button>
    <div v-if="uploading" class="upload-progress" role="status"><el-progress :percentage="uploadProgress ?? 100" :indeterminate="uploadProgress === null" :show-text="uploadProgress !== null" /><span>{{ uploadProgress === 100 ? '文件已传输，正在等待处理结果…' : '正在传输文件，请勿重复上传…' }}</span></div>
  </section>
  <el-alert v-if="uploadUncertain" title="上传失败或结果尚未确认，请先刷新文档列表，避免重复上传。" description="刷新只会查看已有记录，不会重新上传。当前已暂停再次上传。" type="warning" :closable="false" show-icon class="inline-alert" />
  <div class="document-summary"><span><i class="status-dot success"></i>已索引 <b>{{ rows.filter(r => r.status === 'indexed').length }}</b></span><span><i class="status-dot processing"></i>处理中 <b>{{ rows.filter(r => ['uploaded','processing'].includes(r.status)).length }}</b></span><span><i class="status-dot danger"></i>失败 <b>{{ rows.filter(r => r.status === 'failed').length }}</b></span><span class="summary-note">扫描 PDF 请先完成 OCR</span></div>
  <el-card class="document-card" shadow="never"><div class="table-toolbar"><h3>文档列表 <span class="count-badge">{{ rows.length }}</span></h3><div class="table-filters"><el-input v-model="search" aria-label="搜索文档" :prefix-icon="Search" clearable placeholder="搜索文档名称" /><el-select v-model="status" aria-label="文档状态" placeholder="全部状态" clearable><el-option label="等待处理" value="uploaded" /><el-option label="解析与索引中" value="processing" /><el-option label="已索引" value="indexed" /><el-option label="处理失败" value="failed" /></el-select></div></div>
    <StatePanel v-if="loading" kind="loading" title="正在加载文档" />
    <StatePanel v-else-if="error" kind="error" title="暂时无法获取文档" :description="error"><el-button @click="kbs.length ? load() : initialize()">重新加载</el-button></StatePanel>
    <el-table v-else-if="filtered.length" :data="filtered" class="document-table"><el-table-column label="文档名称" min-width="220"><template #default="{ row }"><div class="file-cell"><span :class="['file-icon', row.file_type]"><el-icon><Document /></el-icon><small>{{ row.file_type.toUpperCase() }}</small></span><div><strong :title="row.name">{{ row.name }}</strong><span>{{ fileSize(row.size) }}</span></div></div></template></el-table-column><el-table-column label="处理状态" min-width="225"><template #default="{ row }"><span :class="['status-pill', row.status]" role="status"><i></i>{{ labels[row.status] || '等待确认' }}</span><el-progress v-if="['uploaded','processing'].includes(row.status)" :percentage="Math.min(100, Math.max(0, row.progress))" :stroke-width="4" class="index-progress" /><p v-if="row.error_code" class="document-error">{{ reasons[row.error_code] || '文档处理未完成，请检查文件后再操作。' }}</p></template></el-table-column><el-table-column label="文本片段" width="100"><template #default="{ row }"><span class="chunk-count">{{ row.chunk_count }} 段</span></template></el-table-column><el-table-column label="操作" width="118" align="right"><template #default="{ row }"><el-button link type="danger" :icon="Delete" :loading="deleting === row.id" :disabled="!!deleting" @click="remove(row)">{{ row.status === 'deleting' ? '重试删除' : '删除' }}</el-button></template></el-table-column></el-table>
    <StatePanel v-else kind="empty" :title="!kb ? '请先创建知识库' : search || status ? '没有找到匹配的文档' : '还没有文档，上传一份开始吧'" description="已索引的文档会成为智能问答的参考来源。"><el-button v-if="!kb" type="primary" @click="$router.push('/knowledge')">创建知识库</el-button><el-button v-else-if="search || status" @click="search = ''; status = ''">清空筛选</el-button><el-button v-else :disabled="!canUpload" @click="picker?.click()">选择文件</el-button></StatePanel>
  </el-card>
</template>
