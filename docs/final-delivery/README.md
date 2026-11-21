# RAG-Knowledge V1.0 毕业设计交付包

> GitHub副本说明：标为“本地专用”的原始证据未纳入Git，不是可下载附件。分类及存在性见[本地材料索引](../LOCAL_EVIDENCE_INDEX.md)；不复制原始审计或用户数据来补齐链接。

编制：M7；资料截止2026-11-18。
本包依据项目实际源码、ORM/迁移和历史执行摘要，不包含新增运行验收。
当前新版8080/Mock模式以M6.6记录为依据，M7未现场查询服务、数据库或容器。
历史真实模型调用6次，本轮0次。

## 阅读顺序

| 文档 | 用途 |
|---|---|
| [SYSTEM_REQUIREMENTS](SYSTEM_REQUIREMENTS.md) | 目标、六模块、约束及未实现功能 |
| [SYSTEM_ARCHITECTURE](SYSTEM_ARCHITECTURE.md) | 实际技术栈、目录、模块和总体图 |
| [DATABASE_DESIGN](DATABASE_DESIGN.md) | 六表38字段、7外键、索引及ER |
| [RAG_DESIGN](RAG_DESIGN.md) | 上传、解析、Embedding、检索、问答、引用六图 |
| [API_REFERENCE](API_REFERENCE.md) | 20个实际应用端点和模型/错误语义 |
| [SYSTEM_TEST_REPORT](SYSTEM_TEST_REPORT.md) | 离线/Mock/设施/真实后端/真实浏览器/8080分开报告 |
| [USER_GUIDE](USER_GUIDE.md) | 六页使用、状态与来源；没有公开账号口令 |
| [DEPLOYMENT_GUIDE](DEPLOYMENT_GUIDE.md) | 配置真实路径、新副本说明及M6.6版本管理 |
| [GRADUATION_DESIGN_DRAFT](GRADUATION_DESIGN_DRAFT.md) | 摘要、七章初稿和待核实参考资料 |
| [DEFENSE_MATERIALS](DEFENSE_MATERIALS.md) | 项目介绍、12页PPT大纲及答辩问答 |
| [DEMO_SCRIPT](DEMO_SCRIPT.md) | 推荐7分钟只读/历史证据演示脚本 |
| [DELIVERY_CHECKLIST](DELIVERY_CHECKLIST.md) | 已完成/待完善/不适用/未验证 |
| SOURCE_INDEX（本地专用材料，不随发布源码分发） / DELIVERY_VERIFICATION（本地专用材料，不随发布源码分发） | 静态来源与本轮文档核验记录 |

## 图源和截图

[diagrams](diagrams/)保存8份独立Mermaid源码，同时嵌在对应设计文档中。
可在支持Mermaid的编辑器阅读；本轮未用外部渲染服务，图片导出仍待完成。

assets/screenshots（本地专用材料，不随发布源码分发）保存7张M6.6实际8080新版前端的原样截图。
画面由真实Vue生产包渲染，业务内容来自合成API夹具。
不能声称这些截图是当前真实用户资料或再次真实Qwen回答的照片。

## 验收口径

PASS表示明确范围内的既有证据通过；FAIL是记录中的失败尝试；
BLOCKED是当时门禁阻断，需结合后续获授权执行结果阅读；
NOT_RUN表示未执行；NOT_VERIFIED表示尚无充分核实证据。
早期BLOCKED不会被覆盖删除，也不能反过来否定后续明确范围内的PASS。

M1–M5及M6.6的完整原始证据仍位于项目docs与data；
测试报告给出经过筛选的链接。独立复制本目录时，部分外部源码/审计链接需要附带
经过授权的项目副本或另外导出的脱敏证据摘要，不能直接分发整份data/.env/内部日志。

本包不是最终学校排版稿、PPT成品或录屏；个人信息、正式书目与现场彩排仍待完善。
本包保留M7编制时的历史口径；新发布副本的安装与分发边界以根README为准，不将历史快照解释为当前线上状态。