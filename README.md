# 知序 · RAG-Knowledge V1.0

基于文档检索增强生成（RAG）的个人知识库问答系统。支持注册登录、用户隔离、知识库管理、PDF/DOCX/TXT/Markdown上传、处理进度、带来源引用的问答及会话历史。

- 前端：Vue 3、TypeScript、Vite、Element Plus。
- 后端：Python、FastAPI、Pydantic Settings、SQLAlchemy、Alembic。
- 数据与RAG：PostgreSQL、Milvus Lite、LlamaIndex分块、PyMuPDF、python-docx。
- 外部模型：Qwen Plus、text-embedding-v4，向量维度1024。

默认采用Mock Embedding和Mock回答，不需要模型API Key。Mock通过只证明接口和流程，不代表真实模型效果。

## 开发文档

八个Stage是按实际功能归纳的专题，不代表历史存在同名Git版本。先读[开发计划](docs/development-plan.md)、[系统架构](docs/ARCHITECTURE.md)与[实际开发历程](docs/development-history.md)。

| 阶段 | 文档 |
|---|---|
| 1 | [初始化与基础架构](docs/stage1.md) |
| 2 | [用户认证与知识库](docs/stage2.md) |
| 3 | [文档上传、解析与切分](docs/stage3.md) |
| 4 | [Embedding与Milvus检索](docs/stage4.md) |
| 5 | [Qwen RAG、引用与历史](docs/stage5.md) |
| 6 | [Vue前端与UI优化](docs/stage6.md) |
| 7 | [Docker部署、费用与运行安全](docs/stage7.md) |
| 8 | [真实验收与V1.0发布](docs/stage8.md) |

维护者说明仓库现为Public；首次上传阶段的Private记录属于历史状态。本轮只整理公开文档，未联网核验或改变可见性。以下新增文档尚未提交/推送，不代表GitHub页面已更新；运行秘密、账号与原始审计继续排除。

## 版本与验收边界

本目录是独立脱敏的V1.0源码发布副本，使用全新本地Git历史；不复制原始提交、标签或归档。详见[发布说明](docs/GITHUB_RELEASE_NOTES.md)。

已有真实后端、M5真实浏览器及R4.6真实链路PASS记录，已知范围与证据边界见[发布说明](docs/GITHUB_RELEASE_NOTES.md)；本次没有重跑验收或查询账本。M6界面优化见[M6说明](docs/M6_UI.md)。原始验收、进度、截图和运行审计仅保留本地，详见[本地材料索引](docs/LOCAL_EVIDENCE_INDEX.md)，不随源码上传。

| 既有环境 | 用途 | 发布边界 |
|---|---|---|
| 127.0.0.1:8080 | Mock演示，六页UI及无付费流程 | 根Compose的默认新副本入口 |
| 127.0.0.1:8081 | 独立真实RAG环境，曾经历infrastructure/real受控切换 | 独立PostgreSQL、Milvus、上传和审计卷；需要本地审批材料 |

上述为已验收部署布局，不代表本次进行了健康检查。新克隆不会继承任何环境、账号、模型额度或运行数据。不要用全量启动命令更新现有8080/8081服务。

## 全新副本安装

推荐Python 3.12、Node.js 24。Python依赖锁定在[requirements.lock.txt](backend/requirements.lock.txt)，前端锁定在[package-lock.json](frontend/package-lock.json)。Milvus Lite要求兼容的本地运行环境；历史平台通过不保证所有系统均兼容。

以下PowerShell命令均在新克隆的仓库根目录执行，路径由实际克隆位置决定。创建虚拟环境、安装、迁移和启动只用于用户批准的新环境；本次文档整改没有执行它们。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock.txt
npm --prefix frontend ci
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
```

在本机编辑[.env.example](.env.example)复制出的`.env`：将`JWT_SECRET`、`POSTGRES_PASSWORD`替换为独立的随机长值，不使用模板占位符，不打印或提交凭据。保持`MODEL_BACKEND=mock`、`ALLOW_PAID_MODELS=false`及空`DASHSCOPE_API_KEY`。

本地便利模式默认使用SQLite，数据写入`data/`；SQLite测试不能代替PostgreSQL验收。普通应用从项目根`.env`读取设置，进程环境优先；它不会自动读取`backend/.env`。

两个独立终端，均从仓库根目录运行：

```powershell
# 后端脚本先执行应用迁移，再启动单worker服务
.\scripts\start-backend.ps1
```

```powershell
.\scripts\start-frontend.ps1
```

访问`http://127.0.0.1:5173`，自行注册账号；接口文档为`http://127.0.0.1:8000/docs`，没有默认管理员口令。8000/5173必须可用，不停止不属于本次新环境的进程。

