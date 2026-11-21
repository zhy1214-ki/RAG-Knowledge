# Stage 3：文档上传、解析与切分

本Stage是开发历程专题，不是历史Git版本。所有运行结论均带证据范围，本轮不执行业务验收。

## 1. 阶段目标

将PDF、DOCX、TXT和Markdown变成可追溯片段，并在后台失败时留下安全状态。主要对应M2，后续补强后台异常和删除一致性。

## 2. 技术与依赖

FastAPI UploadFile/BackgroundTasks、PyMuPDF、python-docx、LlamaIndex SentenceSplitter、文件系统与SQLAlchemy。没有OCR或持久任务队列。

## 3. 实现内容

校验扩展名、文件名、空文件及20MiB默认上限；磁盘使用服务端UUID命名。PDF逐页提取，DOCX提取正文和表格并限制解压总量，文本按UTF-8读取；清洗后限制总文本量。默认分块size=384、overlap=48，是SentenceSplitter参数，不应解释成固定字符数。

## 4. 核心代码位置

| 代码 | 职责 |
|---|---|
| [文档API](../backend/app/api/documents.py) | 上传、列表、状态、删除与检索入口 |
| [解析和分块](../backend/app/rag/parsing.py) | 格式适配、清洗、source_location |
| [文档服务](../backend/app/services/documents.py) | 后台状态、索引和清理 |
| [Document/Chunk模型](../backend/app/models/__init__.py) | 文件、片段和索引状态 |
| [文档页面](../frontend/src/views/Documents.vue) | 上传进度、阶段、失败提示与轮询 |

## 5. 关键实现流程

上传成功后返回202并安排后台处理：uploaded → processing（10%解析、40%向量阶段）→ indexed（100%）；失败为failed。进度是处理阶段，不是字节解析比例。解析 → 分块 → Embedding → 向量写入 → 关系片段与indexed一次提交。删除先写deleting墓碑，再清向量、文件和关系数据。

## 6. 测试与验证结果

M2历史记录覆盖正常上传、四格式、解析与Embedding失败、作用域及删除失败；最终汇总见H01，未将早期用例另加总。定义见[test_m2.py](../backend/tests/test_m2.py)与后台未知异常的[test_security.py](../backend/tests/test_security.py)。本轮没有上传或重建索引。

## 7. 遇到的问题及解决方案

格式不能靠扩展名完全确认，解析异常统一为安全错误；没有可提取文本的扫描PDF明确失败。关系库与向量库没有分布式事务，因此失败尝试清向量并限制只有indexed可检索；服务重启把中断任务标记失败，不伪装为自动续跑。

## 8. 阶段成果

每个片段保存chunk_id、document_id、knowledge_base_id、text、source_name、source_location和chunk_index。PDF保留真实页码，DOCX/TXT/Markdown不捏造页码。后台任务适合演示规模，不保证掉电后自动恢复处理。

## 9. 对应真实开发证据

[开发历程](development-history.md)H01；[解析/切分图](final-delivery/diagrams/04-parse-and-chunk.mmd)；[业务表设计](final-delivery/DATABASE_DESIGN.md)。原用户上传和解析正文不作为公开证据。

[返回计划](development-plan.md) · [查看实际历程](development-history.md)
