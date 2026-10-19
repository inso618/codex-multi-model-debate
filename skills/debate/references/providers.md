# 原始文件接入支持表

核对日期：2026-10-19。接口实现依据官方文档；真实调用结果以各会话的 responses 和讨论记录为准，文本调用成功不证明附件解析能力。格式白名单保守，不能通过修改后缀绕过。

| provider | 原件如何接收 | 当前范围/限制 |
|---|---|---|
| anthropic | `POST /v1/files` multipart 原始字节；Messages 引用 `document.source.file_id` / `image.source.file_id` | PDF、文本、常见图片；不是任意 Office 文件。模型需支持文件类型。当前官方 Files 文档已移除旧 beta header。 |
| grok | `POST /v1/files`，purpose=assistants；Responses 的 `input_file.file_id` | 首版保守支持 PDF/文本/CSV/JSON；供应商自动文档检索，不能声称每页都读过。 |
| qwen | 百炼兼容 Files，purpose=file-extract；system `fileid://...` | Qwen-Long 原件由百炼服务解析。不能自动用 qwen-max 替代；端点、Key 地区按账号配置，文档示例同时出现 workspace 北京端点与旧 dashscope 端点，需实测。 |
| kimi | Kimi Files 上传原件；获取本服务抽取结果后只传回 Kimi | `file_mode=vendor_extract`。不是本地解析，非各家共享抽取结果；不是原生 PDF 视觉。未声称 Kimi Responses 接受 input_file。 |
| deepseek | `POST /files` purpose=user_data；Chat `{"type":"file","file_id":...}` | 当前已核对仅 JPEG/PNG/GIF/WebP，需对应支持视觉的模型；PDF/Office 明确阻止。 |
| hunyuan | 仅文本 Chat Completions 可配置 | 原件文件路线阻止。旧 FilesUploads 需要 URL，且官方预下线；没有为此创建公网文件托管。 |
| tokenhub | 可配置的独立 Chat Completions 参与者，共用中国站广州的推理 Key | `glm-5.3-flash`、`mimo-v2.6-pro`、`kimi-k3`；`hy4-preview` 可显式配置，示例默认不启用；当前适配器仅文本，所有原件附件拦截。GLM 文档接口只接受 file_url，需额外托管，当前未实现；不调用 CLI 的本地文本内联。 |
| openai | Files purpose=user_data；Responses `input_file.file_id` | 可选独立 GPT 辩手，使用自己的 API 额度；不复用 Host 的订阅或聊天历史。PDF 需视觉模型。 |

所有附件在每个参与者处独立上传。相同厂商的两个参与者也各自维护引用和历史。程序做全员能力预检，任一不支持则整轮在上传前停止，不静默缩小参与者名单。Key 无法改变所选接口的文件能力。

TokenHub 是统一服务入口，不等同于分别调用各模型厂商官网。随附示例中 DeepSeek 使用官网直连。TokenHub Key 只在调用时读取，不写入 state、requests 或 responses；CLI 的临时 SecretId/SecretKey 不被本程序读取。

所有请求使用完整本地重放历史；不依赖远端 conversation ID 自动记忆，避免不同厂商状态语义不一致。Responses 的 store=false 不代表原始文件无留存；文件是独立资源。每轮继续引用原件，模型不会因一次文本摘要就失去原件入口。

Kimi 返回的抽取内容可能包含 JSON 包装，按官方示例原样作为文件内容送回本服务模型；本地不理解、修订、补写或共享给其他参与者。大文件的字数/上下文超限会显式报错，不能静默切换为摘要。

## 官方依据

- [Anthropic Files](https://platform.claude.com/docs/en/build-with-claude/files)
- [xAI Files 上传](https://docs.x.ai/developers/files/managing-files)
- [xAI Chat with Files](https://docs.x.ai/developers/model-capabilities/files/chat-with-files)
- [Qwen-Long](https://help.aliyun.com/zh/model-studio/long-context-qwen-long)
- [Kimi 上传文件](https://platform.kimi.com/docs/api/files-upload)
- [Kimi 获取文件内容](https://platform.kimi.com/docs/api/files-content)
- [DeepSeek Files API](https://api-docs.deepseek.com/guides/files_api/)
- [混元旧 FilesUploads 的预下线说明](https://cloud.tencent.com/document/product/1729/112211)
- [OpenAI File inputs](https://developers.openai.com/api/docs/guides/file-inputs)
- [TokenHub 快速入门与统一接口](https://cloud.tencent.com/document/product/1823/130058)
- [TokenHub GLM：多轮历史与仅 URL 文件输入](https://cloud.tencent.com/document/product/1823/132061)
- [TokenHub CLI 本地配置与站点](https://github.com/TencentCloud/THCLI)

## 更新适配器

先核对具体模型和官方原始文件输入协议，再修改 `scripts/providers.py` 中能力检查、上传、请求组装、响应解析，并增加离线协议测试。不要把 OpenAI-compatible 当作文件上传/引用协议必然兼容的证据。

无自动 API 重试。失败时保存状态；网络断开可能已经计费/上传成功，需要人工决定是否重试。接口不支持或返回错误时，不转用浏览器、其他服务商、其他模型，也不自行转换附件。
