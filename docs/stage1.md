# Stage 1：项目初始化与基础架构

本Stage是开发历程专题，不是历史Git版本。所有运行结论均带证据范围，本轮不执行业务验收。

## 1. 阶段目标

建立可启动、可配置、可演示的前后端分离骨架，为后续文档、问答与用户隔离提供共同入口。实际以M1为起点，M4继续补齐认证、迁移和部署基础；不是一次性完成所有能力。

## 2. 技术与依赖

Python/FastAPI、Pydantic Settings、SQLAlchemy/Alembic；Vue 3、TypeScript、Vite和Element Plus。正式关系存储为PostgreSQL，SQLite只是本地便利/离线替代；两者的验证结果分开。

## 3. 实现内容

采用应用工厂与lifespan管理配置、关系连接和资源释放；统一成功响应与安全异常；按api/core/models/services/rag分层。前端通过相对API路径访问后端。服务约束为单实例、单worker，不引入额外消息中间件。

## 4. 核心代码位置

| 代码 | 职责 |
|---|---|
| [factory.py](../backend/app/factory.py) | 应用组装、生命周期、统一异常边界 |
| [配置](../backend/app/core/config.py) | 环境变量与运行模式 |
| [数据库](../backend/app/core/db.py) | SQLAlchemy引擎和会话 |
| [初始迁移](../backend/migrations/versions/001_initial.py) | 冻结业务表结构 |
| [前端入口](../frontend/src/main.ts) / [路由](../frontend/src/router/index.ts) | Vue挂载及页面导航 |

## 5. 关键实现流程

根.env/进程配置 → 创建FastAPI应用 → lifespan准备存储与连接 → 注册路由 → 前端通过API交互。开发脚本先执行Alembic再启动Uvicorn；create_all的便利行为不能替代升级迁移。

## 6. 测试与验证结果

M1阶段记录CRUD、参数/隔离及OpenAPI等3项检查与前端构建通过；后续H01的26离线+2设施是演进后的汇总，不能再加一次早期数量。本轮不启动应用、不执行迁移。当前覆盖定义见[test_m1.py](../backend/tests/test_m1.py)。

## 7. 遇到的问题及解决方案

配置相对路径和平台依赖容易混淆：普通应用固定读取项目根.env，真实运行入口另有安全加载机制；安装从实际克隆根目录开始。供应商/数据库原异常通过安全错误边界分类，不能把连接成功或依赖安装当作真实RAG通过。

## 8. 阶段成果

获得统一配置、接口、ORM、迁移和前端入口。没有建立SSO、高可用队列或多worker共享Milvus能力；默认Mock不意味着完整离线语义模型。

## 9. 对应真实开发证据

[开发历程](development-history.md)H01；[系统测试摘要](final-delivery/SYSTEM_TEST_REPORT.md)的离线/设施区分；[系统架构](ARCHITECTURE.md)。当前源码是最终实现，不能据此恢复当年M1的完整历史树。

[返回计划](development-plan.md) · [查看实际历程](development-history.md)
