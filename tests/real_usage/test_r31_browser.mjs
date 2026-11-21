import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFileSync, existsSync } from 'node:fs'
import { resolve, join, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { navigate, resumeGate, checkLedger, resumeQuestion } from '../../scripts/r3_resume_browser.mjs'
const root = fileURLToPath(new URL('../../', import.meta.url))
const require = createRequire(join(root, 'frontend/package.json'))
const { chromium } = require('playwright'), { expect } = require('@playwright/test')
const base = 'https://r31-offline.invalid', dist = join(root, 'frontend/dist')
const plan = { resume: { previous_call_id: 'old-offline-call', knowledge_base_id: 'offline-kb',
  document_id: 'offline-doc', chunk_id: 'offline-chunk', source_name: 'personal-use-policy.pdf',
  question: 'What is the return period in the personal RAG setup policy? Cite the source.' } }
const originalCall = () => ({ id: 'old-offline-call', kind: 'embedding', status: 'VERIFIED', input_tokens: 28,
  output_tokens: 0, charge_cny: .0000585 })
const initialLedger = () => ({ history: 6, stopped: false, active: 0, calls: [originalCall()] })
let browser
const safeEnv = Object.fromEntries(['PATH', 'Path', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE',
  'APPDATA', 'LOCALAPPDATA', 'PROGRAMDATA'].filter(key => process.env[key] !== undefined).map(key => [key, process.env[key]]))
before(async () => {
  browser = await chromium.launch({ executablePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    headless: true, env: safeEnv })
})
after(async () => { await browser?.close() })

async function fixture(options = {}) {
  const context = await browser.newContext({ baseURL: base, serviceWorkers: 'block', reducedMotion: 'reduce', viewport: { width: 1440, height: 1000 } })
  const page = await context.newPage(), gate = resumeGate(base, 'offline-kb', plan.resume.question)
  page.setDefaultTimeout(1500)
  const state = { sessions: [], messages: [], ledger: initialLedger(), unknown: [], wirePosts: 0, loadingCompleted: false, failLists: false }
  const kb = { id: 'offline-kb', name: 'Offline existing knowledge', description: 'Synthetic fixture only', created_at: '2026-11-19T00:00:00Z' }
  const doc = { id: 'offline-doc', knowledge_base_id: kb.id, name: 'personal-use-policy.pdf', file_type: 'pdf',
    status: options.invalidDocument ? 'failed' : 'indexed', progress: 100, chunk_count: 1, size: 928, created_at: kb.created_at }
  const source = { source_id: 1, chunk_id: 'offline-chunk', document_id: doc.id, knowledge_base_id: kb.id,
    source_name: doc.name, source_location: { format: 'pdf', page: 1 }, text: 'The return period is 17 days.', score: .99 }
  // Every HTTP request is fulfilled/aborted. There is no route.continue or local server.
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    let body; try { body = request.postDataJSON() } catch {}
    if (!gate.allow(request.method(), request.url(), body)) return route.abort()
    if (path.startsWith('/api/')) {
      const ok = (data, status = 200) => route.fulfill({ status, json: { code: 'OK', message: 'OK', data } })
      const fail = code => route.fulfill({ status: 503, json: { code, message: 'Synthetic safe error', data: null } })
      if (path === '/api/health') return ok({ model_backend: 'qwen', vector_backend: 'milvus', rag_runtime_mode: 'real', paid_models_enabled: true })
      if (path === '/api/knowledge-bases') {
        if (state.failLists) return fail('DATABASE_ERROR')
        if (options.delayed) await new Promise(resolve => setTimeout(resolve, 180))
        state.loadingCompleted = true
        return ok([kb])
      }
      if (path === '/api/knowledge-bases/offline-kb/documents') return ok([doc])
      if (path === '/api/sessions') {
        if (request.method() === 'GET') return ok(state.sessions)
        const row = { id: 'offline-session', knowledge_base_id: kb.id, title: '新会话', created_at: kb.created_at }
        state.sessions.push(row); return ok(row, 201)
      }
      if (path === '/api/sessions/offline-session') return ok(state.sessions[0])
      if (path === '/api/sessions/offline-session/messages') {
        if (request.method() === 'GET') return ok(state.messages)
        state.wirePosts++
        if (options.messageFailure) return fail('MODEL_UNAVAILABLE')
        state.ledger.calls.push({ id: 'offline-query', kind: 'embedding', status: 'VERIFIED', input_tokens: 20, output_tokens: 0, charge_cny: .000038 },
          { id: 'offline-qwen', kind: 'qwen', status: 'VERIFIED', input_tokens: 100, output_tokens: 20, charge_cny: .001344 })
        const answer = { id: 'offline-answer', role: 'assistant', content: 'The return period is **17 days**. [1]', citations: [source], created_at: kb.created_at }
        state.messages = [{ id: 'offline-question', role: 'user', content: body.question, citations: [], created_at: kb.created_at }, answer]
        state.sessions[0].title = body.question
        return ok(answer)
      }
      state.unknown.push(request.method() + ' ' + path); return fail('UNEXPECTED_API')
    }
    const asset = path.startsWith('/assets/') ? resolve(dist, '.' + path) : join(dist, 'index.html')
    if (!asset.startsWith(resolve(dist)) || !existsSync(asset)) { state.unknown.push('ASSET_NOT_FOUND'); return route.abort() }
    const mime = { '.js': 'application/javascript', '.css': 'text/css', '.html': 'text/html', '.svg': 'image/svg+xml' }
    return route.fulfill({ body: readFileSync(asset), contentType: mime[extname(asset)] || 'application/octet-stream' })
  })
  await page.addInitScript(() => { sessionStorage.setItem('token', 'offline-session-only'); sessionStorage.setItem('username', 'offline-user') })
  await page.goto('/')
  await expect(page.locator('nav[aria-label="主导航"]')).toBeVisible()
  return { context, page, state, gate }
}
async function chatReady(page, timeout) {
  await expect(page.locator('.chat-workspace')).toBeVisible({ timeout })
  await expect(page.locator('[aria-label="聊天记录"]')).toHaveAttribute('aria-busy', 'false', { timeout })
  await expect(page.getByRole('textbox', { name: '问题', exact: true })).toBeEnabled({ timeout })
}
const hasCode = code => error => error.safeCode === code

