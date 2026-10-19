# Codex Multi-Model Debate

让 Codex 主持跨厂商多模型辩论：各模型独立分析，再交换观点、检验分歧、逐层收敛；本地程序负责 API 调用、原始附件传输和上下文保存。

A Codex skill for structured, cross-provider debate with independent histories and original-file adapters.

无需搭建 MCP 服务。运行环境：**macOS / Linux / WSL，Python 3.9+，仅 Python 标准库**。原生 Windows 暂不支持（使用 POSIX 文件锁）。真实模型调用需要各服务的 API Key 和额度；Codex 订阅不包含这些外部 API 费用。

## 用 Codex 快速安装

把下面这段直接发给 Codex：

```text
请使用 $skill-installer 从以下 GitHub 地址安装 debate skill：
https://github.com/inso618/codex-multi-model-debate/tree/main/skills/debate

如果已有同名 skill，先说明冲突，不要覆盖。
安装成功后运行随附的 scripts/setup.py 创建本地配置模板；如果配置已存在，保留它。
告诉我如何在本地填写 API Key，不要让我把 Key 发到聊天里。
只做离线检查，不调用付费模型，不上传项目文件。
```

安装后在下一轮消息中使用 `$debate`；如果列表尚未刷新，重新打开会话。安装器会拒绝覆盖同名目录。已安装私人版本的用户应先保留原版本，再决定是否替换。

也可以在终端使用 Codex 自带安装器（以实际安装器位置为准；该安装器需要 Python 3.10+）：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --repo inso618/codex-multi-model-debate \
  --path skills/debate
