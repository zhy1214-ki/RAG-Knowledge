import { test, expect, type Page } from '@playwright/test'
import { join } from 'node:path'
import { installMockApi } from './fixtures/m6-api'
const errors = new WeakMap<Page, string[]>()
test.beforeEach(({page}) => { const rows:string[]=[];errors.set(page,rows);page.on('pageerror',error=>rows.push(error.message)) })
test.afterEach(({page}) => { expect(errors.get(page)).toEqual([]) })
const history = () => Array.from({length:24},(_,index)=>({
  id:'m65-'+index,role:index%2?'assistant':'user',content:index===23?'M65 latest synthetic message':'Synthetic history message '+index,
  citations:[],
}))
async function atBottom(page:Page) {
  await expect(page.locator('.chat-scroll')).toContainText('M65 latest synthetic message')
  await expect.poll(()=>page.locator('.chat-scroll').evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight)).toBeLessThan(4)
}
const screenshot=(page:Page,name:string)=>page.screenshot({path:join(process.env.M6_RUN_DIR!,name+'.png'),fullPage:true,animations:'disabled'})

test('M65 switching recent sessions shows latest history without a POST',async({page})=>{
  const state=await installMockApi(page)
  state.messages['session-team']=history()
  for(const width of [1024,1280,1440]){
    await page.setViewportSize({width,height:1000})
    await page.goto('/chat')
    await expect(page.getByRole('textbox',{name:'问题',exact:true})).toBeEnabled()
    await page.locator('.chat-session-list').getByRole('button',{name:'团队文档应该如何归档？'}).click()
    await atBottom(page)
    await expect(page.locator('.chat-session-list .selected')).toContainText('团队文档应该如何归档？')
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
    await screenshot(page,'session-switch-'+width)
  }
  expect(state.questions).toBe(0);expect(state.uploads).toBe(0);expect(state.unhandled).toEqual([]);expect(state.blockedExternal).toEqual([])
})

test('M65 read-only refresh shows latest history and keeps failed sends paused',async({page})=>{
  const state=await installMockApi(page,{messageFailure:true})
  for(const width of [1024,1280,1440]){
    await page.setViewportSize({width,height:1000})
    state.messages['session-product']=[]
    await page.goto('/chat?session=session-product')
    const input=page.getByRole('textbox',{name:'问题',exact:true}),send=page.getByRole('button',{name:'发送',exact:true})
    await expect(input).toBeEnabled()
    await input.fill('Fictional M65 request, no real model')
    await send.click()
    await expect(page.locator('.send-error')).toBeVisible()
    const before=state.questions
    state.messages['session-product']=history()
    await page.getByRole('button',{name:'查看会话记录',exact:true}).click()
    await atBottom(page)
    await expect(send).toBeDisabled();await expect(input).toBeDisabled()
    expect(state.questions).toBe(before)
    await screenshot(page,'read-only-refresh-'+width)
  }
  expect(state.questions).toBe(3);expect(state.uploads).toBe(0);expect(state.unhandled).toEqual([]);expect(state.blockedExternal).toEqual([])
})

test('M65 corrected login fields do not retain empty-field errors',async({page})=>{
  const state=await installMockApi(page,{signedOut:true,loginFailure:true})
  await page.goto('/login')
  await page.getByRole('button',{name:'登 录',exact:true}).click()
  await expect(page.locator('.el-form-item__error')).toHaveCount(2)
  await page.getByRole('textbox',{name:'用户名',exact:true}).fill('m65_review')
  await page.getByRole('textbox',{name:'密码',exact:true}).fill('fictional-M65-password')
  await page.getByRole('button',{name:'登 录',exact:true}).click()
  await expect(page.locator('.login-form .el-alert')).toContainText('用户名或密码错误')
  await expect(page.locator('.el-form-item__error')).toHaveCount(0)
  await screenshot(page,'login-error-settled')
  expect(state.logins).toBe(1);expect(state.questions).toBe(0);expect(state.unhandled).toEqual([])
})

test('M65 corrected knowledge-base name clears validation before saving',async({page})=>{
  const state=await installMockApi(page)
  await page.goto('/knowledge')
  await page.getByRole('button',{name:'创建知识库',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'创建知识库'})
  await dialog.getByRole('button',{name:'保存',exact:true}).click()
  await expect(dialog.getByText('请填写知识库名称')).toBeVisible()
  await dialog.getByRole('textbox',{name:'知识库名称',exact:true}).fill('M65 synthetic review')
  await dialog.getByRole('textbox',{name:'知识库描述',exact:true}).fill('Synthetic UI-only form check')
  await expect(dialog.locator('.el-form-item__error')).toHaveCount(0)
  await screenshot(page,'knowledge-dialog-settled')
  expect(state.kbs).toHaveLength(3);expect(state.questions).toBe(0);expect(state.unhandled).toEqual([])
})
