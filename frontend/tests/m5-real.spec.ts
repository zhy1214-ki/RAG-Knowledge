// Future authorized execution only. Never reads a model credential.
import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createHash, randomUUID } from 'node:crypto'
const root = new URL('../../', import.meta.url)
const plan = JSON.parse(readFileSync(process.env.M5_PLAN_PATH || new URL('data/m5-acceptance/plan.json', root), 'utf8'))
if (process.env.M5_APPROVAL_ID !== plan.approval_id) throw new Error('EXPLICIT_M5_APPROVAL_REQUIRED')
for (const [path, digest] of Object.entries(plan.frontend_hashes)) {
  const actual = createHash('sha256').update(readFileSync(new URL(path, root))).digest('hex')
  if (actual !== digest) throw new Error('REVIEWED_FRONTEND_CHANGED')
}

test('authorized M5 browser real RAG exactly one upload and one question', async ({ page }) => {
  const errors: string[] = []
  let uploads = 0, questions = 0
  page.on('pageerror', e => errors.push(e.name))
  page.on('request', req => {
    if (req.method() === 'POST' && /\/api\/knowledge-bases\/[^/]+\/documents$/.test(req.url())) uploads++
    if (req.method() === 'POST' && /\/api\/sessions\/[^/]+\/messages$/.test(req.url())) questions++
  })
  try {
    const username = 'm5_' + plan.run_id
    const password = randomUUID()
    // Registration uses no model; login itself is exercised in the browser.
    const registered = await page.request.post('/api/auth/register', { data: { username, password } })
    expect(registered.status()).toBe(201)
    await page.goto('/login')
    await page.getByRole('textbox', { name: '用户名', exact: true }).fill(username)
    await page.getByRole('textbox', { name: '密码', exact: true }).fill(password)
    await page.getByRole('button', { name: '登 录', exact: true }).click()
    await expect(page.getByRole('heading', { name: /你好/ })).toBeVisible()
    await page.getByRole('link', { name: '知识库管理' }).click()
    await page.getByRole('button', { name: '创建知识库' }).click()
    await page.getByRole('dialog').locator('input').fill('M5_' + plan.run_id)
    await page.getByRole('dialog').getByRole('button', { name: '保存', exact: true }).click()
    await expect(page.getByRole('cell', { name: 'M5_' + plan.run_id, exact: true })).toBeVisible()
    await page.getByRole('button', { name: '文档', exact: true }).click()
    await expect(page.getByRole('button', { name: '上传文档' })).toBeEnabled()
    await page.locator('input[type=file]').setInputFiles(fileURLToPath(new URL('samples/real-rag-policy.txt', root)))
    await expect(page.getByText('已索引', { exact: true })).toBeVisible({ timeout: 75000 })
    await page.getByRole('link', { name: 'AI 智能问答' }).click()
    await page.getByRole('textbox', { name: '问题' }).fill(plan.question)
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect(page.locator('.chat-message.assistant')).toContainText(/17|十七/, { timeout: 130000 })
    await expect(page.locator('.el-collapse-item__header')).toContainText('[1] real-rag-policy.txt')
    await page.locator('.el-collapse-item__header').click()
    await expect(page.getByText(/文档 ID：/)).toBeVisible()
    await expect(page.locator('.el-collapse-item__header')).not.toContainText('页')
    await page.getByRole('link', { name: '会话历史' }).click()
    await page.getByRole('button', { name: '继续问答' }).click()
    await expect(page.locator('.chat-message.assistant')).toContainText(/17|十七/)
    const token = await page.evaluate(() => sessionStorage.getItem('token'))
    const headers = { Authorization: 'Bearer ' + token }
    const status = await page.request.get('/api/m5-control/status', { headers })
    const state = (await status.json()).data
    expect(state.calls.map((c: any) => c.path)).toEqual(['/embeddings','/embeddings','/chat/completions'])
    expect(state.upload_posts).toBe(1); expect(state.message_posts).toBe(1)
    expect(uploads).toBe(1); expect(questions).toBe(1); expect(errors).toEqual([])
    const finished = await page.request.post('/api/m5-control/finish', { headers })
    expect(finished.ok()).toBeTruthy()
    // Cleanup uses existing DELETE endpoints only, never new model requests.
    const kbs = (await (await page.request.get('/api/knowledge-bases', { headers })).json()).data
    expect(kbs).toHaveLength(1)
    expect((await page.request.delete('/api/knowledge-bases/' + kbs[0].id, { headers })).ok()).toBeTruthy()
  } catch (error) {
    const token = await page.evaluate(() => sessionStorage.getItem('token')).catch(() => null)
    if (token) await page.request.post('/api/m5-control/stop', { headers: { Authorization: 'Bearer ' + token } }).catch(() => {})
    throw error
  }
})
