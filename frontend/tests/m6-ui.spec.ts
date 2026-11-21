import { test, expect, type Page } from '@playwright/test'
import { join } from 'node:path'
import { installMockApi } from './fixtures/m6-api'
const failures = new WeakMap<Page, string[]>()
test.beforeEach(({page}) => { const errors:string[]=[];failures.set(page,errors);page.on('pageerror',error=>errors.push(error.message)) })
test.afterEach(({page}) => { expect(failures.get(page)).toEqual([]) })
const shot=(page:Page,name:string)=>page.screenshot({path:join(process.env.M6_RUN_DIR!,name+'.png'),fullPage:true,animations:'disabled'})

test('登录校验、失败文案与注册切换，不显示内部异常',async({page})=>{
  const state=await installMockApi(page,{signedOut:true,loginFailure:true})
  await page.goto('/login')
  await page.getByRole('button',{name:'登 录',exact:true}).click()
  await expect(page.getByText('请输入用户名',{exact:true})).toBeVisible()
  await expect(page.getByText('请输入密码',{exact:true})).toBeVisible()
  expect(state.logins).toBe(0)
  await page.getByRole('textbox',{name:'用户名',exact:true}).fill('m6_user')
  await page.getByRole('textbox',{name:'密码',exact:true}).fill('fictional-M6-password')
  await page.getByRole('button',{name:'登 录',exact:true}).click()
  await expect(page.locator('.login-form .el-alert')).toContainText('用户名或密码错误')
  await expect(page.locator('body')).not.toContainText('Traceback')
  expect(state.logins).toBe(1)
  await shot(page,'login-error')
  await page.getByRole('button',{name:'还没有账号？创建账号'}).click()
  await expect(page.getByRole('heading',{name:'创建你的账号'})).toBeVisible()
})

test('注册登录与首页真实接口统计',async({page})=>{
  const state=await installMockApi(page,{signedOut:true})
  await page.goto('/login')
  await page.getByRole('button',{name:'还没有账号？创建账号'}).click()
  await page.getByRole('textbox',{name:'用户名',exact:true}).fill('m6_user')
  await page.getByRole('textbox',{name:'密码',exact:true}).fill('fictional-M6-password')
  await page.getByRole('button',{name:'注册并进入'}).click()
  await expect(page.getByRole('heading',{name:'你好，m6_user'})).toBeVisible()
  await expect(page.locator('.stat-value')).toHaveText(['3','6','3'])
  expect(state.registrations).toBe(1);expect(state.logins).toBe(1);expect(state.unhandled).toEqual([])
})

test('首页统计失败用未知值代替，拒绝显示内部异常',async({page})=>{
  const state=await installMockApi(page,{statsFailure:true})
  await page.goto('/')
  await expect(page.locator('.stat-value')).toHaveText(['3','—','3'])
  await expect(page.getByText('部分文档数据暂时无法加载',{exact:false})).toBeVisible()
  await expect(page.locator('body')).not.toContainText('Traceback')
  expect(state.questions).toBe(0);expect(state.uploads).toBe(0)
})

test('知识库卡片创建编辑筛选、取消删除与确认删除',async({page})=>{
  const state=await installMockApi(page)
  await page.goto('/knowledge')
  await page.getByRole('button',{name:'创建知识库',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'创建知识库'})
  await dialog.getByRole('button',{name:'保存',exact:true}).click()
  await expect(dialog.getByText('请填写知识库名称')).toBeVisible()
  expect(state.kbs).toHaveLength(3)
  await dialog.getByRole('textbox',{name:'知识库名称',exact:true}).fill('M6 合成验收')
  await dialog.getByRole('textbox',{name:'知识库描述',exact:true}).fill('仅用于本轮离线界面验证')
  await shot(page,'knowledge-create-dialog')
  await dialog.getByRole('button',{name:'保存',exact:true}).click()
  await expect(page.getByRole('heading',{name:'M6 合成验收',exact:true})).toBeVisible()
  await page.getByRole('textbox',{name:'搜索知识库'}).fill('M6')
  await expect(page.locator('.kb-card')).toHaveCount(1)
  await page.getByRole('button',{name:'编辑',exact:true}).click()
  await page.getByRole('dialog').getByRole('textbox',{name:'知识库描述'}).fill('编辑后的合成说明')
  await page.getByRole('dialog').getByRole('button',{name:'保存',exact:true}).click()
  await expect(page.locator('.kb-card')).toContainText('编辑后的合成说明')
  await page.getByRole('button',{name:'删除',exact:true}).click()
  await page.getByRole('dialog',{name:'删除知识库'}).getByRole('button',{name:'取消',exact:true}).click()
  expect(state.kbs).toHaveLength(4)
  await page.getByRole('button',{name:'删除',exact:true}).click()
  await page.getByRole('dialog',{name:'删除知识库'}).getByRole('button',{name:'确认删除'}).click()
  await expect(page.getByText('没有找到相关知识库',{exact:true})).toBeVisible()
  expect(state.kbs).toHaveLength(3);expect(state.unhandled).toEqual([])
})

