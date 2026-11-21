import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { createHash, randomBytes } from 'node:crypto'

const hash = text => createHash('sha256').update(text).digest('hex')

// This directory is outside Playwright's cleanup target and is never removed here.
export function reserveOutput(root, approvalId, runId) {
  const nonce = randomBytes(24).toString('hex')
  try {
    mkdirSync(root) // recursive:false: exactly one contender may create it.
  } catch (error) {
    if (error.code === 'EEXIST') throw new Error('M5_BROWSER_OUTPUT_ALREADY_EXISTS')
    throw new Error('M5_BROWSER_OUTPUT_RESERVATION_FAILED')
  }
  try {
    writeFileSync(join(root, 'reservation.json'),
      JSON.stringify({ approval_id: approvalId, run_id: runId, nonce_sha256: hash(nonce) }),
      { flag: 'wx', encoding: 'utf8' })
  } catch {
    // Keep the reservation on failure; never remove or silently reuse a run.
    throw new Error('M5_BROWSER_OUTPUT_RESERVATION_FAILED')
  }
  return { nonce, outputDir: join(root, 'playwright') }
}

export function verifyOutput(root, approvalId, runId, nonce) {
  if (!nonce) throw new Error('M5_BROWSER_LAUNCHER_REQUIRED')
  let reservation
  try { reservation = JSON.parse(readFileSync(join(root, 'reservation.json'), 'utf8')) }
  catch { throw new Error('M5_BROWSER_RESERVATION_INVALID') }
  if (reservation.approval_id !== approvalId || reservation.run_id !== runId ||
      reservation.nonce_sha256 !== hash(nonce)) {
    throw new Error('M5_BROWSER_RESERVATION_INVALID')
  }
  return join(root, 'playwright')
}

// Pass only browser/runtime variables; never read or forward model credentials.
export function browserEnvironment(planPath, approvalId, nonce) {
  const env = {}
  for (const name of ['PATH','Path','SystemRoot','SYSTEMROOT','WINDIR','TEMP','TMP',
    'USERPROFILE','LOCALAPPDATA','APPDATA','COMSPEC','PATHEXT','EDGE_PATH',
    'CI','NO_COLOR','FORCE_COLOR','PROCESSOR_ARCHITECTURE']) {
    if (process.env[name] !== undefined) env[name] = process.env[name]
  }
  return { ...env, M5_PLAN_PATH: planPath, M5_APPROVAL_ID: approvalId, M5_OUTPUT_NONCE: nonce }
}
