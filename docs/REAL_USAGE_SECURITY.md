> 当前修订（2026-11-18）：R2已增加显式infrastructure模式，不读取/挂载/注入模型Key，模型操作统一拒绝。
> 最新入口与待审批材料见无密钥R2部署方案（本地专用材料，不随发布源码分发）及新审批（本地专用材料，不随发布源码分发）。
> 旧R1正文保留作历史说明，其旧摘要不能用于当前修改后制品；不要直接执行下方旧真实模式命令。
> real实现与费用保护保留，但需匹配当前代码的新real审批；本轮没有部署、数据库或付费操作。

> GitHub副本说明：标为“本地专用”的原始证据未纳入Git，不是可下载附件。分类及存在性见[本地材料索引](LOCAL_EVIDENCE_INDEX.md)；不复制原始审计或用户数据来补齐链接。

# R1 真实使用安全与费用控制

状态：实现和离线验证完成；保护代码尚未部署。本轮真实请求0、历史真实请求仍6；
没有读取真实API Key、Docker操作或真实数据库连接。

## 1. 密钥边界

[运行入口](../scripts/real_usage_runtime.py)复用原[安全加载函数](../scripts/real_rag_acceptance.py)：
非空进程DASHSCOPE_API_KEY优先；其次显式dotenv文件；最后兼容原raw key-file。
dotenv使用`dotenv_values(..., interpolate=False)`，不把值写回os.environ、不修改全局环境。

独立Compose不给后端直接设置DASHSCOPE_API_KEY，只把已有`backend/.env`只读挂到`/run/secrets/model.env`，
新后端启动才安全加载；本轮只检查文件是否存在。
Qwen和Embedding共用服务端Key，前端没有模型鉴权参数、密钥挂载或直连云服务能力。
API响应沿用安全错误结构，不回传Key和外部原始异常。

PG密码、JWT密钥使用新专用文件，生成脚本默认不执行生成分支；存在即阻断，不覆盖。
数据库URL在内存中用SQLAlchemy URL构造，防止密码特殊字符破坏格式；不打印URL。
未来首次部署必须验证secret文件权限与只读挂载实际生效，本轮NOT_VERIFIED。
Windows文件模式0600不代表ACL配置已经验证。

Git忽略`.env`、`.env.*`、`data/`等；只放行不含真实值的.env.example。
根和前端构建上下文均排除.env/.env.*，原backend/.dockerignore已排除。
新后端Dockerfile仅COPY程序/迁移/公开审批制品，前端镜像不接收后端目录。
这些是源码与离线验证结论，实际镜像内容审计仍待授权构建后完成。

## 2. 本地访问与用户隔离

- 新前端只绑定127.0.0.1:8081；后端/PG没有宿主端口。
- 新Compose项目默认网络，不加入8080项目网络，也不使用共享external网络。
- PG实例/数据库、Milvus和上传目录、审计卷全部独立；不借用演示数据库或schema。
- 沿用密码哈希、JWT认证和user_id所有权检查；收费入口先验证KB/会话所有权，再登记操作。
- 真实新应用单进程单worker；不得横向扩容，否则进程锁的频率/并发语义不成立。
- 仅回环HTTP适用于可信本机，不是公网生产HTTPS方案；本轮未配置TLS、MFA、管理员审批界面或云端防火墙。

原prompt仍将文档视为不可信证据，沿用真实页码与引用校验；
没有更改RAG排序、引用生成、消息保存或原六张业务表。
提示词防护不能证明对所有提示注入均有效，不能作安全绝对承诺。

## 3. 模型门禁实际范围

实现：[config.py](../backend/app/real_usage/config.py)、
[guard.py](../backend/app/real_usage/guard.py)、
[models.py](../backend/app/real_usage/models.py)、
[application.py](../backend/app/real_usage/application.py)。

| 项目 | 实际实现 |
|---|---|
| 配置 | 只允许北京兼容接口、qwen-plus非思考、text-embedding-v4/1024、独立PG/存储路径 |
| 启动审批 | ID、清单SHA和运行制品哈希先核对；实际limits必须逐项匹配 |
| 输入 | 单请求按UTF-8估算；聊天额外256封装余量；首次4096上限，超过发送前422 |
| 输出 | Qwen max_tokens=256、enable_thinking=false、stream=false |
| 批量Embedding | 每批≤10条，估算总量≤输入上限；先校验所有单片段，过长不发送 |
| 大小/分块 | 20MiB文件、最多32片段；分块数超限在Embedding前拒绝 |
| 模型频率 | 滚动60秒最多6次，读取持久账本；不是所有HTTP接口限流 |
| 并发 | 模型调用单并发、付费业务操作单并发，拒绝等待；非全系统写接口互斥 |
| 防重 | 用户/资源/操作/内容摘要做HMAC，300秒内相同提交409；不保存全文指纹原料 |
| 覆盖入口 | 文档上传后台索引、独立search、发送会话消息的Embedding/Qwen都经注入模型 |
| 超时/重试 | HTTPX超时30秒，HTTPTransport retries=0、trust_env=False、不跟随重定向；无SDK重试 |
| 次数/预算 | 首次R1合计3次、UTC每日60次、日估算¥0.01，持久化不随重启清零 |
| 使用量 | 记录服务端usage的输入/输出；缺失/超限/异常完成立即全局暂停 |

