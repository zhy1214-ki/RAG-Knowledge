import { test, expect } from '@playwright/test'
import { writeFileSync } from 'node:fs'
test('parent and worker share the owned output without any network', async ({ page }, info) => {
  const requests: string[] = []
  await page.route('**/*', route => { requests.push(route.request().method()); return route.abort() })
  await page.setContent('<main><p data-testid="answer">Fictional answer: 17 days [1]</p></main>')
  await expect(page.getByTestId('answer')).toHaveText('Fictional answer: 17 days [1]')
  expect(requests).toEqual([])
  writeFileSync(info.outputPath('fictional-worker-output.txt'), 'offline-only')
})
