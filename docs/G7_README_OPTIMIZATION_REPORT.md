# G7：README 专业化展示升级报告

**结论：PASS（本地文档优化与离线检查范围）。具备申请独立文档提交的条件，本轮未暂存、提交或推送。**

基线：`main` / `31f13fe03a6b27098f07a519c4d6e03af2926c51`。G6.2 的文档推送已经完成；本次 G7 修改仍只保存在本地，不宣称 GitHub 已展示新版 README。

## 1. README 调整

按“项目介绍 → 技术栈 → 功能展示 → 架构 → RAG 流程 → 技术亮点 → 测试验收 → 快速开始 → 开发阶段 → 限制与安全”重组。

- 使用“知序 · RAG-Knowledge”标题与具体应用场景，突出文档到答案的完整链路。
- 将技术栈整理为角色清晰的表格，说明 LlamaIndex 主要用于分块。
- 使用六张合成 UI 示意图（已实现的 Vue 界面 + Mock 数据），附展示说明和来源索引。
- 新增两幅 Mermaid 图，分别说明真实组件调用关系和索引/问答流程。
- 说明用户隔离、引用校验、消息事务、费用门禁、失败暂停及可信时间恢复的实现与适用范围。
- 明确 R4.6 的两次 Embedding、一次 Qwen 均 VERIFIED，并与 Mock UI 展示区分。
- 保留新副本 Docker 与本地开发启动方式，默认 Mock、不要求模型密钥。
- 删除 README 中“开发阶段文档尚未提交/推送”的过期表述，保留全部 Stage 导航。
- 保留 OCR 缺失、单实例、任务中断、费用估算和历史时间证据不足等边界。

## 2. 实际变更清单

| 状态 | 文件 |
|---|---|
| 修改 | [README.md](../README.md) |
| 新增 | 本报告 |
| 新增 | [公开截图说明](images/product/README.md) |
| 新增 | `docs/images/product/home.png` |
| 新增 | `docs/images/product/knowledge.png` |
| 新增 | `docs/images/product/documents.png` |
| 新增 | `docs/images/product/chat.png` |
| 新增 | `docs/images/product/citations.png` |
| 新增 | `docs/images/product/history.png` |

共 **9 个预期变更：1 个修改、8 个新增**。没有删除文件，没有修改前后端业务源码、依赖锁文件、Docker 配置或已有 Stage 文档。预览 HTML、截图、渲染库及检查回执仅位于 Git 忽略的 `.cache/g7/`，不纳入拟提交文件。

## 3. 技术事实与证据对照

| README 内容 | 核对依据 |
|---|---|
| 真实技术栈与配置默认值 | [依赖](../backend/requirements.lock.txt)、[前端依赖](../frontend/package.json)、[配置](../backend/app/core/config.py)、[Compose](../docker-compose.yml) |
| 六页及交互 | [路由](../frontend/src/router/index.ts)、[前端阶段](stage6.md) |
| 用户、知识库、文档及会话归属 | [API 权限依赖](../backend/app/api/deps.py) |
| 解析、分块与索引状态 | [解析器](../backend/app/rag/parsing.py)、[文档服务](../backend/app/services/documents.py) |
| 知识库限定检索、引用与消息事务 | [问答服务](../backend/app/services/chat.py)、[向量适配](../backend/app/rag/vectors.py)、[模型适配](../backend/app/rag/providers.py) |
| 费用、限频、并发、UNKNOWN 与时钟保护 | [独立运行门禁](../backend/app/real_usage/guard.py)、[受保护模型](../backend/app/real_usage/models.py)、[部署阶段](stage7.md) |
| R4.6：真实 Embedding 2 次、Qwen 1 次 VERIFIED，答案与引用/历史通过 | [验收阶段](stage8.md)、[开发历程](development-history.md)，并只读核对本地原始 R4.6 报告中的非敏感结论 |

原始 R4.6 记录中，文档 Embedding 与查询 Embedding 各 1 次，Qwen 回答 1 次；答案为“15分钟响应、4小时恢复”，引用关联测试原文。原报告包含的账号、认证和运行细节不复制到公开材料。

本次只核对源码和既有证据，**不代表重跑了真实环境验收或查询了当前运行账本**。历史 PASS 不延伸为新环境、长期稳定性或全场景准确率 PASS。

## 4. 架构图、流程图与 Markdown 预览