```

下文的 `DEBATE_SKILL` 指安装后的目录，标准安装可设置为：

```bash
DEBATE_SKILL="${CODEX_HOME:-$HOME/.codex}/skills/debate"
```

Skill 的组成和发现方式见 [Codex 官方说明](https://developers.openai.com/codex/skills)。此仓库的安装单元是 `skills/debate`，不是仓库根目录。

## 配置 API Key

```bash
python3 "$DEBATE_SKILL/scripts/setup.py"
```

初始化只在本地创建两个权限为 `600` 的文件，不联网、不覆盖已有配置：

- `~/.config/codex-debate/providers.json`：参与模型、角色、端点和参数。
- `~/.config/codex-debate/keys.env`：在本地编辑器中填写 Key，不要发送到聊天或提交到 Git。

示例阵容为 GLM-5.3 Flash、MiMo V2.6 Pro、Kimi K3（通过腾讯云 TokenHub），以及 DeepSeek（官网直连）。前三者使用 `TOKENHUB_API_KEY`，DeepSeek 使用 `DEEPSEEK_API_KEY`。Hy4 不在默认阵容中。

**示例模型 ID 不保证在你的账号可用。** 请核对服务商控制台，修改 `model`、`base_url` 和 `enabled`；至少启用两个参与者。也可从 [其他提供方模板](skills/debate/assets/provider-templates.json) 选用 Claude、OpenAI、Qwen、Kimi 官网、Grok，填入实际模型 ID 后启用。提供方、模型与角色分别配置，不自动切换模型。

```bash
python3 "$DEBATE_SKILL/scripts/debate.py" doctor
```

`doctor` 只检查本地字段、Key 是否存在和附件兼容性；**不验证远端鉴权、额度或模型可用性**。配置优先级为 `--config` > `DEBATE_CONFIG` > 默认路径。详细字段见 [运行手册](skills/debate/references/usage.md)。

## 开始讨论

配置完成后，将下面的示例发给 Codex，按需替换议题：

```text
$debate
请用我已配置并启用的模型，讨论“一个新产品应先做网页端还是移动端”。
由你担任 Host，先明确目标用户、资源和验收条件，再设计 3～5 个讨论层级。
本次不上传文件，允许调用所选模型的 API。
先独立分析，再交换观点；保留重要分歧，不按多数票决定。
每层最多 4 轮，全场最多 16 轮，条件满足后提前收敛。
将会话保存在仓库外的新目录，最后给我 discussion.md 和结论摘要。
```

带文件时，明确给出文件路径、接收模型和问题。Codex 会预检每个参与者的文件支持范围，之后分别上传原始字节；不会自动上传整个项目。配置和历史保存在本地，换会话后可通过会话目录继续。

```text
$debate
请继续我指定目录中的已有讨论。先读取 state.json 和 discussion.md，报告当前层级、参与者和未解决分歧，再推进下一轮。
```

## 讨论机制

1. Host 设计 3～5 层问题与检查点，默认覆盖问题定义、理想态、差距、策略、方案。
2. 每层首轮独立作答；所有参与者完成后，下一轮才交换上一轮完整发言。
3. Host 依据证据、检查点和结构性反对意见判断继续、共识或裁决；裁决不冒充共识。
4. 推进时回查此前承诺，并记录挑战检验和允许的取舍。用户新增意见同步给全体。
5. 保留独立历史、请求、响应、判定和最终报告；需要压缩时显式操作，不静默截断。

各模型不继承 Host 的聊天历史。私有 assistant 消息会用于该参与者的下一轮请求；互评仅交换公开发言，不交换私有推理字段。Host 仍会影响问题设计和判定，独立历史不能保证讨论完全无偏。

GPT 也可作为独立 OpenAI API 辩手加入，拥有独立上下文；本版不自动启动 Codex 分身。

## 文件与流式支持范围

“适配器已实现”不等于所有账号、模型、文件组合都已实测。以模型能力、服务商限制和实际响应为准，完整说明见 [提供方支持表](skills/debate/references/providers.md)。

| 接入路线 | 当前原始文件路线 |
|---|---|
| Claude / Anthropic | Files + Messages；PDF、文本、部分图片 |
| OpenAI | Files + Responses；PDF 需支持视觉的模型 |
| Grok / xAI | Files + Responses；保守支持 PDF、文本、CSV、JSON |
| Qwen-Long | 百炼上传并解析原件；不能任意替换成其他 Qwen 模型 |
| Kimi 官网 | 显式 `vendor_extract`：Kimi 服务接收、抽取原件，结果只回传给该参与者；不是原生 PDF 视觉 |
| DeepSeek 官网 | 当前适配器仅允许已核对的图片格式；不支持 PDF / Office |
| TokenHub / 混元文本路线 | 当前适配器仅支持文本；拦截所有原始附件 |

因此，**默认四模型阵容用于文本讨论，不能直接用于 PDF 辩论**。需要 PDF 时应选择支持对应原件的参与者。不会用本地 OCR、文本提取或某个模型的摘要代替其他模型接收原件。

Chat Completions 适配器支持 SSE，TokenHub 默认开启。默认单次 HTTP 请求等待上限为 240 秒，包含等待和接收阶段；一轮含多个模型及可能的上传请求，不保证 240 秒内结束。只有完整响应才写入下一轮历史。超时或中断保留状态，不自动重试；结果不确定时，重试可能重复计费。其他适配器当前使用非流式请求。

## 隐私与保存

- 仓库仅包含程序、空 Key 模板和合成测试；不含真实会话、个人配置、附件或凭证。
- 安装不会上传文件。运行 `run --live` 才向配置的端点发送问题、历史及所选原件，可能产生费用。
- Key 从环境变量或权限受限的本地文件读取，不写入请求认证日志；不要把 Key 写进议题或附件。会话日志仍可能包含敏感正文、模型输出和推理字段，应视为私有资料。
- 提供方按各自政策保存数据，本工具不承诺零留存，也不自动删除远端上传文件。
- 将会话放在仓库外。`.gitignore` 是辅助措施，提交前仍需检查实际暂存内容。
- 安装目录和配置目录分离，便于更新代码时保留 Key；更新不会自动迁移旧会话中的参与者快照。

## 离线演示与开发验证

不需要 Key，不调用模型：

```bash
python3 -m unittest discover -s "$DEBATE_SKILL/tests" -v
DEBATE_DEMO_ROOT="$(mktemp -d)"
python3 "$DEBATE_SKILL/scripts/demo.py" --output "$DEBATE_DEMO_ROOT/demo"
```

演示包含 5 层、10 轮、3 个模拟参与者。输出明确标注 MOCK，仅证明流程可运行，不证明真实模型能力。仓库 CI 在 macOS / Ubuntu、Python 3.9 / 3.12 上运行相同离线验证，不使用真实 API Key。

- [Skill 主持规则](skills/debate/SKILL.md)
- [运行手册：配置与命令](skills/debate/references/usage.md)
- [Host 判定、恢复与上下文管理](skills/debate/references/decisions.md)
- [提供方协议与官方资料](skills/debate/references/providers.md)

License: [MIT](LICENSE).
