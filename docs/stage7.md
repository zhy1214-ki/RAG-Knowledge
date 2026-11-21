# Stage 7：Docker真实环境部署、费用控制与运行安全

本Stage是开发历程专题，不是历史Git版本。运行结论来自限定范围的既有记录，本轮不执行验收。

## 1. 阶段目标

保留8080 Mock演示，同时建立独立8081运行环境，并为日常真实调用提供持久化额度、失败停止及可信时间保护。对应M4部署基础与R1～R4.5.7的连续完善。

## 2. 技术与依赖

Docker Compose、PostgreSQL、Milvus Lite本地持久化、SQLAlchemy事务/行锁、HTTPX无重试客户端及单worker进程锁。没有独立Milvus服务集群、分布式任务平台或远端工作流中间件。

## 3. 实现内容

8081独立后端、前端入口、关系数据卷、上传/向量卷和审计卷，默认本机绑定。infrastructure不加载真实Key、不创建真实模型客户端，所有模型入口拒绝；real必须通过模式、地域、配置、审批和费用门禁。六张业务表之外，独立运行增加GuardState、ModelCall、Operation三类持久化表。

## 4. 核心代码位置

| 代码 | 职责 |
|---|---|
| [模式配置](../backend/app/real_usage/config.py) / [应用包装](../backend/app/real_usage/application.py) | 配置隔离与受保护API |
| [guard.py](../backend/app/real_usage/guard.py) | 费用预留、并发、防重、UTC/epoch和暂停 |
| [GuardedModels](../backend/app/real_usage/models.py) | 超时、输出上限、重试0及输入分批 |
| [运行入口](../scripts/real_usage_runtime.py) | 安全加载、审批核验与管理入口 |
| [设施Compose](../deploy/real-usage/compose.infrastructure.yml) / [限频覆盖](../deploy/real-usage/compose.r42-rate5.yml) | 独立资源与5次/分钟配置 |
| [增量迁移](../backend/real_usage_migrations/versions/r4_002_clock.py) | 时间高水位和epoch两列 |
| [连续性预检](../scripts/clock_continuity_preflight.py) / [备份](../scripts/real_usage_backup.py) | 失败前证据与隔离备份 |

## 5. 关键实现流程

受保护业务入口取得操作指纹 → 检查暂停和UTC时间 → PostgreSQL锁住唯一GuardState行 → 检查日/月预算、总量、类型、滚动60秒频率 → 持久化SENT_UNCERTAIN和保守费用 → 单次HTTP → 验证usage后VERIFIED。失败、超时或用量不确定转UNKNOWN并暂停，不退款、不自动重发。SQLite离线替代使用BEGIN IMMEDIATE，不能当成真实PostgreSQL锁证据。

## 6. 测试与验证结果

H06记录R2.2真实PostgreSQL/Milvus/上传持久化和独立恢复PASS，测试向量为本地虚构；H08记录53项离线、12组真实PostgreSQL门禁，以及61项时钟修复；H09记录Epoch 88项、预检31项和后续独立部署/恢复。它们是不同范围和不同轮次，不能简单求和。本轮不执行上述测试。

## 7. 遇到的问题及解决方案

早期启动器强制真实Key，后来以明确infrastructure模式解决，不能缺Key自动降级。时钟误判先修复墙钟/单调采样错位，再修复新epoch接管时同样本比较；首次合法接管只建锚，后续继续检查。独立预检器用整数纳秒并在断言前持久化/回读样本，生产guard仍保留真实回拨、60秒异常漂移及跨UTC日重启人工复核。没有通过扩大固定阈值或清账来消除错误。

## 8. 阶段成果

历史日常授权参数为日估算0.10元/月3元、日60次、分钟5次、单并发1、输入估算4096/输出256、自动重试0。它们不是新克隆默认值或本次授权；示例/旧文档中的早期限额不能直接当作当前生效值。估算按输入字节等保守方式预留，不等于精确Tokenizer；也不保证云账单绝不超限。原运行数据和审批不分发。

## 9. 对应真实开发证据

[开发历程](development-history.md)H06、H08、H09；[预算政策历史快照](R4_BUDGET_POLICY.md)、[运行安全](REAL_USAGE_SECURITY.md)、[费用测试](../tests/real_usage/test_r4_budget.py)、[Epoch回归](../tests/real_usage/test_r453_epoch.py)、[预检回归](../tests/clock_preflight/test_r456_continuity.py)。人工确认须另外授权，历史连续性不能补证的部分仍为NOT_VERIFIED。

[返回计划](development-plan.md) · [查看实际历程](development-history.md)
