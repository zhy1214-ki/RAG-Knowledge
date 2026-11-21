import type { Page } from '@playwright/test'
export const answer = '## 创建知识库，让资料井井有条\n\n在 **知识库管理** 中选择「创建知识库」，填写名称与描述后即可上传文档。\n\n1. 按主题建立知识库，避免把所有文件堆在一起。\n2. 上传资料并等待「已索引」。\n3. 在智能问答中选择对应知识库，开始提问。\n\n> 每个回答都可以展开来源，回到原文确认依据。[1]\n\n### 一个整理文档的小例子\n\n```python\ndocuments = ["产品指南.pdf", "操作规范.docx"]\nfor name in documents:\n    print(f"已整理：{name}")\n```\n\n建议先从一个清晰的主题开始，再逐步扩展知识范围。'
export async function installMockApi(page: Page, options: {
  empty?: boolean; signedOut?: boolean; loginFailure?: boolean; statsFailure?: boolean;
  messageFailure?: boolean; slowMessage?: boolean; markdown?: string; slowUpload?: boolean;
  slowHistory?: boolean; slowLists?: boolean; kbFailureOnce?: boolean;
} = {}) {
  const timestamp = '2026-11-18T01:30:00Z'
  const kbs = [
    { id:'kb-product', name:'产品使用指南', description:'从账号设置到核心功能，快速找到每一步的操作说明。', created_at:timestamp },
    { id:'kb-team', name:'团队协作规范', description:'汇集团队的工作方式、协作约定与日常流程。', created_at:'2026-11-17T02:00:00Z' },
    { id:'kb-api', name:'API 与集成文档', description:'接口说明、接入流程与常见问题，连接你的工作工具。', created_at:'2026-11-16T06:00:00Z' },
  ]
  const document = (id:string,kb:string,name:string,type:string,status:string,progress:number,chunks:number,error:string|null=null) =>
    ({id,knowledge_base_id:kb,name,file_type:type,status,progress,chunk_count:chunks,error_code:error,size:186432,created_at:timestamp})
  const documents = [
    document('doc-product','kb-product','产品快速入门.pdf','pdf','indexed',100,18),
    document('doc-roles','kb-product','账号与权限说明.docx','docx','processing',62,0),
    document('doc-scan','kb-product','历史资料扫描件.pdf','pdf','failed',0,0,'PARSE_ERROR'),
    document('doc-team','kb-team','团队协作手册.docx','docx','indexed',100,12),
    document('doc-archive','kb-team','文档归档规范.md','md','indexed',100,4),
    document('doc-api','kb-api','接口接入指南.md','md','indexed',100,9),
  ]
  const citation = { source_id:1,chunk_id:'chunk-product',document_id:'doc-product',knowledge_base_id:'kb-product',
    source_name:'产品快速入门.pdf',source_location:{format:'pdf',page:3},
    text:'创建知识库：进入知识库管理，选择创建知识库并填写名称。上传文档后，等待处理状态变为已索引，即可在智能问答中选择该知识库提问。',score:0.87 }
  const sessions = [
    {id:'session-product',knowledge_base_id:'kb-product',title:'如何创建和管理知识库？',created_at:timestamp},
    {id:'session-team',knowledge_base_id:'kb-team',title:'团队文档应该如何归档？',created_at:'2026-11-17T07:00:00Z'},
    {id:'session-api',knowledge_base_id:'kb-api',title:'API 的认证方式是什么？',created_at:'2026-11-16T06:30:00Z'},
  ]
  const messages:Record<string,any[]> = {
    'session-product':[
      {id:'question-product',role:'user',content:'如何创建和管理知识库？',citations:[],created_at:timestamp},
      {id:'answer-product',role:'assistant',content:options.markdown||answer,citations:[citation],created_at:timestamp},
    ],
    'session-team':[{id:'team-answer',role:'assistant',content:'建议按主题归档，并在上传后确认文档的索引状态。',citations:[],created_at:timestamp}],
    'session-api':[{id:'api-answer',role:'assistant',content:'请根据接入指南配置账号权限，再完成接口接入。',citations:[],created_at:timestamp}],
  }
  const state = { kbs:options.empty?[]:kbs, documents:options.empty?[]:documents,
    sessions:options.empty?[]:sessions, messages, uploads:0,questions:0,logins:0,registrations:0,
    unhandled:[] as string[],blockedExternal:[] as string[],historyReads:[] as string[],listReads:0 }
  if (!options.signedOut) await page.addInitScript(() => {
    sessionStorage.setItem('token','m6-fictional-token');sessionStorage.setItem('username','lin_yuan')
  })
  let counter=0
  await page.route('**/*',async route => {
    const req=route.request(),url=new URL(req.url())
    if (url.origin!=='http://127.0.0.1:15176') { state.blockedExternal.push(url.origin); return route.abort() }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const path=url.pathname.slice(4),method=req.method()
    const ok=(data:unknown,status=200)=>route.fulfill({status,json:{code:'OK',message:'成功',data}})
    const fail=(code:string,status=503)=>route.fulfill({status,json:{code,message:'Traceback: fictional internal detail MUST NOT DISPLAY',data:null}})
    if(path==='/health')return ok({status:'ok',model_backend:'mock',vector_backend:'memory'})
    if(path==='/auth/register'){state.registrations++;return ok({id:'m6-user',username:req.postDataJSON().username},201)}
    if(path==='/auth/login'){state.logins++;return options.loginFailure?fail('UNAUTHORIZED',401):ok({access_token:'m6-fictional-token',user:{id:'m6-user',username:req.postDataJSON().username}})}
    if(req.headers().authorization!=='Bearer m6-fictional-token')return fail('UNAUTHORIZED',401)
    if(path==='/knowledge-bases'){
      if(method==='GET'){state.listReads++;if(options.slowLists)await new Promise(resolve=>setTimeout(resolve,350));if(options.kbFailureOnce&&state.listReads===1)return fail('DATABASE_ERROR');return ok(state.kbs)}
      if(method==='POST'){const row={id:'kb-new-'+ ++counter,...req.postDataJSON(),created_at:timestamp};state.kbs.unshift(row);return ok(row,201)}
    }
    const kbMatch=path.match(/^\/knowledge-bases\/([^/]+)$/)
    if(kbMatch){
      const id=kbMatch[1]
      if(method==='PUT'){const row=state.kbs.find(k=>k.id===id);Object.assign(row!,req.postDataJSON());return ok(row)}
      if(method==='DELETE'){state.kbs=state.kbs.filter(k=>k.id!==id);state.documents=state.documents.filter(d=>d.knowledge_base_id!==id);state.sessions=state.sessions.filter(s=>s.knowledge_base_id!==id);return ok(null)}
    }
    const docsMatch=path.match(/^\/knowledge-bases\/([^/]+)\/documents$/)
    if(docsMatch){
      if(method==='GET')return options.statsFailure?fail('DATABASE_ERROR'):ok(state.documents.filter(d=>d.knowledge_base_id===docsMatch[1]))
      if(method==='POST'){
        state.uploads++
        if(options.slowUpload)await new Promise(resolve=>setTimeout(resolve,600))
        const doc=document('doc-new-'+ ++counter,docsMatch[1],'合成验收.txt','txt','indexed',100,1)
        state.documents.unshift(doc);return ok({...doc,status:'uploaded',progress:0},202)
      }
    }
    const deleteDoc=path.match(/^\/knowledge-bases\/([^/]+)\/documents\/([^/]+)$/)
    if(deleteDoc&&method==='DELETE'){state.documents=state.documents.filter(d=>d.id!==deleteDoc[2]);return ok(null)}
    if(path==='/sessions'){
      if(method==='GET')return ok(state.sessions)
      if(method==='POST'){const row={id:'session-new-'+ ++counter,...req.postDataJSON(),title:'新会话',created_at:timestamp};state.sessions.unshift(row);state.messages[row.id]=[];return ok(row,201)}
    }
    const sessionMatch=path.match(/^\/sessions\/([^/]+)$/)
    if(sessionMatch){
      if(method==='GET')return ok(state.sessions.find(s=>s.id===sessionMatch[1]))
      if(method==='DELETE'){state.sessions=state.sessions.filter(s=>s.id!==sessionMatch[1]);delete state.messages[sessionMatch[1]];return ok(null)}
    }
    const messageMatch=path.match(/^\/sessions\/([^/]+)\/messages$/)
    if(messageMatch){
      const id=messageMatch[1]
      if(method==='GET'){if(options.slowHistory&&id==='session-team')await new Promise(resolve=>setTimeout(resolve,250));state.historyReads.push(id);return ok(state.messages[id]||[])}
      if(method==='POST'){
        state.questions++
        if(options.slowMessage)await new Promise(resolve=>setTimeout(resolve,600))
        if(options.messageFailure)return fail('MODEL_UNAVAILABLE')
        const text=req.postDataJSON().question
        const message={id:'answer-'+ ++counter,role:'assistant',content:options.markdown||answer,citations:[citation],created_at:timestamp}
        state.messages[id]=[...(state.messages[id]||[]),{id:'user-'+counter,role:'user',content:text,citations:[],created_at:timestamp},message]
        const session=state.sessions.find(s=>s.id===id);if(session)session.title=text
        return ok(message)
      }
    }
    state.unhandled.push(method+' '+path);return fail('UNPLANNED_MOCK_API',404)
  })
  return state
}
