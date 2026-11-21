import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { randomBytes, createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { reserveOutput, verifyOutput, browserEnvironment } from '../scripts/m5-output-gate.mjs'

const project = fileURLToPath(new URL('../../', import.meta.url))
const gateUrl = new URL('../scripts/m5-output-gate.mjs', import.meta.url).href
function sandbox() {
  const dir = join(project, 'data/m5-output-gate-fix/tests', randomBytes(8).toString('hex'))
  mkdirSync(dir, { recursive: true })
  return dir
}
const hash = bytes => createHash('sha256').update(bytes).digest('hex')

test('first run atomically creates its reservation and allows owned output', () => {
  const root = join(sandbox(), 'run')
  const owned = reserveOutput(root, 'fictional-approval', 'fictional-run')
  assert.ok(existsSync(join(root, 'reservation.json')))
  assert.equal(owned.outputDir, join(root, 'playwright'))
  assert.equal(verifyOutput(root, 'fictional-approval', 'fictional-run', owned.nonce), owned.outputDir)
})

test('existing historical output is blocked and evidence is preserved', () => {
  const root = join(sandbox(), 'run')
  mkdirSync(root)
  const evidence = join(root, 'historical.txt')
  writeFileSync(evidence, 'do-not-overwrite')
  const before = hash(readFileSync(evidence))
  assert.throws(() => reserveOutput(root, 'fictional-approval', 'fictional-run'),
    { message: 'M5_BROWSER_OUTPUT_ALREADY_EXISTS' })
  assert.equal(hash(readFileSync(evidence)), before)
  assert.equal(existsSync(join(root, 'reservation.json')), false)
})

test('two independent processes cannot claim the same root', async () => {
  const root = join(sandbox(), 'run')
  const code = 'import {reserveOutput} from ' + JSON.stringify(gateUrl) +
    ';try{reserveOutput(' + JSON.stringify(root) + ',"fictional-approval","fictional-run");' +
    'process.stdout.write("RESERVED")}catch(e){process.stdout.write(e.message);process.exitCode=2}'
  function contender() {
    return new Promise((resolve, reject) => {
      const child = spawn(process.execPath, ['--input-type=module', '-e', code],
        { env: browserEnvironment('', 'fictional-approval', ''), stdio: ['ignore', 'pipe', 'pipe'] })
      let output = ''
      child.stdout.on('data', data => { output += data.toString() })
      child.stderr.on('data', data => { output += data.toString() })
      child.once('error', reject)
      child.once('close', status => resolve({ status, output }))
    })
  }
  const results = await Promise.all([contender(), contender()])
  assert.equal(results.filter(r => r.status === 0 && r.output === 'RESERVED').length, 1)
  assert.equal(results.filter(r => r.status === 2 && r.output === 'M5_BROWSER_OUTPUT_ALREADY_EXISTS').length, 1)
})

test('unowned direct config access is blocked without claiming a directory conflict', () => {
  const root = join(sandbox(), 'run')
  const owned = reserveOutput(root, 'fictional-approval', 'fictional-run')
  assert.throws(() => verifyOutput(root, 'fictional-approval', 'fictional-run', ''),
    { message: 'M5_BROWSER_LAUNCHER_REQUIRED' })
  assert.throws(() => verifyOutput(root, 'fictional-approval', 'fictional-run', 'wrong'),
    { message: 'M5_BROWSER_RESERVATION_INVALID' })
  assert.equal(verifyOutput(root, 'fictional-approval', 'fictional-run', owned.nonce), owned.outputDir)
})

test('actual Playwright parent and worker reloads preserve the run reservation', () => {
  const dir = sandbox(), runId = randomBytes(6).toString('hex'), approvalId = 'offline-output-' + runId
  const plan = join(dir, 'fictional-plan.json')
  writeFileSync(plan, JSON.stringify({ run_id: runId, approval_id: approvalId, status: 'PENDING_APPROVAL' }))
  const root = join(project, 'data/m5-acceptance/browser-' + runId)
  const owned = reserveOutput(root, approvalId, runId)
  const before = readFileSync(join(root, 'reservation.json'))
  for (let i = 0; i < 3; i++) assert.equal(verifyOutput(root, approvalId, runId, owned.nonce), owned.outputDir)
  const cli = join(project, 'frontend/node_modules/playwright/cli.js')
  const config = join(project, 'frontend/tests/playwright.output-gate.offline.config.ts')
  const result = spawnSync(process.execPath, [cli, 'test', '--config', config], {
    cwd: project, env: browserEnvironment(plan, approvalId, owned.nonce), encoding: 'utf8', timeout: 60000,
  })
  assert.equal(result.status, 0, result.stdout + result.stderr)
  assert.match(result.stdout, /1 passed/)
  assert.deepEqual(readFileSync(join(root, 'reservation.json')), before)
  assert.ok(existsSync(join(root, 'playwright', '.last-run.json')))
})

test('original request guard, RAG scenario and historical counters are unchanged', () => {
  const baseline = JSON.parse(readFileSync(join(project, 'data/m5-output-gate-fix/baseline.json'), 'utf8'))
  for (const [file, expected] of Object.entries(baseline.preserved_files)) {
    if (file === 'scripts/m5_browser_backend.py') {
      // The approved preflight hook changed; the original model budget must not.
      const current = readFileSync(join(project, file), 'utf8').replace(/\r\n/g, '\n')
      const budget = current.slice(current.indexOf('class ModelBudget:'), current.indexOf('\ndef serve('))
      const storageBaseline = JSON.parse(readFileSync(join(project, 'data/m5-storage-preflight-fix/baseline.json'), 'utf8'))
      assert.equal(hash(Buffer.from(budget)), storageBaseline.model_budget_source_sha256_lf)
    } else assert.equal(hash(readFileSync(join(project, file))), expected, file)
  }
  const scenario = readFileSync(join(project, 'frontend/tests/m5-real.spec.ts'), 'utf8')
  const body = scenario.slice(scenario.indexOf("test('authorized M5 browser")).replace(/\r\n/g, '\n')
  assert.equal(hash(Buffer.from(body)), baseline.real_browser_test_body_sha256)
  const plan = JSON.parse(readFileSync(join(project, 'data/m5-acceptance/plan.json'), 'utf8'))
  assert.equal(plan.max_embedding_requests, 2); assert.equal(plan.max_qwen_requests, 1)
  assert.equal(plan.retries, 0); assert.equal(plan.budget_cny, '0.01')
})