test('文档类型校验、实际上传反馈和重复事件保护',async({page})=>{
  const state=await installMockApi(page,{slowUpload:true})
  await page.goto('/documents')
  await expect(page.getByRole('button',{name:'上传文档',exact:true})).toBeEnabled()
  const input=page.locator('input[type=file]')
  await input.setInputFiles({name:'invalid.exe',mimeType:'application/octet-stream',buffer:Buffer.from('fictional')})
  expect(state.uploads).toBe(0)
  const file={name:'合成验收.txt',mimeType:'text/plain',buffer:Buffer.from('fictional M6 policy')}
  await input.setInputFiles(file)
  await expect(page.getByRole('heading',{name:'正在上传文档'})).toBeVisible()
  await input.setInputFiles(file)
  await expect(page.getByRole('button',{name:'上传文档',exact:true})).toBeDisabled()
  await shot(page,'document-upload-progress')
  const row=page.locator('.el-table__row').filter({hasText:'合成验收.txt'})
  await expect(row).toContainText('已索引')
  expect(state.uploads).toBe(1);expect(state.unhandled).toEqual([])
})

test('文档状态筛选、失败原因与删除交互',async({page})=>{
  const state=await installMockApi(page)
  await page.goto('/documents')
  await expect(page.getByText('无法提取文本',{exact:false})).toBeVisible()
  await page.locator('.table-filters .el-select').click()
  await page.getByRole('option',{name:'处理失败',exact:true}).click()
  await expect(page.locator('.el-table__row')).toHaveCount(1)
  await expect(page.locator('.el-table__row')).toContainText('历史资料扫描件.pdf')
  await page.getByRole('button',{name:'删除',exact:true}).click()
  await page.getByRole('dialog',{name:'删除文档'}).getByRole('button',{name:'确认删除'}).click()
  await expect(page.getByText('没有找到匹配的文档',{exact:true})).toBeVisible()
  expect(state.documents.some(doc=>doc.id==='doc-scan')).toBe(false)
})

test('Markdown列表代码高亮、复制与真实已有引用展示',async({page})=>{
  const state=await installMockApi(page)
  await page.goto('/chat?session=session-product')
  await expect(page.locator('.markdown-content h2')).toHaveText('创建知识库，让资料井井有条')
  await expect(page.locator('.markdown-content ol li')).toHaveCount(3)
  await expect(page.locator('.code-block .hljs-keyword').first()).toBeVisible()
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async(text:string)=>{(window as any).m6Copied=text}}}))
  await page.getByRole('button',{name:'复制代码'}).click()
  expect(await page.evaluate(()=>(window as any).m6Copied)).toContain('for name in documents:')
  await page.locator('.el-collapse-item__header').click()
  await expect(page.locator('.source-title')).toContainText('[1] 产品快速入门.pdf · 第 3 页')
  await expect(page.locator('.source-text')).toContainText('创建知识库：')
  await expect(page.getByText('文档 ID：doc-product')).toBeVisible()
  await page.locator('.chat-scroll').evaluate(el=>{el.scrollTop=el.scrollHeight})
  await shot(page,'chat-citations')
  expect(state.questions).toBe(0);expect(state.unhandled).toEqual([])
})

test('不可信Markdown不执行HTML脚本、不加载图片或危险链接',async({page})=>{
  const fence=String.fromCharCode(96).repeat(3)
  const malicious='## 安全展示\n\n<script>window.m6Xss=true</script>\n\n<img src="https://outside.invalid/key" onerror="window.m6Xss=true">\n\n[危险链接](javascript:alert(1))\n\n![远程图](https://outside.invalid/track)\n\n'+fence+'unknown\n'+ 'x'.repeat(1500)+'\n'+fence
  const state=await installMockApi(page,{markdown:malicious})
  await page.goto('/chat?session=session-product')
  await expect(page.locator('.markdown-content h2')).toHaveText('安全展示')
  await expect(page.locator('.markdown-content img,.markdown-content script,.markdown-content a[href^="javascript:"]')).toHaveCount(0)
  expect(await page.evaluate(()=>(window as any).m6Xss)).toBeUndefined()
  expect(state.blockedExternal).toEqual([])
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true)
})

