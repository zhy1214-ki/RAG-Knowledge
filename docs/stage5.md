# Stage 5：Qwen RAG问答、来源引用与会话历史

本Stage是开发历程专题，不是历史Git版本。运行结论来自限定范围的既有记录，本轮不执行验收。

## 1. 阶段目标

把知识库检索结果交给Qwen生成有依据的回答，引用由服务器验证并保存。主要对应M3及M4完善；真实模型链路另由M5和后续R阶段验证，不把协议Mock当成模型效果。

## 2. 技术与依赖

Qwen Plus兼容HTTP接口、text-embedding-v4、Milvus Lite、SQLAlchemy与PostgreSQL。普通模型适配与独立真实模式GuardedModels共享业务接口，后者额外约束费用与运行状态。

## 3. 实现内容

系统Prompt将证据和历史声明为不可信数据，不执行文档中的指令或工具。模型返回JSON answer/source_ids；检查编号类型、范围及正文引用是否都在声明集合中。引用的文档ID、名称、位置和片段来自服务器检索数据，而非模型自行生成。

## 4. 核心代码位置

| 代码 | 职责 |
|---|---|
| [问答服务](../backend/app/services/chat.py) | 检索、上下文历史、消息事务 |
| [模型适配](../backend/app/rag/providers.py) | Prompt、调用及引用校验 |
| [会话API](../backend/app/api/chat.py) | 用户归属、会话及消息读写 |
| [请求响应模型](../backend/app/schemas/__init__.py) | 问题、Top-K、回答和引用契约 |
| [消息展示](../frontend/src/components/MessageItem.vue) | 答案与来源快照展示 |

## 5. 关键实现流程

验证用户与会话归属 → 查询Embedding → Milvus过滤及关系库复核 → 取最多10条历史（模型侧每条截取最多4000字符）→ 构造不可信证据上下文 → 生成并验证引用 → 同一事务保存用户/AI两条消息。无indexed文档时不进入查询Embedding；有索引但证据不足时可已产生查询Embedding，却不调用Qwen。

## 6. 测试与验证结果

H01中的M3覆盖引用、无证据不生成、模型失败不保存半条对话、会话隔离及非法引用拒绝；定义见[test_m3.py](../backend/tests/test_m3.py)。H02/H03/H07/H09分别提供真实模型范围；本轮没有重新提问或调用模型。

## 7. 遇到的问题及解决方案

模型可能声称不存在的来源，不能只信任正文里的编号，因此同时校验JSON编号和正文引用，越界或未声明引用返回安全错误。来源正文与模型回答均不可信；防提示注入是约束与隔离设计，不宣称通过了全面对抗评测。历史保存失败不能假报回答已持久化。

## 8. 阶段成果

支持有来源的知识库问答和历史恢复，无证据时明确说明；PDF页码来自解析，其他格式不造页码。文档删除仍可保留消息中的来源快照，会话/知识库删除会清相应历史；查看历史不重新生成。

## 9. 对应真实开发证据

[开发历程](development-history.md)H01～H03、H07和H09；[问答流程](final-delivery/diagrams/07-rag-question-answer.mmd)；[引用流程](final-delivery/diagrams/08-citation-processing.mmd)。没有公开真实用户问答或完整敏感上下文。

[返回计划](development-plan.md) · [查看实际历程](development-history.md)
