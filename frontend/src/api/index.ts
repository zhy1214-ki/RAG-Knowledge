import axios from 'axios'
import { ElMessage } from 'element-plus'
export const api = axios.create({ baseURL: '/api', timeout: 120000 })
export function errorMessage(error: unknown, fallback = '服务暂时不可用，请稍后查看处理状态。') {
  if (!axios.isAxiosError(error)) return fallback
  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') return '请求超时，结果尚未确认。请先查看处理状态或会话记录，避免重复提交。'
  if (!error.response) return '服务连接中断，结果尚未确认，请先查看记录'
  if (error.response.status === 401) return error.config?.url?.includes('/auth/') ? '用户名或密码错误，请重新输入。' : '登录已过期，请重新登录。'
  const code = (error.response.data as { code?: string } | undefined)?.code
  if (code === 'CONFLICT') return error.config?.url?.includes('/auth/') ? '该用户名已被使用，请换一个用户名。' : '名称已存在，请使用其他名称。'
  const messages: Record<string, string> = {
    VALIDATION_ERROR: '输入信息不符合要求，请检查后提交。',
    MODEL_UNAVAILABLE: '模型服务暂时不可用，已暂停发送，请先查看会话记录。',
    MODEL_DISABLED: '当前环境尚未开启模型服务，请联系管理员。',
    EMBEDDING_ERROR: '知识处理服务暂时不可用，请先查看文档或会话状态。',
    VECTOR_ERROR: '知识检索服务暂时不可用，请稍后查看处理状态。',
    DATABASE_ERROR: '数据服务暂时不可用，请先查看已有记录。',
    NOT_FOUND: '内容不存在或已被删除，请刷新列表。',
    USAGE_STOPPED: "模型调用已暂停，请先核对用量和失败记录。",
    USAGE_LIMIT: "模型请求次数或估算预算已达本环境上限。",
    USAGE_RATE_LIMIT: "模型请求过于频繁，请稍后操作，不要重复提交。",
    USAGE_BUSY: "已有任务进行中，请等待当前任务完成。",
    DUPLICATE_REQUEST: "近期已提交相同内容，请先查看处理状态或会话记录。",
    TOKEN_LIMIT: "输入超过本环境的Token估算上限，请缩小文档或上下文。",
    USAGE_STORAGE: "用量记录不可用，已安全阻断模型调用。",
    DOCUMENT_LIMIT: "文档片段超过本环境上限，请拆分后再处理。",
    ACCEPTANCE_STOPPED: '本次操作已停止，请先查看已有记录，不要重复提交。',
  }
  return code && messages[code] || fallback
}
api.interceptors.request.use(config => {
  const token = sessionStorage.getItem('token')
  if (token) config.headers.Authorization = 'Bearer ' + token
  return config
})
api.interceptors.response.use(response => response, error => {
  if (error.response?.status === 401 && !error.config?.url?.includes('/auth/')) {
    sessionStorage.removeItem('token')
    window.location.assign('/login')
  }
  ElMessage.error(errorMessage(error))
  return Promise.reject(error)
})
export async function request<T = any>(method: string, url: string, data?: unknown): Promise<T> {
  return (await api.request({ method, url, data })).data.data
}
