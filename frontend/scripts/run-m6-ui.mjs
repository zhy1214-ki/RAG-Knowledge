import { mkdirSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
const stage = process.argv[2]
if (!['before', 'after', 'regression', 'review'].includes(stage)) throw new Error('M6_STAGE_REQUIRED')
const project = fileURLToPath(new URL('../../', import.meta.url))
const parent = join(project, 'data/m6-ui/runs')
mkdirSync(parent, { recursive: true })
const run = join(parent, stage + '-' + randomBytes(6).toString('hex'))
mkdirSync(run)
const env = {}
for (const name of ['PATH','Path','SystemRoot','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','COMSPEC','PATHEXT','EDGE_PATH','CI','NO_COLOR','FORCE_COLOR']) {
  if (process.env[name] !== undefined) env[name] = process.env[name]
}
env.M6_RUN_DIR = run; env.M6_STAGE = stage
console.log('M6_ARTIFACT_DIR=' + run)
const child = spawnSync(process.execPath, [
  join(project, 'frontend/node_modules/playwright/cli.js'), 'test',
  '--config', join(project, 'frontend/playwright.m6.config.ts'), ...process.argv.slice(3),
], { cwd: project, env, stdio: 'inherit' })
process.exitCode = child.error ? 2 : child.status ?? 1
