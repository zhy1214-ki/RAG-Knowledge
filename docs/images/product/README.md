# 合成 UI 示意图说明

这六张图片是合成 UI 示意图，来自既有 M6 验证中的实际 Vue 界面与 Mock API 数据；不是生产环境或真实模型调用的运行截图，不能作为真实 Qwen 回答或真实数据库内容的证明。没有为本次 README 更新启动服务、上传文档或调用模型。

来源实现：[截图场景](../../../frontend/tests/m6-capture.spec.ts) · [合成 API 夹具](../../../frontend/tests/fixtures/m6-api.ts) · [界面实现记录](../../stage6.md)。

## 来源及完整性

本次从已审查的历史素材逐字节复制，未裁剪、拼接、重绘或更改文字。除引用展开图来自 M6 的补充状态外，其余来自 M6 新版主页面。下列素材标识用于追溯，不是缺失的公开下载链接。

| 公开文件 | 历史素材标识 | 尺寸 | SHA-256 |
|---|---|---|---|
| [home.png](home.png) | M6 / after/home.png | 1440 × 1167 | `168374d8cc56cf3209b4c4a624b0f74ff36fae3aa08d71e80321cddf7ae52473` |
| [knowledge.png](knowledge.png) | M6 / after/knowledge.png | 1440 × 1000 | `16e283066565121d40eacdcb644f7e3da85366c0efb1b16f237560b010be99d7` |
| [documents.png](documents.png) | M6 / after/documents.png | 1440 × 1000 | `7d8cc64a788f488af61a8864e04221a14d1402d7b0a873006927ef0850611f0c` |
| [chat.png](chat.png) | M6 / after/chat.png | 1440 × 1015 | `32ae493960b0a471594dc9a41e3ccf8e5bf2a75f332304554bb9688611350d9c` |
| [citations.png](citations.png) | M6 / states/chat-citations.png | 1440 × 1015 | `26dacef930175deb826b2a99228a7d2632bf44fe633361b1d7720f6c202db336` |
| [history.png](history.png) | M6 / after/history.png | 1440 × 1057 | `a8db8b61ccfcf7e66ae0d1589d9afc0f1643b30e4eb112df33dfb2be832e82bd` |

## 隐私复核

- 六图均已人工逐张查看，并与合成夹具及既有 UI 审查记录核对。
- 可见账号别名、文档名称、文档标识、统计数量和会话内容来自合成夹具，不是实际用户身份、上传文件或聊天记录。
- 画面不含 API Key、Token、密码、邮箱、浏览器地址栏、私有文件路径或审批信息。
- 六份 PNG 不含文本元数据或 EXIF；原始字节 SHA-256 与来源一致。
- 文档页中的处理进度、失败状态及引用中的 PDF 页码是对应 Mock 场景的展示，不能据此推断真实环境当前状态。

本目录仅分发这六张已复核的合成 UI 示意图，不复制历史运行审计、私有凭据、生产截图或用户数据。
