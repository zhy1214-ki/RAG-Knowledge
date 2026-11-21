import { test, expect, type Page } from '@playwright/test'

async function mockApi(page: Page, options: {
  authenticated?: boolean; historyBroken?: boolean; messageError?: string;
  uploadError?: boolean; documentError?: string; noEvidence?: boolean; slow?: boolean;
} = {}) {
  const state = { uploads: 0, posts: 0, historyReads: 0, authChecks: 0, sessions: [] as any[], messages: [] as any[],
    documents: [] as any[], kbs: [{ id: 'kb1', name: 'M5 合成知识库', description: '虚构测试', owner_id: 'user1', created_at: '2026-11-18T00:00:00Z' }] }
  if (options.authenticated !== false) {
    await page.addInitScript(() => { sessionStorage.setItem('token', 'm5-fictional-token'); sessionStorage.setItem('username', 'm5_user') })
  }
  const citation = { source_id: 2, chunk_id: 'chunk2', document_id: 'doc1', knowledge_base_id: 'kb1',
    source_name: 'real-rag-policy.txt', source_location: { format: 'txt' }, text: 'The return period is 17 days.', score: 0.72 }
  const doc = { id: 'doc1', knowledge_base_id: 'kb1', name: 'real-rag-policy.txt', file_type: 'txt',
    size: 179, status: options.documentError ? 'failed' : 'indexed', error_code: options.documentError || null, progress: 100, chunk_count: 1 }
  if (options.documentError) state.documents = [doc]
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const req = route.request(), path = new URL(req.url()).pathname.replace('/api', ''), method = req.method()
    async function ok(data: unknown, status = 200) { await route.fulfill({ status, json: { code: 'OK', message: '成功', data } }) }
    async function fail(code: string) { await route.fulfill({ status: 503, json: { code, message: code === 'DATABASE_ERROR' ? '数据库暂时不可用' : '模型服务不可用', data: null, request_id: 'fake-id' } }) }
    if (path === '/health') return ok({ status: 'ok', model_backend: 'qwen' })
    if (path === '/auth/login') return ok({ access_token: 'm5-fictional-token', token_type: 'bearer', user: { id: 'user1', username: 'm5_user' } })
    expect(req.headers().authorization).toBe('Bearer m5-fictional-token')
    state.authChecks++
    if (path === '/knowledge-bases' && method === 'GET') return ok(state.kbs)
    if (path === '/knowledge-bases' && method === 'POST') {
      const row = { ...state.kbs[0], ...req.postDataJSON() }; state.kbs = [row]; return ok(row, 201)
    }
    if (path === '/knowledge-bases/kb1/documents' && method === 'GET') return ok(state.documents)
    if (path === '/knowledge-bases/kb1/documents' && method === 'POST') {
      state.uploads++
      if (options.slow) await new Promise(resolve => setTimeout(resolve, 250))
      if (options.uploadError) return fail('DATABASE_ERROR')
      state.documents = [doc]
      return ok({ ...doc, status: 'uploaded', progress: 0 }, 202)
    }
    if (path === '/sessions' && method === 'GET') return ok(state.sessions)
    if (path === '/sessions' && method === 'POST') {
      const row = { id: 'session1', ...req.postDataJSON(), title: '新会话', created_at: '2026-11-18T00:00:00Z' }
      state.sessions = [row]; return ok(row, 201)
    }
    if (path === '/sessions/session1' && method === 'GET') return ok(state.sessions[0])
    if (path === '/sessions/session1/messages' && method === 'GET') {
      state.historyReads++
      if (options.historyBroken) return fail('DATABASE_ERROR')
      return ok(state.messages)
    }
    if (path === '/sessions/session1/messages' && method === 'POST') {
      state.posts++
      if (options.slow) await new Promise(resolve => setTimeout(resolve, 250))
      if (options.messageError) return fail(options.messageError)
      const question = req.postDataJSON().question
      const answer = { id: 'answer1', session_id: 'session1', role: 'assistant',
        content: options.noEvidence ? '当前知识库中没有足够证据回答这个问题，请补充相关文档或调整问题。' : 'The return period is 17 days [2].',
        citations: options.noEvidence ? [] : [citation], created_at: '2026-11-18T00:00:00Z' }
      state.messages = [{ id: 'question1', role: 'user', content: question, citations: [] }, answer]
      state.sessions[0].title = question
      return ok(answer)
    }
    throw new Error('UNPLANNED_OFFLINE_API ' + method + ' ' + path)
  })
  return state
}

async function ask(page: Page) {
  await page.goto('/chat')
  await expect(page.getByRole('textbox', { name: '问题' })).toBeEnabled()
  await page.getByRole('textbox', { name: '问题' }).fill('What is the return period?')
  await page.getByRole('button', { name: '发送', exact: true }).click()
}

test('POST成功直接展示回答，历史GET故障不会导致重提', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  const state = await mockApi(page, { historyBroken: true, slow: true })
  await ask(page)
  await page.getByRole('textbox', { name: '问题' }).dispatchEvent('keydown', { key: 'Enter', ctrlKey: true })
  await expect(page.locator('.chat-message.assistant')).toContainText('17 days')
  await expect(page.getByRole('textbox', { name: '问题' })).toHaveValue('')
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
  expect(state.posts).toBe(1); expect(state.historyReads).toBe(0); expect(errors).toEqual([])
})

