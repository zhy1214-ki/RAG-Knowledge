# 环境、安装与部署说明

> GitHub副本说明：标为“本地专用”的原始证据未纳入Git，不是可下载附件。分类及存在性见[本地材料索引](../LOCAL_EVIDENCE_INDEX.md)；不复制原始审计或用户数据来补齐链接。

本文件是操作说明，不是M7执行记录。本轮没有运行Docker、安装、迁移、启动或健康探针。
现有8080版本状态来自2026-11-18 M6.6快照；现场存活与网络状态在M7为NOT_VERIFIED。

本页保留M7/M6.6历史快照。现有布局区分8080 Mock与独立8081真实环境，后者审批和密钥材料不分发；新副本的当前入门步骤见[根README](../../README.md)。

## 1. 环境基线

- 历史Windows验收使用项目内Python3.12.16，系统原Python没有被替换。
- 前端Dockerfile使用node:24-alpine，本地开发推荐与之对应的Node24系列。
- 后端python:3.12-slim，安装libgomp1并以非root用户运行；只支持本项目单实例单worker方案。
- PostgreSQL镜像postgres:16-alpine，Nginx镜像nginx:1.28-alpine。
- Milvus Lite固定3.2.2与pymilvus3.0.2；当前Windows及Linux容器组合有历史PASS，
  不扩展承诺其他架构或版本均兼容。

精确Python/Node库版本由requirements.lock.txt和package-lock.json规定。
跨数据库迁移旧业务数据并未自动实现，SQLite只用于本地便利模式和离线测试。

## 2. 配置加载机制

仅列项名和非敏感行为，不提供任何凭据值、数据库密码或认证请求。

| 配置项 | 用途 |
|---|---|
| DATABASE_URL | SQLAlchemy连接；敏感值不展示 |
| JWT_SECRET | JWT签名材料；敏感值不展示 |
| POSTGRES_PASSWORD | Compose初始化PostgreSQL及插值连接配置；不展示值 |
| MODEL_BACKEND | mock或qwen；现演示mock |
| ALLOW_PAID_MODELS | 真实模型显式开关；现演示false |
| DASHSCOPE_API_KEY | 真实模型凭据；当前文档不读取或展示 |
| QWEN_BASE_URL / QWEN_MODEL | 兼容接口地域与模型名称；默认北京接口、qwen-plus |
| EMBEDDING_MODEL / EMBEDDING_DIMENSION | text-embedding-v4 / 固定1024 |
| VECTOR_BACKEND / VECTOR_URI | milvus及本地持久化位置；勿用SDK保留名MILVUS_URI |
| STORAGE_DIR / MAX_UPLOAD_BYTES | 上传目录和默认20MiB上限 |
| CHUNK_SIZE / CHUNK_OVERLAP / MIN_SCORE | 默认384 / 48 / 0.2 |
| TOKEN_HOURS / CORS_ORIGINS | 默认12小时及两个本地5173来源 |

普通Settings用pydantic-settings：
显式构造参数优先于进程环境，再是配置模块ROOT/.env，最后是代码默认值。
在当前源码目录ROOT为项目根，backend/.env不是普通应用自动加载路径。
在后端镜像/app/app/core/config.py位置按同一parents[3]计算ROOT为/；
容器配置实际通过Compose environment提供，不依赖将宿主.env打入镜像。

Compose读取项目根.env用于插值；没有给backend配置env_file。
受控真实验收脚本另有安全入口：非空进程环境优先，再显式--key-env-file，
再兼容--key-file；dotenv_values关闭插值，选定文件出错立即阻断，不写全局环境。
这不意味着普通应用会自动读取backend/.env，也不是本轮允许切换真实模式。
配置的具体值和文件内容不要发到浏览器、终端报告或毕业材料。

## 3. 全新副本安装说明（本轮不执行）

只适用于获准的新环境，不应用于现有8080演示资源。

```powershell
# 在实际新克隆的仓库根目录执行，无固定盘符要求
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock.txt
npm --prefix frontend ci
```

