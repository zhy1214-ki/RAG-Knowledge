# API V1

> M7整理说明：完整20个应用端点及当前请求/响应模型见[API_REFERENCE](final-delivery/API_REFERENCE.md)；本文件保留简表，不表示本轮重新运行接口。

开发地址 http://127.0.0.1:8000 ，交互文档 /docs，schema /openapi.json。
业务前缀 /api；注册、登录、健康检查之外都需 Authorization: Bearer token。
默认令牌有效 12 小时。用户名 3–64 位字母数字、下划线或短横线，密码 8–128 位。

成功格式：{"code":"OK","message":"成功","data":...}
错误格式：{"code":"VALIDATION_ERROR","message":"请求参数不合法","data":null,"request_id":"随机ID"}
不回显输入、堆栈或凭证；其他用户的资源统一 404。

| 方法 | 路径 | 请求或行为 |
|---|---|---|
| GET | /api/health | 应用模式和状态 |
| POST | /api/auth/register | username, password；201 |
| POST | /api/auth/login | username, password；token 与公开用户信息 |
| GET | /api/auth/me | 当前用户 id, username |
| GET/POST | /api/knowledge-bases | 列表 / 创建（name必填，description可选） |
| GET/PUT/DELETE | /api/knowledge-bases/{kb} | 详情 / 更新基础信息 / 连文档索引会话一起清理 |
| POST | /api/knowledge-bases/{kb}/documents | multipart file；202，后台处理 |
| GET | /api/knowledge-bases/{kb}/documents | 文档列表 |
| GET | /api/knowledge-bases/{kb}/documents/{doc} | status, progress, chunk_count, error_code |
| DELETE | /api/knowledge-bases/{kb}/documents/{doc} | 清向量、文件与元数据；deleting 可重试 |
| POST | /api/knowledge-bases/{kb}/search | question, top_k（1–10，默认5） |
| POST | /api/sessions | knowledge_base_id, title 可选；201 |
| GET | /api/sessions | 当前用户会话列表 |
| GET/DELETE | /api/sessions/{session} | 详情 / 删除及清消息 |
| POST | /api/sessions/{session}/messages | question（1–4000字符）, top_k；assistant 消息 |
| GET | /api/sessions/{session}/messages | 按时间的完整记录 |

引用包含 source_id、chunk_id、document_id、knowledge_base_id、source_name、source_location、text、score。
PDF location 为 {"format":"pdf","page":2}；
Word 为 {"format":"docx","section":"正文"}，无 page。
消息包含 id、session_id、role、content、citations、created_at。
DocumentOut 不暴露磁盘路径。
删除文档后历史引用快照保留；删除会话或知识库可清除。

| code | HTTP | 意义 |
|---|---|---|
| VALIDATION_ERROR | 422 | 参数或空文件 |
| UNSUPPORTED_FILE | 415 | 不支持文件格式 |
| FILE_TOO_LARGE | 413 | 文件超限 |
| PARSE_ERROR | 422 / failed | 解析失败或无文本 |
| DATABASE_ERROR | 503 | 数据库不可用 |
| EMBEDDING_ERROR | 503 / failed | Embedding 失败 |
| VECTOR_ERROR | 503 / failed | 向量初始化、写入、检索、清理失败 |
| MODEL_UNAVAILABLE | 503 | 模型失败或返回无效引用 |
| MODEL_DISABLED | 403 | 真实调用未启用 |
| UNAUTHORIZED | 401 | 凭证或令牌错误 |
| NOT_FOUND | 404 | 资源缺失或未拥有 |
| CONFLICT | 409 | 用户名或知识库名称重复 |
| INTERNAL_ERROR | 500 / failed | 未预期错误 |

异步失败不改变先前的 202，须轮询文档状态。
PROCESS_INTERRUPTED 是重启恢复时记录的文档错误码。
重复清理向量幂等，已删除的文档资源再次 DELETE 返回 404。
