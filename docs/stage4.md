# Stage 4：Embedding与Milvus向量检索

本Stage是开发历程专题，不是历史Git版本。所有运行结论均带证据范围，本轮不执行业务验收。

## 1. 阶段目标

以固定1024维向量建立知识库内Top-K检索，并验证持久化和删除。M2建立适配层，后续M4设施及真实模型验收补充证据。

## 2. 技术与依赖

text-embedding-v4、HTTPX模型适配、PyMilvus与Milvus Lite。Mock特征向量和内存向量库是两个独立替身维度；Mock模型也可用于真实Milvus设施测试，不能把该组合称为真实Embedding。

## 3. 实现内容

模型层统一embed接口；真实响应检查数量、维度与有限数值。基础适配每批最多10条；独立真实模式还按输入估算上限拆批，上传文档不能假定只调用一次。Milvus集合区分模型模式，主键chunk_id，COSINE相似度，动态元数据带文档和知识库标识。

## 4. 核心代码位置

| 代码 | 职责 |
|---|---|
| [providers.py](../backend/app/rag/providers.py) | Mock与Qwen Embedding适配 |
| [vectors.py](../backend/app/rag/vectors.py) | 内存替身、Milvus持久化、过滤与删除 |
| [检索服务](../backend/app/services/chat.py) | 查询向量化及关系库复核 |
| [真实模型包装](../backend/app/real_usage/models.py) | 输入/批量约束和费用门禁 |
| [配置](../backend/app/core/config.py) | 维度、Top-K相关阈值及存储URI |

## 5. 关键实现流程

片段文本 → Embedding → 写入chunk_id关联向量。问题 → 单条查询Embedding → 用knowledge_base_id过滤Milvus → 按默认0.2阈值筛选 → 关系库复核片段/文档归属及indexed。Top-K由请求模型限制为1～10；向量返回不直接等于可用证据。

## 6. 测试与验证结果

[test_milvus.py](../backend/tests/test_milvus.py)有真实插入、过滤、删除及重开测试定义；H01记录该设施PASS，输入向量来自替身。H02/H03和H09才包含真实Embedding。离线向量确定性及异常覆盖在[test_m2.py](../backend/tests/test_m2.py)。本轮没有访问Milvus或模型。

## 7. 遇到的问题及解决方案

曾处理主键结果字段、SDK保留环境名冲突、集合重开加载与本地服务文件锁。使用VECTOR_URI，打开集合显式load_collection，关闭时释放本适配器本地服务。固定版本目录型存储不能仅据.db后缀用is_file判断；也不能无差别放宽所有路径校验。

## 8. 阶段成果

获得持久化向量适配与双层作用域校验。删除按document_id清理，Mock/Qwen集合不能互当有效索引；保留单实例单worker约束，不把内存替身或单样本命中率推广为语义检索质量评估。

## 9. 对应真实开发证据

[开发历程](development-history.md)H01、H02、H03、H06和H09；[架构](ARCHITECTURE.md)；[向量检索图](final-delivery/diagrams/06-vector-retrieval.mmd)。实际集合、用户资源标识及向量数据不公开。

[返回计划](development-plan.md) · [查看实际历程](development-history.md)
