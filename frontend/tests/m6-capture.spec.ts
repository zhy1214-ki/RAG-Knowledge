import { test, expect } from '@playwright/test'
import { join } from 'node:path'
import { installMockApi } from './fixtures/m6-api'
for(const [name,path] of [['login','/login'],['home','/'],['knowledge','/knowledge'],['documents','/documents'],['chat','/chat?session=session-product'],['history','/history']]){
  test('capture '+name+' with synthetic API data',async({page})=>{
    const state=await installMockApi(page)
    await page.goto(path!)
    await expect(page.locator('h2').first()).toBeVisible()
    if(name==='home')await expect(page.locator('.stat-value').nth(1)).toHaveText('6')
    if(name==='knowledge')await expect(page.getByText('产品使用指南',{exact:true}).first()).toBeVisible()
    if(name==='documents')await expect(page.getByText('产品快速入门.pdf',{exact:true})).toBeVisible()
    if(name==='chat')await expect(page.locator('.chat-message.assistant')).toContainText('创建知识库')
    if(name==='history')await expect(page.getByText('如何创建和管理知识库？',{exact:true}).first()).toBeVisible()
    if(name==='login')expect((await page.locator('.diagram-document>.el-icon').boundingBox())!.height).toBeGreaterThan(20)
    if(name==='home')expect((await page.locator('.hero-doc>.el-icon').boundingBox())!.height).toBeGreaterThan(24)
    await page.evaluate(()=>document.fonts.ready)
    await page.screenshot({path:join(process.env.M6_RUN_DIR!,name+'.png'),fullPage:true,animations:'disabled'})
    expect(state.questions).toBe(0);expect(state.uploads).toBe(0);expect(state.unhandled).toEqual([])
  })
}
test('capture chat loading and failure feedback',async({page})=>{
  const state=await installMockApi(page,{slowMessage:true,messageFailure:true})
  await page.goto('/chat')
  await expect(page.getByRole('textbox',{name:'问题',exact:true})).toBeEnabled()
  await page.getByRole('textbox',{name:'问题',exact:true}).fill('请说明文档的主要步骤。')
  await page.getByRole('button',{name:'发送',exact:true}).click()
  await expect(page.locator('.answer-loading')).toBeVisible()
  await page.screenshot({path:join(process.env.M6_RUN_DIR!,'chat-loading.png'),animations:'disabled',fullPage:true})
  await expect(page.locator('.send-error')).toBeVisible()
  await expect(page.getByRole('button',{name:'发送',exact:true})).toBeDisabled()
  await page.screenshot({path:join(process.env.M6_RUN_DIR!,'chat-error.png'),animations:'disabled',fullPage:true})
  expect(state.questions).toBe(1);expect(state.unhandled).toEqual([])
})