test('建议问题只填入输入框，生成中反馈且只发送一次',async({page})=>{
  const state=await installMockApi(page,{slowMessage:true})
  await page.goto('/chat')
  await page.getByRole('button',{name:'这份文档主要介绍了什么？'}).click()
  await expect(page.getByRole('textbox',{name:'问题',exact:true})).toHaveValue('这份文档主要介绍了什么？')
  expect(state.questions).toBe(0)
  await page.getByRole('button',{name:'发送',exact:true}).click()
  await expect(page.getByText('正在检索知识并生成回答…',{exact:true})).toBeVisible()
  await page.getByRole('textbox',{name:'问题',exact:true}).dispatchEvent('keydown',{key:'Enter',ctrlKey:true})
  await expect(page.locator('.chat-message.assistant')).toContainText('创建知识库')
  await expect(page.locator('.chat-message.user')).toHaveCount(1)
  await expect(page.getByRole('textbox',{name:'问题',exact:true})).toHaveValue('')
  expect(state.questions).toBe(1);expect(state.unhandled).toEqual([])
})

test('历史选中态、延迟响应隔离及继续会话',async({page})=>{
  const state=await installMockApi(page,{slowHistory:true})
  await page.goto('/history')
  await expect(page.locator('.history-entry.selected')).toContainText('如何创建和管理知识库？')
  await page.locator('.history-entry').filter({hasText:'团队文档应该如何归档？'}).click()
  await page.locator('.history-entry').filter({hasText:'API 的认证方式是什么？'}).click()
  await expect.poll(()=>state.historyReads.includes('session-team')).toBe(true)
  await expect(page.locator('.history-preview')).toContainText('请根据接入指南配置账号权限')
  await expect(page.locator('.history-entry.selected')).toContainText('API 的认证方式是什么？')
  await page.getByRole('button',{name:'继续问答'}).click()
  await expect(page).toHaveURL(/session=session-api/)
  await expect(page.locator('.chat-message.assistant')).toContainText('请根据接入指南配置账号权限')
  expect(state.questions).toBe(0)
})

test('空状态与初始加载失败可恢复，不伪装成空列表',async({page})=>{
  await installMockApi(page,{slowLists:true,kbFailureOnce:true})
  await page.goto('/knowledge')
  await expect(page.getByText('正在加载知识库',{exact:true})).toBeVisible()
  await expect(page.getByText('知识库暂时未能加载',{exact:true})).toBeVisible()
  await expect(page.getByText('创建第一个知识库，开始整理知识',{exact:true})).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText('Traceback')
  await page.getByRole('button',{name:'重新加载',exact:true}).click()
  await expect(page.locator('.kb-card')).toHaveCount(3)
})

test('空数据页面与无知识库输入禁用',async({page})=>{
  const state=await installMockApi(page,{empty:true})
  for(const [path,text] of [['/knowledge','创建第一个知识库，开始整理知识'],['/documents','请先创建知识库'],['/history','还没有会话，去探索你的知识库吧']]){
    await page.goto(path);await expect(page.getByText(text,{exact:true})).toBeVisible()
  }
  await page.goto('/chat')
  await expect(page.getByRole('button',{name:'先创建知识库'})).toBeVisible()
  await expect(page.getByRole('textbox',{name:'问题',exact:true})).toBeDisabled()
  await shot(page,'chat-empty')
  expect(state.questions).toBe(0);expect(state.uploads).toBe(0)
})

for(const viewport of [{width:1440,height:1000},{width:1280,height:900},{width:1024,height:768}]){
  test('六页桌面无横向溢出 '+viewport.width,async({page})=>{
    const state=await installMockApi(page);await page.setViewportSize(viewport)
    for(const path of ['/login','/','/knowledge','/documents','/chat?session=session-product','/history']){
      await page.goto(path);await expect(page.locator('h2').first()).toBeVisible()
      if(path.startsWith('/chat'))await expect(page.locator('.chat-message.assistant')).toBeVisible()
      await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth)).toBeLessThanOrEqual(1)
      if(path.startsWith('/chat'))expect((await page.locator('.composer-bottom').boundingBox())!.y).toBeLessThan(viewport.height)
    }
    expect(state.unhandled).toEqual([])
  })
}

test('独立Vite未被Mock截获的API被硬阻断，无后端代理',async({request})=>{
  const response=await request.get('http://127.0.0.1:15176/api/health')
  expect(response.status()).toBe(503);expect((await response.json()).code).toBe('M6_MOCK_ONLY')
})

test('恢复长会话后滚动到最新消息，不产生新提问',async({page})=>{
  const state=await installMockApi(page)
  state.messages['session-product']=Array.from({length:24},(_,index)=>({
    id:'long-history-'+index,role:index%2?'assistant':'user',
    content:'这是第 '+index+' 条合成历史消息，用于检查恢复会话后的滚动位置。',citations:[],
  }))
  state.messages['session-product'].push({id:'history-tail',role:'assistant',content:'这是最后一条合成历史消息。',citations:[]})
  await page.goto('/chat?session=session-product')
  await expect(page.locator('.chat-message.assistant').last()).toContainText('这是最后一条合成历史消息。')
  await expect.poll(()=>page.locator('.chat-scroll').evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight)).toBeLessThan(4)
  expect(state.questions).toBe(0);expect(state.unhandled).toEqual([])
})