| 检查 | 结果 |
|---|---|
| 两幅 Mermaid 解析及 SVG 渲染 | PASS，本地 Mermaid 11.12.0 |
| 架构关系 | PASS_STATIC；FastAPI 调用模型，PostgreSQL/文件/Milvus 分别持久化，无数据库直接调用 Qwen 的错误关系 |
| RAG 流程 | PASS_STATIC；索引、查询向量化、归属/状态/相似度校验、证据不足分支、引用及历史均体现 |
| Markdown 预览 | PASS，使用现有 MarkdownIt 与独立 Chromium |
| 图片实际加载 | 6/6 PASS |
| 页内导航 | 5/5 PASS |
| 桌面宽度 | 1024 / 1280 / 1440 均无文档级横向溢出 |
| 浏览器 pageerror / 外部页面请求 | 0 / 0 |
| GitHub 线上实际新版渲染 | NOT_VERIFIED，本轮未提交、推送或发布新版 README |

图使用 GitHub 支持的 `mermaid` fenced code block 与基础 flowchart 语法；本地预览不等于当前 GitHub 渲染器版本的线上实测。兼容方式参考 [GitHub 官方图表说明](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams)。

预览使用的固定版本渲染库只保存在忽略目录，不增加项目依赖，不复制到前端构建或公开图片中。预览期间不访问现有演示服务，临时浏览器已关闭。

## 5. 截图来源与隐私

六张合成 UI 示意图来自既有 M6 的新版首页、知识库、文档、聊天、会话历史及引用展开场景。原素材已纳入历史 UI 审查，本轮再次逐张查看，并与[合成夹具](../frontend/tests/fixtures/m6-api.ts)及[截图场景](../frontend/tests/m6-capture.spec.ts)核对。

- 账号别名、文件名、统计、文档 ID 和对话均为合成测试数据，不是个人真实身份或业务记录。
- 没有浏览器地址栏、密钥、认证 Token、密码、邮箱、私有路径或审批信息。
- 六图 SHA-256 与历史来源逐字节一致，未裁剪、拼接、重绘或修改文字。
- 六份 PNG 均可解码，未发现文本元数据或 EXIF。
- README 明确标注 Mock；截图中的处理进度及 PDF 页码不作为真实索引或模型质量证据。
- 无需补拍产品图，没有启动模型、上传文档或连接生产数据。

详细来源标识、尺寸和 SHA-256 见[公开截图说明](images/product/README.md)。

## 6. 链接、安全与范围检查

| 检查 | 结果 |
|---|---|
| README 相对引用 | 48 处，缺失 0 |
| 截图来源说明相对引用 | 9 处，缺失 0 |
| README Stage 1～8、计划、架构、历程导航 | 11 个目标全部存在 |
| 本报告新增相对引用 | 最终单独复核，无缺失目标 |
| 新改 Markdown 敏感信息扫描 | PASS，未发现所检查的真实密钥、Token、私钥、邮箱、含凭据连接串、私有绝对路径或历史审批标识 |
| PNG 隐私检查 | PASS，人工画面复核、合成来源核对及元数据检查 |
| 其余已跟踪文件 | **185 个 SHA-256 全部不变**，包括已验收业务源码与配置 |
| 原始项目保护 | Git 引用、工作区状态及 3 份原始未提交文档哈希不变 |
| 当前发布仓库 | `main` 与 HEAD 不变，暂存区为空，仅有上述 9 个工作区变更 |
| 空白检查 | `git diff --check` PASS；新文档另检查行尾空白与文件末尾 |
| 业务测试、数据库及模型 | 未重复运行业务测试；未操作数据库或容器；真实模型请求 0 |
| Git 操作 | 提交、推送、拉取、抓取及标签变更均 0 |

安全检查覆盖本次实际新增/修改内容；其余发布内容复用既有审核，并通过字节不变核验保持证据有效。扫描不构成“绝无任何隐私风险”的无限保证。

## 7. 独立提交准备与剩余边界

**已具备申请独立文档提交的本地条件。** 后续如获授权，可仅审阅并暂存上表 9 个文件，创建单独的 README/展示文档提交；推送仍需独立授权。

本轮没有新 Commit Hash，没有新标签，没有上传图片或新版 README 到 GitHub。G6.2 已上线的开发文档不受本轮未提交状态影响。

尚未进行的项目：

- 新版 README 的 GitHub 线上实际渲染与图片浏览：NOT_VERIFIED，留待获准提交/推送后检查。
- 新克隆安装、真实模型、容器健康和长期稳定性：未在本轮执行，沿用各自历史验收范围，不扩充结论。
- 不对原始历史材料作新的公开分发，不将旧阶段文档中的阶段截止状态当成当前部署状态。

当前工作完成后停止，不自动提交、推送或进入下一阶段。