test('actual UI with AI badge resumes once, displays sources and reads saved history using mocks', async () => {
  const { context, page, state, gate } = await fixture()
  try {
    assert.equal(await page.getByRole('link', { name: 'AI 智能问答', exact: true }).count(), 0)
    const screenshots = []
    const result = await resumeQuestion(page, plan, () => state.ledger, gate, async name => {
      if (process.env.R31_TEST_OUTPUT) await page.screenshot({ path: join(process.env.R31_TEST_OUTPUT, name + '-mock.png'), fullPage: true })
      screenshots.push(name)
    }, 2500)
    assert.equal(result.status, 'PASS'); assert.equal(state.wirePosts, 1)
    assert.deepEqual(screenshots, ['01-answer-sources', '02-history'])
    assert.deepEqual(state.unknown, []); assert.equal(gate.state.questions, 1); assert.equal(gate.state.uploads, 0)
    assert.equal(new URL(page.url()).pathname, '/history')
  } finally { await context.close() }
})

test('changed AI navigation text and badge do not affect route selection', async () => {
  const { context, page } = await fixture()
  try {
    await page.locator('nav a[href="/chat"]').evaluate(link => { link.querySelector('span').textContent = '探索文档'; link.querySelector('.nav-ai').textContent = 'NEW' })
    await navigate(page, '/chat', time => chatReady(page, time), 2000)
    assert.equal(new URL(page.url()).pathname, '/chat')
  } finally { await context.close() }
})

test('missing navigation element stops without submitting a question', async () => {
  const { context, page, state } = await fixture()
  try {
    await page.locator('nav a[href="/chat"]').evaluate(link => link.remove())
    await assert.rejects(navigate(page, '/chat', time => chatReady(page, time), 250), hasCode('NAVIGATION_ELEMENT_NOT_FOUND'))
    assert.equal(state.wirePosts, 0)
  } finally { await context.close() }
})

test('duplicate navigation elements are rejected', async () => {
  const { context, page } = await fixture()
  try {
    await page.locator('nav a[href="/chat"]').evaluate(link => link.after(link.cloneNode(true)))
    await assert.rejects(navigate(page, '/chat', time => chatReady(page, time), 250), hasCode('NAVIGATION_ELEMENT_AMBIGUOUS'))
  } finally { await context.close() }
})

test('navigation action timeout has a safe distinct code', async () => {
  const { context, page } = await fixture()
  try {
    await page.locator('nav a[href="/chat"]').evaluate(link => { link.style.pointerEvents = 'none' })
    await assert.rejects(navigate(page, '/chat', time => chatReady(page, time), 250), hasCode('NAVIGATION_TIMEOUT'))
  } finally { await context.close() }
})

test('wrong route is rejected even when chat markup is present', async () => {
  const { context, page } = await fixture()
  try {
    await page.locator('nav a[href="/chat"]').evaluate(link => { link.addEventListener('click', event => { event.preventDefault(); event.stopImmediatePropagation() }, true) })
    await assert.rejects(navigate(page, '/chat', async () => {}, 250), hasCode('NAVIGATION_ROUTE_INCORRECT'))
  } finally { await context.close() }
})

test('correct route without a ready page is rejected', async () => {
  const { context, page } = await fixture()
  try {
    await assert.rejects(navigate(page, '/chat', time => expect(page.locator('#missing-ready-marker')).toBeVisible({ timeout: time }), 250), hasCode('PAGE_LOAD_FAILED'))
    assert.equal(new URL(page.url()).pathname, '/chat')
  } finally { await context.close() }
})