仅当目标.env不存在时，才从.env.example另建本地配置，并在本机安全填写必要项；
不要覆盖已有.env或输出其内容。提供的示例不是生产凭据。
本轮没有执行上述依赖安装、配置复制或凭据生成。

本机开发脚本分别为scripts/start-backend.ps1和scripts/start-frontend.ps1，
后端脚本先执行Alembic再启动Uvicorn，前端Vite默认5173；
开发API文档在8000/docs。脚本只在另外授权的新/开发环境使用。

全新Compose副本使用docker-compose.yml构建三个服务，启动顺序为PostgreSQL健康→后端→前端。
后端Dockerfile先alembic upgrade head再启动Uvicorn。
此处仅说明设计，不要求在当前演示机重新运行全量compose up --build。

## 4. 当前8080部署快照

| 项目 | M6.6已保存记录 |
|---|---|
| 项目/前端容器 | rag-knowledge / rag-knowledge-frontend-1 |
| 前端镜像标签 | rag-knowledge-frontend:m65-20261118-161701-b87c0573 |
| 前端镜像ID | sha256:f2f098f592559264b4df937c21f590f3d986ef178ccc7c7c867ff3fb5bc14181 |
| 入口资源 | index-BSiAg2dc.js / index-_pqpYkm2.css |
| 端口 | 127.0.0.1:8080→80，仅本机 |
| 后端 | backend:8000，未映射宿主端口 |
| 关系库 | postgres:5432，未映射宿主端口 |
| 网络 | rag-knowledge_default |
| 卷 | rag-knowledge_app_data与rag-knowledge_postgres_data |
| 模型 | mock；向量后端milvus |
| backend/PostgreSQL重启 | M6.6前后身份/启动时间/重启数保持 |
| 回滚 | 未发生，旧镜像/回滚标签/归档保留 |

Milvus Lite在后端环境内；没有第四个Milvus容器。
当前固定版本存储为目录式，.db后缀不可当成单文件路径类型断言。
禁止多worker同时共享这一本地持久化；不建议擅自修改Docker或WSL配置。

## 5. 保持当前新版的管理方式（仅记录，不执行）

M6.6保留旧rag-knowledge-frontend:latest，新版使用独立版本标签。
后续经授权管理frontend时，应带已保留的候选覆盖文件：

```powershell
# 历史维护依赖本地私有candidate.compose.yml；请先独立核验覆盖文件和授权，不从Git克隆直接执行。
```

这不是M7实际操作。不能在当前环境只用原compose up来“验证文档”，
否则可能选择旧latest或扩大变更范围。
新部署应先核验制品、做可校验备份、只替换frontend，流程见
M6.5方案（本地专用材料，不随发布源码分发）及M6.6结果（本地专用材料，不随发布源码分发）。

## 6. 备份、恢复与维护边界

M6.6旧前端归档frontend-before.tar为26,417,152字节，
SHA-256为38eae4ecd6a7bac5c34179cac88876d91774311e2037575aa07aa70d63406a66，
路径位于data/frontend-deploy/m65-20261118-161701-b87c0573/。
回滚标签为rag-knowledge-frontend:rollback-m65-20261118-161701-b87c0573。
这是镜像备份，不是数据库备份；真实回滚演练NOT_RUN。

数据保存在两个命名卷。任何业务备份需另外授权、停止写入并一致处理关系库/向量/文件，
不能只复制一个.db文件后宣称可以完整恢复。M7不读取数据卷、不导出数据库、不清理资源。
不要把docker compose down -v或镜像清理当成日常演示步骤。

后台任务重启不会续跑，会标记PROCESS_INTERRUPTED；deleting失败需维护者确认后重试。
当前无TLS、SSO、高可用或限流部署；远程发布、证书、生产监控与灾备均未验证。

## 7. 验收与敏感材料

当前版本生效证据是镜像身份+index/11资源SHA/MIME+六页Mock浏览器，
不是仅凭标题或截图。M7复用这些历史结果，不重新测试。
不分发.env、真实凭据、完整认证请求、原始内部日志或数据卷；
SOURCE_INDEX只包含允许公开的源码/审计路径与哈希，不含配置值。

本次文档交付没有新的部署工作；需要更多环境验证时须另定范围。