# 部署和维护

> GitHub副本说明：标为“本地专用”的原始证据未纳入Git，不是可下载附件。分类及存在性见[本地材料索引](LOCAL_EVIDENCE_INDEX.md)；不复制原始审计或用户数据来补齐链接。

> M7整理说明：现有8080新版以M6.6结果（本地专用材料，不随发布源码分发）及[当前部署指南](final-delivery/DEPLOYMENT_GUIDE.md)为准。下述安装/维护命令只是说明，本轮没有执行。

8080为Mock演示入口；8081为独立真实环境，不能用根Compose接管。新克隆及当前发布边界见[发布说明](GITHUB_RELEASE_NOTES.md)。本页M6.6镜像/运行信息属于历史快照，不是本轮现场状态。

## 启动

以下全量启动说明仅适用于获准的全新副本：在根目录运行 docker compose up --build -d，访问 http://127.0.0.1:8080。现有M6.6演示环境须使用保留的candidate.compose.yml，不应按此重新启动全服务。
只公开本机 Nginx，PostgreSQL 处于 Compose 内部网络。
注册自己的用户，无内置管理员口令。
后端以非 root 单 worker 启动，先执行 Alembic upgrade head。
依赖 PostgreSQL 健康后启动后端，再启动 Nginx。
默认Mock，现有演示不调用付费模型。真实后端与M5浏览器单文单问历史验收已PASS，当时累计6次；后续R4.6历史验收边界见GITHUB_RELEASE_NOTES.md，均不构成再次调用授权。

全新副本必须自行从.env.example创建本地.env并设置随机JWT与数据库密码；Git中不提供预配置秘密，勿打印或提交。
Compose 中密码建议随机字母数字；直接 DATABASE_URL 的特殊字符需要 URL 编码。
项目没有修改宿主 Docker、WSL 或网络设置。

## 数据

app_data 保存上传与 Milvus 文件，postgres_data 保存关系数据。
docker compose stop 停止并保留数据。
不要对含有效资料的卷执行删除；备份前暂停写入，同时备份关系库、向量与文件。
SQLite 仅本地便利模式，切换 PostgreSQL 不会自动迁移数据。
开发脚本总是从根目录运行；相对路径以根目录为准。
使用 VECTOR_URI，不使用 SDK 保留的 MILVUS_URI。

## 恢复

单实例、单worker使用Milvus Lite本地持久化，固定3.2.2已验证为目录式存储；禁止多进程共享。
BackgroundTasks 不持久化任务队列，重启会把处理中断标记 failed。
删除失败状态为 deleting，恢复向量库后再次 DELETE。
数据库不可用时可能无法写失败状态，恢复数据库并重启后会修复中断状态。
扫描 PDF 无 OCR，需预先转换成含文本格式。
历史来源快照随会话/知识库删除，文档删除本身不抹除历史。

## 真实模型

获得独立授权后再设置 MODEL_BACKEND=qwen、ALLOW_PAID_MODELS=true 和 Key。
Base URL 与 Key 匹配地域，模型为 qwen-plus、text-embedding-v4 / 1024。
切换模式后新建知识库并重新上传；不自动重建旧索引、不静默回退。
Qwen兼容适配既有离线替身测试，也有真实后端及M5浏览器单文单问PASS；当前新版UI直接证据为M6.6 Mock交互，不扩大为新一轮真实验收。

## V1 边界

演示规模；无 OCR、SSO、角色权限、密码找回、限流或高可用任务队列。
前端主包会有 Vite 大包提示，构建通过，未为此增加不必要依赖。
M6起回答使用markdown-it禁用原始HTML，再由DOMPurify净化后通过v-html展示；来源正文使用Vue文本插值，不按HTML执行。
本地令牌存 sessionStorage；远程正式部署应自行配置 HTTPS 与相应访问控制。
