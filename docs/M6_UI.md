# M6：前端 UI 与用户体验优化

> GitHub副本说明：标为“本地专用”的原始证据未纳入Git，不是可下载附件。分类及存在性见[本地材料索引](LOCAL_EVIDENCE_INDEX.md)；不复制原始审计或用户数据来补齐链接。

日期：2026-11-18。状态：前端离线/Mock 验收 PASS。
原 M1–M5 验收证据保持；本轮真实模型调用0，历史累计仍6，不把 Mock 结果当成新增真实模型证据。
没有 Docker 操作、PostgreSQL/Milvus 连接、真实 Key 读取、业务数据删除、Git push 或远程部署。

## 设计规范与前后对比

保留「知序」品牌，主色 #2f6cf6，浅灰工作区与白色内容层，统一圆角、边框、按钮、弹窗及状态反馈。
样式按 base/pages/chat/responsive 四个文件组织，所有图形使用已有图标和 CSS，
不加载远程字体、图片或装饰服务。核心聊天正文14px，页面标题26px，桌面优先，保留窄屏适配。

| 页面 | 改造前主要问题 | 本次结果 |
|---|---|---|
| 登录与注册 | 基础表单、错误仅短暂提示、无 busy 入口保护 | 双栏品牌布局、字段校验、持续错误反馈、忙碌禁用；注册成功后登录失败不会再次注册 |
| 系统首页 | 统计初始化为0、部分请求失败无明确状态 | 使用原知识库/文档/会话接口计数，未知值显示—；快捷入口、真实已有知识库与最近会话 |
| 知识库 | 基础表格、空数据重复、保存无反馈 | 三列卡片、名称/描述搜索、创建编辑校验、确认删除、加载/空/错误状态 |
| 文档 | 上传按钮为主、传输无反馈、状态不突出 | 拖拽/文件选择、实际传输进度、服务器索引进度、状态筛选、失败原因、清晰文件列表 |
| 智能问答 | 单列纯文本、无代码样式、生成中缺少消息上下文 | 左侧知识库/会话、右侧聊天；Markdown、代码高亮/复制、消息气泡、生成状态、引用原文展开 |
| 会话历史 | 只能看列表再跳转 | 选中态列表、消息/引用预览、搜索、继续问答、确认删除；延迟响应不覆盖新选择 |

六页前后对比与7种补充状态（本地专用材料，不随发布源码分发）。
共19张截图，全部为合成数据 Mock 截图；统计数字来自夹具的 API 返回，
生产页面没有硬编码业务数量。新代码未部署到现有演示容器，因此旧8080页面仍是原镜像。

## 交互与安全细节

- 页面标题、加载/空/错误状态和消息展示使用简单共享组件，不引入额外状态框架。
- 上传传输进度来自 axios onUploadProgress，未知总量使用不定进度；解析索引进度来自原文档API。
  uploaded、processing、indexed、failed、deleting 分别显示；轮询仅GET，离开页面后停止。
- 保留上传中的同步 busy 检查；失败/超时保持暂停，刷新仅查看记录，不自动重新上传。
- 聊天 busy 在请求前同步设置；成功直接使用POST返回的回答，不追加易导致误重发的GET。
  失败/超时保持 uncertain，记录查看只GET，不自动解锁发送或重新提问；建议问题只填输入框。
- 加载会话与生成回答分离；恢复长历史后，在实际消息渲染完成后滚动到最后一条。
- 引用保持服务返回的 source_id、document_id、文本；只读展开不再调用检索或模型。
  只为 format=pdf 的真实正整数 page 显示页码，Word/TXT 不推测页码。
- Markdown html=false，DOMPurify 再净化；图片转为纯文字，禁止自动远程图片请求；
  危险链接不生成可执行URL。代码只按支持语言高亮，未知语言以转义文本展示。
  引用原文始终Vue文本插值，不按HTML或Markdown执行。
- 统一错误文案按既有错误码映射，不直接展示供应商/服务器 message 或内部堆栈。
  原JWT流程不变，模型Key不进入前端、截图或构建产物。
- 页面级防重保护没有扩展为跨标签页幂等；后端次数/预算门禁仍是独立真实验收的重要约束。
  本轮没有修改检索、引用生成、消息事务或数据库用户隔离规则。

