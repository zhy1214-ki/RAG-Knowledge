# API参考（V1.0）

由源码静态核对的20个应用端点；不通过导入FastAPI应用生成，避免加载凭据或触发生命周期。
源码：[基础路由](../../backend/app/api/base.py)、[文档路由](../../backend/app/api/documents.py)、
[会话路由](../../backend/app/api/chat.py)、[健康](../../backend/app/main.py)、
[Pydantic模型](../../backend/app/schemas/__init__.py)、[鉴权](../../backend/app/api/deps.py)。

## 1. 地址、认证与响应

开发后端为http://127.0.0.1:8000，8080前端通过Nginx同源代理/api。
仅health、注册和登录不需已登录身份，其余业务端点均需有效Bearer认证。
本材料不提供完整认证请求、任何密码或令牌示例。

开发后端提供/docs、/redoc和/openapi.json；这些是框架文档路由，不计入20个应用端点。
现有Nginx只代理/api/，不能把8080/docs当后端Swagger入口；Docker未公开8000宿主端口。

| 包络 | 字段 |
|---|---|
| 成功 | code=OK；message=成功；data为资源、列表或null |
| 错误 | code为安全分类码；message为安全说明；data=null；request_id为随机关联ID |

健康端点返回status、model_backend、vector_backend，只表明应用可响应及当前配置，
不主动连接数据库、执行Milvus查询或调用模型，不能独立视为全部依赖就绪检查。

## 2. 全部应用端点

鉴权“是”表示需current_user；资源接口还会做owned_kb或owned_session校验。

| 编号 | 方法 | 完整路径 | 请求 | 成功HTTP/数据 | 鉴权 |
|---|---|---|---|---|---|
| API01 | GET | /api/health | 无 | 200/状态与模式 | 否 |
| API02 | POST | /api/auth/register | Credentials | 201/UserOut | 否 |
| API03 | POST | /api/auth/login | Credentials | 200/TokenOut | 否 |
| API04 | GET | /api/auth/me | 无 | 200/UserOut | 是 |
| API05 | GET | /api/knowledge-bases | 无 | 200/KBOut列表 | 是 |
| API06 | POST | /api/knowledge-bases | KBInput | 201/KBOut | 是 |
| API07 | GET | /api/knowledge-bases/{kb_id} | 路径ID | 200/KBOut | 是 |
| API08 | PUT | /api/knowledge-bases/{kb_id} | 路径ID+KBInput | 200/KBOut | 是 |
| API09 | DELETE | /api/knowledge-bases/{kb_id} | 路径ID | 200/null | 是 |
| API10 | POST | /api/knowledge-bases/{kb_id}/documents | multipart字段file | 202/DocumentOut | 是 |
| API11 | GET | /api/knowledge-bases/{kb_id}/documents | 路径ID | 200/DocumentOut列表 | 是 |
| API12 | GET | /api/knowledge-bases/{kb_id}/documents/{doc_id} | 路径ID | 200/DocumentOut | 是 |
| API13 | DELETE | /api/knowledge-bases/{kb_id}/documents/{doc_id} | 路径ID | 200/null | 是 |
| API14 | POST | /api/knowledge-bases/{kb_id}/search | SearchInput | 200/Citation列表 | 是 |
| API15 | POST | /api/sessions | SessionInput | 201/SessionOut | 是 |
| API16 | GET | /api/sessions | 无 | 200/SessionOut列表 | 是 |
| API17 | GET | /api/sessions/{session_id} | 路径ID | 200/SessionOut | 是 |
| API18 | DELETE | /api/sessions/{session_id} | 路径ID | 200/null | 是 |
| API19 | GET | /api/sessions/{session_id}/messages | 路径ID | 200/MessageOut列表 | 是 |
| API20 | POST | /api/sessions/{session_id}/messages | MessageInput | 200/assistant MessageOut | 是 |

没有分页参数、按文件下载接口、自动重试索引接口、模型管理接口或专用首页统计接口。
API14在qwen模式下可能调用问题Embedding，不能认为“仅搜索”始终不产生模型请求。
本轮不执行上表任何业务请求。

## 3. 请求模型