30秒是HTTPX各网络阶段超时配置，不承诺请求从排队到完成的绝对总时长≤30秒；
后端单操作门禁拒绝并行。浏览器超时不等于云端请求未执行，禁止自动重发。
单请求模型类型约束已实现，但首次合计3次不是各类型分别2/1的硬限额。

限额先持久化预留，再进行网络发送；进程在发送前崩溃也可能占一次，
所以账本`reserved_attempts`是保守尝试上界，不能直接当作真实发出的精确请求数。
发出后失败/超时/结果未知也保留次数和预留，不退费、不自动重试。
成功时保留原保守预留与实际估算中的较大值，实际usage单独保存。

日预算使用UTC日期；并非用户本地零点。R1累计3次不会在日切时恢复。
历史基线6不计入新3次额度，但始终保留；新累计尝试上界=6+R1预留次数。
旧脚本记录不修改，其他客户端/API Key上的调用不在R1本地账本内。
云价格、计费口径、Tokenizer、网络不确定性及其他客户端都可能造成差异；
应用层保护不能保证整个账号账单绝不超限。建议另在云控制台设置适当预算告警，
本轮未检查或修改任何云端账号配置。

## 4. 失败、重启与人工处置

模型HTTP错误、超时、无usage、usage超限、回答finish_reason不完整或输出校验失败，
会记录UNKNOWN/暂停原因，当前操作失败并阻断后续真实请求。
审计不可写也阻断；计数持久化失败不继续发下一请求。
启动遇RUNNING操作或SENT_UNCERTAIN调用时转FAILED/UNKNOWN并暂停，不自动重做。
文档解析/索引失败仍由原业务服务记录failed和安全error_code。

前端只新增安全错误码的中文提示：
USAGE_STOPPED、USAGE_LIMIT、USAGE_RATE_LIMIT、USAGE_BUSY、DUPLICATE_REQUEST、
TOKEN_LIMIT、USAGE_STORAGE、DOCUMENT_LIMIT。
原API结构不变，不显示原始堆栈；8080未重建，当前新增提示尚未上线。

后续授权后可在新后端执行`python /opt/rag/scripts/real_usage_runtime.py status`，
仅查询安全聚合计数，不输出API Key；该命令仍核对审批、只读新数据库。
本轮没有执行容器命令，真实PG上的管理分支NOT_RUN。

只有人工核对请求、云usage、数据库/文档状态后，另行允许`ack-stop --acknowledge-uncertain-charges`。
该操作不清空计数、UNKNOWN预留、重复指纹，也不扩大上限。
有RUNNING或SENT_UNCERTAIN时仍拒绝；重启恢复规则必须先正确执行。
人工解除暂停不构成重新提交付费请求的许可。

禁止删除账本、换数据库、恢复更旧快照、改审批ID以重新获取额度。
备份恢复必须保持或对齐最新已发尝试记录；不可把旧快照中的较低计数当成新额度。
R1不实现跨多个应用实例的分布式锁，也不提供自动计费对账或自动恢复工具。

## 5. 日志与数据保护

模型审计只记录call_id、模型类型、时间、Token计数、估算预留及安全事件，
不写原文、问题、答案、Header、URL密码或Key。
HMAC操作指纹不是可还原的文档全文，JWT密钥也不写指纹表。
新后端关闭Uvicorn访问日志，生命周期异常只给固定安全码；
前端Nginx沿用默认访问日志，不记录请求正文和Authorization Header，
仍可能包含资源路径/ID；新容器日志不和原演示日志混用。
文件名/资源ID也应按私人数据管理，不把真实业务日志上传到交付材料。

日志轮转、磁盘容量告警、审计归档计划、备份加密和Windows ACL尚未落地验证。
本轮不为了消除待办修改宿主机或Docker系统配置。
PG业务表与Milvus/上传卷包含文档和会话正文，属于用户私有数据，
不能因为审计脱敏就宣称所有持久化数据没有敏感信息。

备份工具不会自动加密/解包/删除；`credential_files_included=false`表示方案未挂载凭据文件，
不代表文档中没有用户自行上传的秘密，也不是归档内容DLP证明。
离线tar检查拒绝绝对路径、..、盘符、软/硬链接及特殊设备，SHA-256验证防止不一致；
它不能证明实际数据库可恢复。详见部署与备份（本地专用材料，不随发布源码分发）。

## 6. 本轮验证与未验证

30个不同离线案例最终PASS；仅使用虚构凭据、MockTransport和专用SQLite/文件夹。
HTTPTransport真实网络发送在离线测试中被阻断，子进程使用白名单环境；
不导入默认ASGI app读取真实.env。TypeScript类型检查PASS，没有重跑旧业务PASS或真实验收。

PASS范围：真实模式设置、Key缺失、持久计数、限额/Token/并发/频率、防重/所有权、
超时暂停、Mock上传问答与引用、failed索引、原Mock默认、PG DDL及备份路径/哈希。
实际Key有效性/容器UID读取、R1新PG迁移、Milvus卷持久化、镜像、启动、实际恢复均未验证。
这些必须在后续授权范围内逐步记录，不能借M5旧真实PASS填成R1真实PASS。

定价依据（2026-11-18核对，仅公开文档）：
[Qwen北京价格](https://help.aliyun.com/zh/model-studio/qwen-plus)、
[Embedding规格/价格](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)。
审批信息见REAL_USAGE_APPROVAL.md（本地专用材料，不随发布源码分发）。