test('page readiness waits for actual UI initialization', async () => {
  const { context, page, state } = await fixture({ delayed: true })
  try {
    state.loadingCompleted = false
    await navigate(page, '/chat', time => chatReady(page, time), 2000)
    assert.equal(state.loadingCompleted, true)
    assert.equal(await page.locator('[aria-label="聊天记录"]').getAttribute('aria-busy'), 'false')
  } finally { await context.close() }
})

test('API failure during navigation has a safe distinct code', async () => {
  const { context, page, state } = await fixture()
  try {
    state.failLists = true
    await assert.rejects(navigate(page, '/chat', time => chatReady(page, time), 500), hasCode('API_REQUEST_FAILED'))
    assert.equal(state.wirePosts, 0)
  } finally { await context.close() }
})

test('message failure stops once, never re-arms or auto-submits again', async () => {
  const { context, page, state, gate } = await fixture({ messageFailure: true })
  try {
    await assert.rejects(resumeQuestion(page, plan, () => state.ledger, gate, undefined, 2000), hasCode('QUESTION_POST_FAILED'))
    assert.equal(state.wirePosts, 1); assert.equal(gate.state.questions, 1)
    assert.throws(() => gate.arm(), hasCode('PAID_POST_GATE_VIOLATION'))
    assert.equal(gate.allow('POST', base + '/api/sessions/offline-session/messages', { question: plan.resume.question }), false)
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
    assert.equal(state.wirePosts, 1)
  } finally { await context.close() }
})

test('invalid existing document blocks the resume before any message', async () => {
  const { context, page, state, gate } = await fixture({ invalidDocument: true })
  try {
    await assert.rejects(resumeQuestion(page, plan, () => state.ledger, gate), hasCode('DOCUMENT_RESUME_STATE_INVALID'))
    assert.equal(state.wirePosts, 0); assert.equal(gate.state.stopped, true)
  } finally { await context.close() }
})

test('previous request count and usage must survive a new approval ID', () => {
  checkLedger(initialLedger(), 1, 0, 'old-offline-call')
  const empty = initialLedger(); empty.calls = []
  assert.throws(() => checkLedger(empty, 1, 0, 'old-offline-call'), hasCode('LEDGER_COUNT_OR_STATUS_MISMATCH'))
  const changed = initialLedger(); changed.calls[0].input_tokens = 0
  assert.throws(() => checkLedger(changed, 1, 0, 'old-offline-call'), hasCode('PRIOR_CALL_CHANGED'))
  const duplicate = initialLedger(); duplicate.calls.push(originalCall())
  assert.throws(() => checkLedger(duplicate, 1, 0, 'old-offline-call'), hasCode('LEDGER_COUNT_OR_STATUS_MISMATCH'))
})

test('unknown requests, active operations, stopped state and changed history block paid work', () => {
  for (const patch of [{ stopped: true }, { active: 1 }, { history: 7 }]) {
    assert.throws(() => checkLedger({ ...initialLedger(), ...patch }, 1, 0, 'old-offline-call'), hasCode('LEDGER_STOPPED_OR_HISTORY_CHANGED'))
  }
  const uncertain = initialLedger(); uncertain.calls[0].status = 'UNKNOWN'
  assert.throws(() => checkLedger(uncertain, 1, 0, 'old-offline-call'), hasCode('LEDGER_COUNT_OR_STATUS_MISMATCH'))
})

test('resume gate allows one session and one question, blocks repeat and upload/search/foreign writes', () => {
  const gate = resumeGate(base, 'offline-kb', plan.resume.question)
  gate.arm()
  assert.equal(gate.allow('POST', base + '/api/sessions', { knowledge_base_id: 'offline-kb' }), true)
  assert.equal(gate.allow('POST', base + '/api/sessions/offline-session/messages', { question: plan.resume.question }), true)
  assert.equal(gate.allow('POST', base + '/api/sessions/offline-session/messages', { question: plan.resume.question }), false)
  for (const [method, path] of [['POST', '/api/knowledge-bases/offline-kb/documents'], ['POST', '/api/knowledge-bases/offline-kb/search'],
    ['POST', '/api/auth/register'], ['DELETE', '/api/knowledge-bases/offline-kb'], ['PUT', '/api/knowledge-bases/offline-kb']]) {
    assert.equal(resumeGate(base, 'offline-kb', plan.resume.question).allow(method, base + path, {}), false)
  }
  assert.equal(resumeGate(base, 'offline-kb', plan.resume.question).allow('GET', 'https://external.invalid/api/health'), false)
  assert.equal(gate.state.questions, 1)
})

test('entry without explicit resume authorization exits before reserving output or Docker/API work', () => {
  const result = spawnSync(process.execPath, [join(root, 'scripts/r3_resume_browser.mjs')], { env: safeEnv, encoding: 'utf8' })
  assert.equal(result.status, 2)
  assert.equal(JSON.parse(result.stdout).error_code, 'R31_EXPLICIT_RESUME_AUTHORIZATION_REQUIRED')
  assert.equal(result.stderr, '')
})