| 模型 | 字段与校验 |
|---|---|
| Credentials | username：3–64位字母/数字/下划线/短横线；password：8–128字符 |
| KBInput | name必填、1–120字符；description默认空字符串、至多4000字符 |
| SearchInput | question必填、1–4000字符；top_k默认5、整数1–10 |
| SessionInput | knowledge_base_id必填字符串；title默认新会话、1–120字符 |
| MessageInput | 继承SearchInput，不接受用户指定来源或模型密钥 |
| 上传 | file必填；支持pdf/docx/txt/md；非空且默认不超过20MiB |

KBInput在PUT时也要求name，不是PATCH。
模型中的字符串ID没有声明UUID格式校验器；实际保存的主键为UUID字符串。
不能将UI上的trim或必填提示扩大成后端未声明的数据库约束。

## 4. 响应模型字段

| 模型 | 字段 |
|---|---|
| UserOut | id、username |
| TokenOut | access_token、token_type、user；仅运行期传递，不收入材料样例 |
| KBOut | name、description、id、owner_id、created_at |
| DocumentOut | id、knowledge_base_id、name、file_type、size、status、progress、chunk_count、error_code、created_at |
| SessionOut | knowledge_base_id、title、id、created_at；不包含owner_id |
| MessageOut | id、session_id、role、content、citations、created_at |
| Citation | source_id、chunk_id、document_id、knowledge_base_id、source_name、source_location、text、score |

DocumentOut不返回file_path；UserOut不返回password_hash。
role在响应中限定为user或assistant。单次消息POST返回assistant，非返回整段历史；
成功后GET消息记录包含同次保存的user和assistant两条。

source_location由解析器生成：PDF含format=pdf和实际page；
DOCX含format=docx与section=正文；TXT/MD仅含format。
引用编号源自当前检索结果，不会因模型只选部分来源而重新编号。

## 5. 异步处理与错误语义

上传202表示已保存文件和元数据且已安排后台任务，不表示indexed。
后续解析/Embedding/向量错误记录于Document.status=failed及error_code；
状态GET仍通常返回200/OK包络，需检查data.status。
progress的10/40/100为处理阶段；前端文件传输进度是另一个独立值。

| 错误码 | HTTP或出现位置 | 含义 |
|---|---|---|
| VALIDATION_ERROR | 422 | 参数、非法名称或空文件 |
| UNSUPPORTED_FILE | 415 | 文件扩展名不支持 |
| FILE_TOO_LARGE | 413 | 超过上传上限 |
| PARSE_ERROR | 后台failed；解析函数分类422 | 无可提取文本、解析失败或文本规模不合要求 |
| DATABASE_ERROR | 503；后台可能无法写状态 | 关系数据库操作异常 |
| EMBEDDING_ERROR | 503或后台failed | 向量服务或返回格式异常 |
| VECTOR_ERROR | 503或后台failed | 向量初始化、插入、检索、删除异常 |
| MODEL_UNAVAILABLE | 503 | 生成服务异常或回答/引用格式无效 |
| MODEL_DISABLED | 403 | 真实模型适配层的授权/凭据门禁 |
| UNAUTHORIZED | 401 | 登录凭据或JWT无效 |
| NOT_FOUND | 404 | 缺失或未拥有的资源 |
| CONFLICT | 409 | 用户名或同所有者知识库名称冲突 |
| HTTP_ERROR | 对应框架HTTP状态 | 统一处理的HTTP异常 |
| INTERNAL_ERROR | 500或后台failed | 未分类内部错误 |
| PROCESS_INTERRUPTED | Document.error_code | 启动时将中断的uploaded/processing标记failed |

deleting是文档状态而非HTTP错误码；删除外部索引失败后保留元数据，允许恢复后再次DELETE。
向量删除是幂等操作，但已不存在的文档资源重复DELETE仍返回404。
无检索证据返回200及证据不足回答，不是服务故障，也不会调用生成模型。
数据库故障、结果不确定或超时不允许客户端盲目重新POST。

## 6. 排序与隔离

知识库/文档/会话列表按created_at倒序；
消息GET按created_at及id正序。没有游标或分页保证。
所有权由服务端JWT身份确定，客户端提交owner_id不能绕过隔离。
删除文档不删除已有消息来源快照；删除会话或知识库会清除相关消息。
本参考是源码契约快照，不是本轮实时OpenAPI抓取或接口复测结果。