Markdown相关维护参考：[DOMPurify](https://github.com/cure53/DOMPurify)、
[Highlight.js](https://highlightjs.readthedocs.io/en/latest/readme.html)；实现见 MarkdownContent.vue。
必要新增依赖：markdown-it 14.3.3、dompurify 3.4.18、highlight.js 11.12.0，及Markdown的开发类型声明。
安装使用 ignore-scripts，版本由 package-lock.json 固定。

## 实际验证

- TypeScript PASS；最终 npm run build 包含 vue-tsc 与 Vite，生产构建 PASS。
- 27项不同 Mock 检查最终全部通过：原M5受影响防重/API场景10项，新增M6 UI/安全/布局17项。
- 初轮26项分段执行，3+2+10+11通过；失败为3处测试定位问题：
  持久提示与Toast同文案、状态与隐藏下拉选项同文案、Element Plus内部输入框被正常占位层覆盖。
  按实际区域/点击容器调整定位，保留业务断言；已经通过的未受影响用例不重复。
- 最后发现并修复长历史滚动时序，新增该用例，并仅复验2个受影响的聊天/历史用例；定向3项通过。
- 六页在1440、1280、1024桌面宽度均无文档级横向溢出；
  Markdown恶意HTML/危险链接/远程图片/超长代码测试通过，新增用例未出现pageerror。
- 六页基线与优化后截图通过；图标尺寸检查和聊天生成/失败状态截图通过。
  人工检查中修复了装饰图标被通用i元素样式压缩的问题，仅补拍受影响页面。
- 原M4原生后端Word浏览器用例仅同步UI定位器，NOT_RUN；
  该用例会启动后端和Milvus，不在本轮受控验证范围。旧默认配置限制到demo.spec.ts，避免收集真实验收脚本。
- 真实后端/PG/Milvus/付费RAG测试均未重复。M6新UI真实模型浏览器验收 NOT_RUN。

审计：data/m6-ui/verification.json、test-receipts.json、build-final.log 与各次 regression 日志。
71个受保护的后端/验收脚本/历史文件哈希保持不变，M5真实累计6次未重置。

## 后续有代码变更时的离线复核方式

在项目根目录运行：

    npm run --prefix frontend build
    node frontend/scripts/run-m6-ui.mjs regression
    node frontend/scripts/run-m6-ui.mjs after

regression 只收集 M6 与受影响的 M5 Mock 测试；after 采集当前界面，不能重建旧基线。
运行器为每次创建独立随机输出根目录，Playwright仅清自己的子目录；
不覆盖现有审计/截图，不向子进程传递模型凭据。
Vite仅监听127.0.0.1:15176，envDir=false、无后端代理；
页面所有API由路由夹具响应，任何漏拦截API由Vite返回M6_MOCK_ONLY，
外部页面请求被拦截。服务由测试运行器退出时清理，不操作现有演示容器。

## 修改文件

已修改的原前端源码：
- frontend/src/App.vue
- frontend/src/api/index.ts
- frontend/src/style.css
- frontend/src/views/Chat.vue
- frontend/src/views/Documents.vue
- frontend/src/views/History.vue
- frontend/src/views/Home.vue
- frontend/src/views/Knowledge.vue
- frontend/src/views/Login.vue

新增展示源码：
- frontend/src/components/MarkdownContent.vue
- frontend/src/components/MessageItem.vue
- frontend/src/components/PageHeading.vue
- frontend/src/components/StatePanel.vue
- frontend/src/styles/base.css
- frontend/src/styles/chat.css
- frontend/src/styles/pages.css
- frontend/src/styles/responsive.css
- frontend/src/types.ts
- frontend/src/utils.ts

依赖与前端验证文件：
- frontend/package.json
- frontend/package-lock.json
- frontend/playwright.config.ts
- frontend/tests/demo.spec.ts
- frontend/tests/m5-offline.spec.ts
- frontend/vite.m6.config.ts
- frontend/playwright.m6.config.ts
- frontend/scripts/run-m6-ui.mjs
- frontend/tests/m6-ui.spec.ts
- frontend/tests/m6-capture.spec.ts
- frontend/tests/fixtures/m6-api.ts

文档：README.md、docs/M6_UI.md、docs/PROGRESS.md、docs/screenshots/m6/README.md；
新增截图及data/m6-ui下本轮审计，不修改旧真实验收报告。

## 当前边界与下一步

无功能阻塞。Vite有主包体积提示：主JS约1118.42kB，gzip约372.82kB；
Markdown/消息模块已独立到共享异步块约188.40kB（gzip76.03kB）。
本轮没有扩大为打包架构重构或性能压测，可后续按需处理组件按需引入/分包。

现有Mock容器未部署这些修改。建议先审阅截图与交互，再决定是否更新演示前端；
任何容器更新、远程部署或新的真实模型验收仍需相应独立授权。
M5原真实验收脚本/批准快照保持，M6更换了卡片与历史展示；
未来真实前端再验收需先适配相应定位器、重新审核前端哈希和范围，不能复用旧审批。