## PostgreSQL与Docker新副本

根[docker-compose.yml](docker-compose.yml)提供PostgreSQL 16、单worker后端和Nginx前端。准备好根`.env`中的随机秘密后，仅在批准的新副本且8080空闲时运行：

```powershell
docker compose up --build -d
docker compose ps
```

默认Web入口为`http://127.0.0.1:8080`，PostgreSQL不发布宿主端口；上传及Milvus保存在`app_data`，关系库保存在`postgres_data`。停止时使用`docker compose stop`保留数据，不运行`down -v`。现有部署维护及备份边界见[部署说明](docs/DEPLOYMENT.md)。

## 使用与来源引用

1. 注册登录，创建知识库。
2. 上传合成[samples/travel-policy.docx](samples/travel-policy.docx)或[samples/travel-policy.pdf](samples/travel-policy.pdf)，等待已索引。
3. 中文文档可问“差旅报销需要多久提交？”，英文PDF可问“travel reimbursement policy”。
4. 查看回答引用的文档、片段和位置。PDF尽可能给真实页码，Word不伪造页码。
5. 从会话历史恢复。删除操作会影响文件/向量/元数据，只对明确允许的数据执行。

TXT/Markdown使用UTF-8；默认单文件20MiB，解析文本上限200万字符。扫描PDF需先OCR，本系统没有OCR。来源文档作为不可信输入，不能作为覆盖系统指令的依据。

## 真实Qwen与Embedding

真实请求可能产生费用，必须单独确认账号、地域、调用范围和预算。普通应用的必要配置为：`MODEL_BACKEND=qwen`、`ALLOW_PAID_MODELS=true`、后端专用`DASHSCOPE_API_KEY`；默认北京兼容端点为`https://dashscope.aliyuncs.com/compatible-mode/v1`，模型为`qwen-plus`和`text-embedding-v4`/1024维。Key必须与端点地域匹配。

独立8081运行机制另使用只读密钥文件和持久化预算门禁，其审批JSON、密钥和历史账本不包含在Git中。`backend/.env`只由相应安全入口读取；完整机制见[真实环境架构](docs/REAL_USAGE_ARCHITECTURE.md)和[预算策略](docs/R4_BUDGET_POLICY.md)。模板占位符不构成新环境或付费授权，不能复用历史审批。

真实模型失败不会静默回退Mock。Mock/Qwen使用不同Milvus集合；新环境切换模式时按受控方案建立相应索引，不将旧元数据当作新模式的有效向量，也不因此删除已有数据。配置名为`VECTOR_URI`，勿误用SDK保留名`MILVUS_URI`。

## 验证与运行限制

仅在相关代码变化且范围已批准时运行测试，不重复已有PASS：

```powershell
# 离线API和业务测试；不依赖外部模型
.\.venv\Scripts\python.exe -m pytest -c backend\pytest.ini backend\tests -m "not infrastructure" -q
npm --prefix frontend run build
# 独立合成API场景；不转发现有服务
node frontend/scripts/run-m6-ui.mjs regression
```

基础设施测试使用专用资源，另行授权；未配置`TEST_POSTGRES_URL`导致跳过，不能记为通过。详细历史范围见[系统测试报告](docs/final-delivery/SYSTEM_TEST_REPORT.md)，其原始证据路径明确标为本地专用。

Milvus Lite只支持本项目单实例、单worker共享约束；当前版本存储为目录型，不能仅据`.db`后缀判断类型。BackgroundTasks不是持久队列，重启中断任务会标记失败。关系库、向量与文件没有分布式事务，删除失败保留可恢复状态。历史保存来源快照，知识库/会话删除会影响历史。

本项目没有OCR、SSO、通用角色系统或高可用任务队列；普通演示接口没有通用限流。8081独立模型费用门禁不等同于全站安全或云账单绝对上限保证。模型凭据只供后端使用，不进入浏览器。

Git源码不含`.env`、数据库卷、上传文件、用户聊天、原始日志、截图和私有审批。本副本不携带原始Git身份历史；Private仓库仍不能收回他人已克隆内容；发布前必须阅读[隐私与历史说明](docs/GITHUB_PRIVACY.md)。
