# Stage 2：用户认证与知识库管理

本Stage是开发历程专题，不是历史Git版本。所有运行结论均带证据范围，本轮不执行业务验收。

## 1. 阶段目标

让用户只访问自己的知识库、文档和会话。知识库CRUD始于M1，用户注册/JWT与基础隔离在M4完善；本Stage把相关设计集中说明。

## 2. 技术与依赖

FastAPI依赖注入、SQLAlchemy查询、scrypt密码哈希和PyJWT。前端Pinia/sessionStorage负责登录态展示，真正的授权依据仍在后端。

## 3. 实现内容

注册保存随机盐与scrypt摘要；登录用恒定成本哈希及恒定时间比较验证，签发HS256令牌。KnowledgeBase的owner_id/name联合唯一；文档先检查知识库归属，会话还检查owner与知识库。越权资源返回统一404。

## 4. 核心代码位置

| 代码 | 职责 |
|---|---|
| [base.py](../backend/app/api/base.py) | 注册、登录、用户信息和知识库CRUD |
| [deps.py](../backend/app/api/deps.py) | current_user与资源所有权依赖 |
| [业务模型](../backend/app/models/__init__.py) | 用户、知识库、外键和唯一约束 |
| [前端认证状态](../frontend/src/stores/auth.ts) | 本地登录态 |
| [知识库页面](../frontend/src/views/Knowledge.vue) | 列表、创建、编辑与删除交互 |

## 5. 关键实现流程

注册/登录 → 校验令牌并获取用户 → 用owner_id限定知识库查询 → 验证下属文档/会话 → 提交独立事务。删除知识库先逐文档清理文件和向量，再删除关系记录及级联会话。

## 6. 测试与验证结果

H01包含注册登录、凭据不返回、跨用户资源拒绝、重复名称及级联清理的历史PASS。定义见[test_m1.py](../backend/tests/test_m1.py)、[test_security.py](../backend/tests/test_security.py)与[test_m3.py](../backend/tests/test_m3.py)；这些文件不是本轮新执行结果。

## 7. 遇到的问题及解决方案

前端隐藏按钮不足以隔离数据，因此查询条件绑定实际用户和知识库；数据库唯一约束冲突回滚并返回安全错误。知识库删除也涉及外部向量/文件，不能只依赖关系库级联。令牌放在sessionStorage不等同于SSO或全面浏览器安全认证。

## 8. 阶段成果

形成基础多用户隔离与知识库CRUD，保留最小权限边界。未实现通用角色、密码找回或第三方身份系统；JWT与数据库秘密必须由本地安全配置提供，不使用模板占位上线。

## 9. 对应真实开发证据

[开发历程](development-history.md)H01和H04；[数据库设计](final-delivery/DATABASE_DESIGN.md)；[API说明](API.md)。不公开测试用户名、密码、实际资源ID或认证请求。

[返回计划](development-plan.md) · [查看实际历程](development-history.md)
