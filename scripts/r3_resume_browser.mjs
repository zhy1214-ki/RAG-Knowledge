// Resume-only acceptance tool. Importing this module performs no I/O or requests.
import { createRequire } from 'node:module'
import { readFileSync, writeFileSync, mkdirSync, realpathSync, lstatSync } from 'node:fs'
import { resolve, join, relative, isAbsolute, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(join(root, 'frontend/package.json'))
const { expect } = require('@playwright/test')
export function check(ok, code) { if (!ok) throw Object.assign(new Error(code), { safeCode: code }) }

export async function navigate(page, path, ready, timeout = 12000) {
  check(['/chat', '/history'].includes(path), 'NAVIGATION_ROUTE_INCORRECT')
  let apiFailed = false, pageFailed = false
  const onResponse = response => { if (new URL(response.url()).pathname.startsWith('/api/') && !response.ok()) apiFailed = true }
  const onError = () => { pageFailed = true }
  page.on('response', onResponse); page.on('pageerror', onError)
  try {
    const link = page.locator('nav[aria-label="主导航"] a[href="' + path + '"]')
    const count = await link.count()
    check(count > 0, 'NAVIGATION_ELEMENT_NOT_FOUND')
    check(count === 1, 'NAVIGATION_ELEMENT_AMBIGUOUS')
    try { await link.click({ timeout }) } catch { check(false, 'NAVIGATION_TIMEOUT') }
    try { await page.waitForURL(url => url.pathname === path, { timeout }) }
    catch { check(false, apiFailed ? 'API_REQUEST_FAILED' : pageFailed ? 'PAGE_LOAD_FAILED' : 'NAVIGATION_ROUTE_INCORRECT') }
    try { await ready(timeout) }
    catch { check(false, apiFailed ? 'API_REQUEST_FAILED' : 'PAGE_LOAD_FAILED') }
    check(!apiFailed, 'API_REQUEST_FAILED'); check(!pageFailed, 'PAGE_LOAD_FAILED')
  } finally { page.off('response', onResponse); page.off('pageerror', onError) }
}

export function resumeGate(base, kb, question) {
  const state = { uploads: 0, questions: 0, sessions: 0, logins: 0, violations: [], stopped: false }
  let armed = false, used = false
  return {
    state,
    arm() { check(!used && !state.stopped, 'PAID_POST_GATE_VIOLATION'); used = true; armed = true },
    stop() { state.stopped = true; armed = false },
    allow(method, url, body) {
      const target = new URL(url)
      let allowed = target.origin === base
      if (allowed && target.pathname.startsWith('/api/')) {
        if (method === 'GET') return true
        if (method === 'POST' && target.pathname === '/api/auth/login') allowed = !state.stopped && state.logins++ === 0
        else if (method === 'POST' && target.pathname === '/api/sessions') {
          allowed = armed && !state.stopped && state.sessions++ === 0 && body?.knowledge_base_id === kb
        } else if (method === 'POST' && /^\/api\/sessions\/[^/]+\/messages$/.test(target.pathname)) {
          allowed = armed && !state.stopped && state.sessions === 1 && state.questions === 0 && body?.question === question
          if (allowed) { state.questions++; armed = false }
        } else allowed = false
      } else if (method !== 'GET') allowed = false
      if (!allowed) { state.violations.push('PAID_POST_GATE_VIOLATION'); state.stopped = true; armed = false }
      return allowed
    },
  }
}

export function checkLedger(value, embeddings, qwen, previousCall) {
  check(value.history === 6 && !value.stopped && value.active === 0, 'LEDGER_STOPPED_OR_HISTORY_CHANGED')
  check(value.calls.length === embeddings + qwen && value.calls.every(c => c.status === 'VERIFIED') &&
    value.calls.filter(c => c.kind === 'embedding').length === embeddings &&
    value.calls.filter(c => c.kind === 'qwen').length === qwen, 'LEDGER_COUNT_OR_STATUS_MISMATCH')
  const old = value.calls.find(c => c.id === previousCall)
  check(old?.kind === 'embedding' && old.input_tokens === 28 && old.output_tokens === 0 &&
    Number(old.charge_cny) === .0000585, 'PRIOR_CALL_CHANGED')
  check(value.calls.reduce((sum, c) => sum + Number(c.charge_cny), 0) <= .01, 'BUDGET_EXCEEDED')
}

async function get(page, path) {
  let result
  try {
    result = await page.evaluate(async path => {
      const response = await fetch('/api' + path, { headers: { Authorization: 'Bearer ' + sessionStorage.getItem('token') }, cache: 'no-store' })
      return { status: response.status, body: await response.json() }
    }, path)
  } catch { check(false, 'READ_ONLY_API_FAILED') }
  check(result.status === 200 && result.body.code === 'OK', 'READ_ONLY_API_FAILED')
  return result.body.data
}

// Called only after authenticated owner, current storage and ledger preflight pass.
export async function resumeQuestion(page, plan, ledger, gate, capture = async () => {}, timeout = 12000) {
  const target = plan.resume
  try {
    checkLedger(ledger(), 1, 0, target.previous_call_id)
    const kbs = await get(page, '/knowledge-bases')
    check(kbs.length === 1 && kbs[0].id === target.knowledge_base_id, 'KNOWLEDGE_BASE_SCOPE_MISMATCH')
    const docs = await get(page, '/knowledge-bases/' + target.knowledge_base_id + '/documents')
    check(docs.length === 1 && docs[0].id === target.document_id && docs[0].status === 'indexed' &&
      docs[0].chunk_count === 1 && docs[0].name === target.source_name, 'DOCUMENT_RESUME_STATE_INVALID')
    check((await get(page, '/sessions')).length === 0, 'UNEXPECTED_PRIOR_SESSION')
    await navigate(page, '/chat', async time => {
      await expect(page.locator('.chat-workspace')).toBeVisible({ timeout: time })
      await expect(page.locator('[aria-label="聊天记录"]')).toHaveAttribute('aria-busy', 'false', { timeout: time })
      await expect(page.getByRole('textbox', { name: '问题', exact: true })).toBeEnabled({ timeout: time })
      await expect(page.locator('.state-error')).toHaveCount(0, { timeout: time })
      await expect(page.locator('.chat-source-picker .el-select__selected-item.el-select__placeholder')).toHaveText(kbs[0].name, { timeout: time })
    }, timeout)
    checkLedger(ledger(), 1, 0, target.previous_call_id)
    check(!gate.state.stopped && gate.state.violations.length === 0, 'PAID_POST_GATE_VIOLATION')
    await page.getByRole('textbox', { name: '问题', exact: true }).fill(target.question)
    // Register once, then click once; failure never re-arms or re-submits.
    const answered = page.waitForResponse(r => r.request().method() === 'POST' &&
      /^\/api\/sessions\/[^/]+\/messages$/.test(new URL(r.url()).pathname), { timeout: 125000 })
    answered.catch(() => {})
    gate.arm()
    await page.getByRole('button', { name: '发送', exact: true }).click({ timeout })
    const response = await answered
    check(response.status() === 200, 'QUESTION_POST_FAILED')
    const body = await response.json()
    check(body.code === 'OK', 'QUESTION_POST_FAILED')
    const answer = body.data, session = new URL(response.url()).pathname.split('/')[3]
    checkLedger(ledger(), 2, 1, target.previous_call_id)
    check(answer.role === 'assistant' && /17|十七/.test(answer.content) && /days|天|日/i.test(answer.content), 'ANSWER_FACT_MISMATCH')
    check(answer.citations?.length === 1, 'CITATION_COUNT_MISMATCH')
    const source = answer.citations[0]
    check(source.document_id === target.document_id && source.knowledge_base_id === target.knowledge_base_id &&
      source.chunk_id === target.chunk_id && source.source_name === target.source_name, 'CITATION_OWNERSHIP_MISMATCH')
    check(source.source_location?.format === 'pdf' && source.source_location?.page === 1, 'PDF_PAGE_MISMATCH')
    check(source.text.replace(/\s+/g, ' ').includes('return period is 17 days'), 'CITATION_TEXT_MISMATCH')
    await expect(page.locator('.chat-message.assistant')).toContainText(/17|十七/, { timeout })
    await expect(page.locator('.source-title')).toContainText(/第\s*1\s*页/, { timeout })
    await page.locator('.el-collapse-item__header').first().click({ timeout })
    await expect(page.locator('.source-id').first()).toContainText(target.document_id, { timeout })
    await expect(page.locator('.source-text').first()).toContainText('17 days', { timeout })
    await capture('01-answer-sources')
    await navigate(page, '/history', async time => {
      await expect(page.locator('.history-messages .chat-message.assistant')).toContainText(/17|十七/, { timeout: time })
      await expect(page.locator('.state-error')).toHaveCount(0, { timeout: time })
    }, timeout)
    const history = await get(page, '/sessions/' + session + '/messages')
    check(history.length === 2 && history[0].role === 'user' && history[0].content === target.question &&
      history[1].id === answer.id && history[1].citations[0]?.chunk_id === target.chunk_id, 'HISTORY_PERSISTENCE_MISMATCH')
    check((await get(page, '/sessions/' + session)).knowledge_base_id === target.knowledge_base_id, 'HISTORY_SCOPE_MISMATCH')
    await capture('02-history')
    checkLedger(ledger(), 2, 1, target.previous_call_id)
    check(gate.state.questions === 1 && gate.state.sessions === 1 && !gate.state.stopped &&
      gate.state.violations.length === 0, 'EXTRA_PAID_POST_DETECTED')
    return { status: 'PASS', session_id: session, answer_id: answer.id, document_id: target.document_id,
      upload_posts: 0, question_posts: 1, new_embedding: 1, new_qwen: 1, history_messages: 2, pdf_page: 1 }
  } catch (error) {
    gate.stop()
    throw Object.assign(new Error(error.safeCode || 'BROWSER_STAGE_FAILED'), { safeCode: error.safeCode || 'BROWSER_STAGE_FAILED' })
  }
}

const digest = value => createHash('sha256').update(value).digest('hex')
function withinProject(name) {
  const path = resolve(root, name), rel = relative(root, path)
  check(rel && !rel.startsWith('..') && !isAbsolute(rel), 'R1_ARTIFACT_PATH_INVALID')
  for (let parent = path; parent !== root; parent = dirname(parent)) check(!lstatSync(parent).isSymbolicLink(), 'R1_ARTIFACT_PATH_INVALID')
  check(realpathSync(path) === path, 'R1_ARTIFACT_PATH_INVALID')
  return path
}
async function main() {
  let browser, context, gate, audit
  try {
    const args = Object.fromEntries(process.argv.slice(2).map(value => {
      const offset = value.indexOf('='); return offset < 0 ? [value, true] : [value.slice(0, offset), value.slice(offset + 1)]
    }))
    check(args['--execute-once'] === true && args['--credentials-stdin'] === true &&
      args['--approval-id'] && args['--approval-sha256'] && args['--preflight'], 'R31_EXPLICIT_RESUME_AUTHORIZATION_REQUIRED')
    const approval = withinProject('deploy/real-usage/approval.r31-resume.json'), raw = readFileSync(approval)
    check(digest(raw) === args['--approval-sha256'], 'R1_APPROVAL_HASH_MISMATCH')
    const plan = JSON.parse(raw)
    check(plan.approval_id === args['--approval-id'], 'APPROVAL_ID_MISMATCH')
    for (const [name, hash] of Object.entries(plan.artifacts)) check(digest(readFileSync(withinProject(name))) === hash, 'R1_RUNTIME_ARTIFACT_MISMATCH')
    const proof = JSON.parse(readFileSync(withinProject(args['--preflight']), 'utf8'))
    const age = Date.now() - Date.parse(proof.checked_at)
    check(Number.isFinite(age) && age >= 0 && age <= 300000 && proof.approval_id === plan.approval_id &&
      proof.approval_sha256 === args['--approval-sha256'] && proof.status === 'PASS' &&
      plan.required_live_checks.every(name => proof[name] === true), 'R31_LIVE_PREFLIGHT_REQUIRED')
    for (const name of ['user_id', 'knowledge_base_id', 'document_id', 'chunk_id', 'pdf_sha256'])
      check(proof[name] === plan.resume[name], 'R31_RESOURCE_SCOPE_MISMATCH')
    const credentials = JSON.parse(readFileSync(0, 'utf8'))
    check(credentials.username === plan.resume.username && typeof credentials.password === 'string' &&
      credentials.password.length > 0, 'R31_OWNER_CREDENTIALS_REQUIRED')
    // One fixed reservation per approval; no arbitrary output path and no overwrite.
    const parent = withinProject('data')
    const reservation = join(parent, plan.approval_id)
    try { mkdirSync(reservation) } catch { check(false, 'M5_BROWSER_OUTPUT_ALREADY_EXISTS') }
    audit = reservation
    const safeEnv = Object.fromEntries(['PATH', 'Path', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE',
      'APPDATA', 'LOCALAPPDATA', 'PROGRAMDATA', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG']
      .filter(key => process.env[key] !== undefined).map(key => [key, process.env[key]]))
    const ledger = () => {
      const sql = "SELECT json_build_object('history',(SELECT historical_requests FROM real_usage_guard WHERE id=1),'stopped',(SELECT stopped FROM real_usage_guard WHERE id=1),'active',(SELECT count(*) FROM real_usage_operations WHERE status='RUNNING'),'calls',COALESCE((SELECT json_agg(json_build_object('id',id,'kind',kind,'status',status,'input_tokens',input_tokens,'output_tokens',output_tokens,'charge_cny',charge_cny) ORDER BY created_at) FROM real_usage_calls),'[]'::json));"
      try { return JSON.parse(execFileSync('docker', ['exec', plan.postgres_container_id, 'psql', '-U', 'rag_real', '-d', 'rag_personal_real', '-qAt', '-v', 'ON_ERROR_STOP=1', '-c', sql],
        { env: safeEnv, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })) }
      catch { check(false, 'LEDGER_READ_FAILED') }
    }
    checkLedger(ledger(), 1, 0, plan.resume.previous_call_id)
    const { chromium } = require('playwright')
    browser = await chromium.launch({ executablePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', headless: true, env: safeEnv })
    context = await browser.newContext({ baseURL: plan.base_url, viewport: { width: 1440, height: 1000 }, locale: 'zh-CN', serviceWorkers: 'block', reducedMotion: 'reduce' })
    gate = resumeGate(plan.base_url, plan.resume.knowledge_base_id, plan.resume.question)
    await context.route('**/*', async route => {
      const request = route.request()
      let body; try { body = request.postDataJSON() } catch {}
      return gate.allow(request.method(), request.url(), body) ? route.continue() : route.abort()
    })
    const page = await context.newPage(), errors = []
    page.setDefaultTimeout(12000)
    page.on('pageerror', () => { errors.push('PAGE_LOAD_FAILED'); gate.stop() })
    page.on('response', response => { if (new URL(response.url()).pathname.startsWith('/api/') && !response.ok()) gate.stop() })
    page.on('requestfailed', request => { if (new URL(request.url()).pathname.startsWith('/api/') || /\.(js|css)(?:\?|$)/.test(request.url())) { errors.push('API_OR_RESOURCE_FAILED'); gate.stop() } })
    await page.goto('/login', { timeout: 12000 })
    await page.getByRole('textbox', { name: '用户名', exact: true }).fill(credentials.username)
    await page.getByRole('textbox', { name: '密码', exact: true }).fill(credentials.password)
    credentials.password = ''
    const login = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/api/auth/login'))
    login.catch(() => {})
    await page.getByRole('button', { name: '登 录', exact: true }).click()
    const response = await login
    check(response.status() === 200 && (await response.json()).data.user.id === plan.resume.user_id, 'LOGIN_OWNER_MISMATCH')
    await expect(page.locator('nav[aria-label="主导航"]')).toBeVisible()
    const result = await resumeQuestion(page, plan, ledger, gate, async name => {
      await page.screenshot({ path: join(audit, name + '.png'), fullPage: true, animations: 'disabled' })
    })
    check(errors.length === 0, 'BROWSER_RESOURCE_OR_SCRIPT_ERROR')
    writeFileSync(join(audit, 'result.json'), JSON.stringify({ ...result, ledger: ledger() }, null, 2) + '\n', { flag: 'wx' })
    console.log(JSON.stringify(result))
  } catch (error) {
    gate?.stop()
    const result = { status: 'FAIL', error_code: error.safeCode || 'BROWSER_STAGE_FAILED',
      upload_posts: 0, question_posts: gate?.state.questions || 0, automatic_retry: false }
    if (audit) writeFileSync(join(audit, 'failure.json'), JSON.stringify(result, null, 2) + '\n', { flag: 'wx' })
    console.log(JSON.stringify(result)); process.exitCode = 2
  } finally { if (context) await context.close().catch(() => {}); if (browser) await browser.close().catch(() => {}) }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main()
