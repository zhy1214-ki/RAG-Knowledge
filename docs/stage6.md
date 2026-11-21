# Stage 6：Vue 3前端开发与UI优化

本Stage是开发历程专题，不是历史Git版本。运行结论来自限定范围的既有记录，本轮不执行验收。

## 1. 阶段目标

通过六个页面完成从登录到知识库、文档、问答和历史的操作，并集中提升桌面演示体验。前端从M1开始，M4补全功能，M6优化，M6.5审查，M6.6仅更新演示前端。

## 2. 技术与依赖

Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router、Axios；MarkdownIt、DOMPurify及highlight.js负责受限内容展示，Playwright用于合成API交互验证。

## 3. 实现内容

六页为登录/注册、首页、知识库、文档、AI问答和会话历史。统一标题、加载/空/错误状态；首页统计使用已有接口。文档上传显示传输进度和后端阶段，问答左右布局、消息气泡、代码复制、来源查看与会话选择均复用现有API。

## 4. 核心代码位置

| 代码 | 职责 |
|---|---|
| [六页路由](../frontend/src/router/index.ts) | 页面入口和登录态导航 |
| [Chat.vue](../frontend/src/views/Chat.vue) | 发送状态、防重及历史加载 |
| [Documents.vue](../frontend/src/views/Documents.vue) | 上传、状态轮询、筛选及错误提示 |
| [History.vue](../frontend/src/views/History.vue) | 会话列表与消息预览 |
| [MarkdownContent.vue](../frontend/src/components/MarkdownContent.vue) | 禁原始HTML、净化、代码块和禁远程图片 |
| [响应式样式](../frontend/src/styles/responsive.css) | 桌面/窄屏布局与减少动画偏好 |

## 5. 关键实现流程

用户主动操作 → API请求 → 加载/成功/安全失败反馈。文档轮询只读取状态并在离开页面时清理。发送中或uncertain时阻止再次提交；失败/超时后只允许检查原记录，不自动重发。历史异步结果避免覆盖新选择，长消息完成布局后再滚动。

## 6. 测试与验证结果

H04中M6 TypeScript/构建和27个不同Mock场景PASS；M6.5审查19张本地图及4个不同定向Mock，覆盖两聊天入口1024/1280/1440宽度；M6.6六页Mock工作流与资源检查PASS。不能把重复回归相加，也不能把这次UI部署写为重新真实问答。定义见[m6-ui](../frontend/tests/m6-ui.spec.ts)、[m65-review](../frontend/tests/m65-review.spec.ts)。

## 7. 遇到的问题及解决方案

测试曾出现定位选择器歧义，修正定位而不删除断言；实际产品还修复长历史渲染/滚动时序和图标压缩。Markdown禁原始HTML后仍经净化，来源用文本展示，远程图片被替换为提示，避免将模型内容作为任意前端代码。没有将普通加载态包装成Token流式响应。

## 8. 阶段成果

形成现代浅色企业管理界面，桌面布局有明确验证；存在窄屏CSS不等于所有移动设备都实测通过。前端防重也不是跨所有浏览器标签页的完整幂等；关键真实操作另受后端保护。

## 9. 对应真实开发证据

[开发历程](development-history.md)H04；[M6已分发记录](M6_UI.md)；[前端入口](../frontend/src/App.vue)、[API层](../frontend/src/api/index.ts)。原截图不随源码分发，本次没有补造截图或运行浏览器。

[返回计划](development-plan.md) · [查看实际历程](development-history.md)