for (const code of ['MODEL_UNAVAILABLE', 'DATABASE_ERROR']) {
  test('问答异常暂停发送且只读核对记录 ' + code, async ({ page }) => {
    const state = await mockApi(page, { messageError: code })
    await ask(page)
    await expect(page.getByText('请求失败或结果尚未确认，已暂停发送。请先查看会话记录，避免重复提交。')).toBeVisible()
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
    await page.getByRole('button', { name: '查看会话记录' }).click()
    await expect.poll(() => state.historyReads).toBe(1)
    expect(state.posts).toBe(1)
  })
}

test('客户端超时暂停发送且无自动重试', async ({ page }) => {
  const state = await mockApi(page, { slow: true })
  await page.goto('/chat')
  await expect(page.getByRole('textbox', { name: '问题' })).toBeEnabled()
  await page.evaluate(async () => { const { api } = await import('/src/api/index.ts'); api.defaults.timeout = 30 })
  await page.getByRole('textbox', { name: '问题' }).fill('What is the return period?')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.locator('.send-error').getByText('请求超时，结果尚未确认。请先查看处理状态或会话记录，避免重复提交。')).toBeVisible()
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
  expect(state.posts).toBe(1)
})

test('无证据回答不显示虚构来源', async ({ page }) => {
  const state = await mockApi(page, { noEvidence: true })
  await ask(page)
  await expect(page.locator('.chat-message.assistant')).toContainText('没有足够证据')
  await expect(page.locator('.citations')).toHaveCount(0)
  expect(state.posts).toBe(1)
})

test('上传中重复文件事件只POST一次，索引轮询仅GET', async ({ page }) => {
  const state = await mockApi(page, { slow: true })
  await page.goto('/documents')
  await expect(page.getByRole('button', { name: '上传文档' })).toBeEnabled()
  const input = page.locator('input[type=file]')
  const file = { name: 'real-rag-policy.txt', mimeType: 'text/plain', buffer: Buffer.from('fictional policy') }
  await input.setInputFiles(file)
  await input.setInputFiles(file)
  await expect(page.locator('.document-table').getByText('已索引', { exact: true })).toBeVisible()
  expect(state.uploads).toBe(1)
})

test('上传异常暂停再次上传，刷新列表不重传', async ({ page }) => {
  const state = await mockApi(page, { uploadError: true })
  await page.goto('/documents')
  await expect(page.getByRole('button', { name: '上传文档' })).toBeEnabled()
  await page.locator('input[type=file]').setInputFiles({ name: 'real-rag-policy.txt', mimeType: 'text/plain', buffer: Buffer.from('fictional') })
  await expect(page.getByText('上传失败或结果尚未确认，请先刷新文档列表，避免重复上传。')).toBeVisible()
  await expect(page.getByRole('button', { name: '上传文档' })).toBeDisabled()
  await page.getByRole('button', { name: '刷新文档列表' }).click()
  expect(state.uploads).toBe(1)
})

for (const [code, text] of [['PARSE_ERROR', '无法提取文本'], ['VECTOR_ERROR', '向量数据库暂不可用']]) {
  test('文档失败状态与提示 ' + code, async ({ page }) => {
    await mockApi(page, { documentError: code })
    await page.goto('/documents')
    await expect(page.locator('.document-table').getByText('处理失败', { exact: true })).toBeVisible()
    await expect(page.getByText(new RegExp(text))).toBeVisible()
  })
}

test('登录到创建上传问答引用及历史的隔离API契约流程', async ({ page }) => {
  const state = await mockApi(page, { authenticated: false })
  await page.goto('/login')
  await page.getByRole('textbox', { name: '用户名', exact: true }).fill('m5_user')
  await page.getByRole('textbox', { name: '密码', exact: true }).fill('fictional-M5-only-password')
  await page.getByRole('button', { name: '登 录', exact: true }).click()
  await expect(page.getByRole('heading', { name: /你好/ })).toBeVisible()
  await page.getByRole('link', { name: '知识库管理' }).click()
  await page.getByRole('button', { name: '创建知识库' }).click()
  await page.getByRole('dialog').locator('input').fill('M5 合成验收')
  await page.getByRole('dialog').getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'M5 合成验收', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '文档', exact: true }).click()
  await expect(page.getByRole('button', { name: '上传文档' })).toBeEnabled()
  await page.locator('input[type=file]').setInputFiles({ name: 'real-rag-policy.txt', mimeType: 'text/plain', buffer: Buffer.from('fictional') })
  await expect(page.locator('.document-table').getByText('已索引', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'AI 智能问答' }).click()
  await page.getByRole('textbox', { name: '问题' }).fill('What is the return period?')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.locator('.el-collapse-item__header')).toContainText('[2] real-rag-policy.txt')
  await page.locator('.el-collapse-item__header').click()
  await expect(page.getByText('文档 ID：doc1')).toBeVisible()
  await expect(page.locator('.el-collapse-item__header')).not.toContainText('页')
  await page.getByRole('link', { name: '会话历史' }).click()
  await page.getByRole('button', { name: '继续问答' }).click()
  await expect(page.locator('.chat-message.assistant')).toContainText('17 days')
  expect(state.uploads).toBe(1); expect(state.posts).toBe(1); expect(state.authChecks).toBeGreaterThan(0)
})
