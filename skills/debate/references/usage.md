# 运行手册

本程序需要 Python 3.9+ 和 macOS / Linux / WSL。仅使用标准库，无需 MCP 服务。`DEBATE_SKILL` 是本 skill 的实际安装目录；不要假定用户的主目录名称。

## 初始化与配置

```bash
DEBATE_SKILL="${CODEX_HOME:-$HOME/.codex}/skills/debate"
python3 "$DEBATE_SKILL/scripts/setup.py"
```

默认生成 `~/.config/codex-debate/providers.json` 和同目录 `keys.env`，拒绝覆盖。可以用 `setup.py --config /自选目录/providers.json` 或环境变量 `DEBATE_CONFIG` 指定位置。配置 JSON 中的 `env_file` 相对配置文件所在目录解析。已有安全的 `keys.env` 会复用；用户在本地填写，不经聊天传递。

已存在的进程环境变量优先于 `keys.env`。该文件只解析 `KEY=value` 行，不作为 shell 脚本执行；不要使用命令替换或引用其他变量。文件应保持权限 `600`。如需沿用已有安装的配置，显式指定原配置路径，不复制其 Key 到 skill 目录。

示例配置至少启用两个模型，默认四名参与者仅用于文本讨论。其他提供方见 `assets/provider-templates.json`；这些模板默认禁用，`YOUR_MODEL_ID` 必须替换成实际模型 ID。删除不使用的参与者或设置 `enabled=false`，不要将不可用模型静默替换。

| 字段 | 说明 |
|---|---|
| `id` | 会话内唯一参与者 ID，初始化后固定 |
| `provider` | `anthropic` / `openai` / `grok` / `qwen` / `kimi` / `deepseek` / `hunyuan` / `tokenhub` |
| `enabled` | 是否参与新会话 |
| `model` / `base_url` | 真实模型 ID 与 API 基址；以账号和地区为准 |
| `api_key_env` | 保存 Key 的环境变量名称，不能填写 Key 本身 |
| `role` / `focus` | 角色与关注点，不改变基础材料的一致性 |
| `max_output_tokens` | 输出上限，默认 4096，示例 8192；推理模型需留足推理和正文空间 |
| `max_context_chars` | 本地上下文字数保护阈值，默认 120000；不是精确 Token 上限 |
| `timeout_seconds` | 单次 HTTP 请求总时限，默认 240 秒，上限 900 秒 |
| `first_response_timeout_seconds` / `idle_timeout_seconds` | 可选等待限制，默认等于总时限，不能大于总时限 |
| `stream` | Chat Completions 的 SSE；TokenHub 默认开启；Anthropic / OpenAI / Grok 此版不支持开启 |
| `generation` | 提供方生成参数，不能覆盖模型、上下文、工具、存储及长度等受控字段 |
| `file_mode` | Kimi 官网抽取需明确 `vendor_extract`；TokenHub 示例为 `text_only` |
| `max_files` / `max_file_mb` | 本地数量和体积保护，默认 10 个 / 每个 20 MiB，不能替代远端限制 |

TokenHub Kimi K3 将统一输出上限映射为 `max_completion_tokens`，默认 `reasoning_effort=high`，支持 `low` / `high` / `max`；完整 assistant 消息（含推理字段）仅回放给自身。原始 SSE 保存在 `responses/*.stream.jsonl`，请求时限和传输指标也保存在日志。部分输出、缺失终止标记或输出长度截断不算完整成功。

可选 `thcli_key` 仅用于明确复用本地 THCLI 凭证，需要显式填写 `profile`、`site`、`area`、`alias`；程序只允许与其站点匹配的 TokenHub 端点。公开模板未绑定任何本地账号，通常直接填写 `TOKENHUB_API_KEY` 即可。详见 `scripts/credentials.py`。

## 离线预检

```bash
python3 "$DEBATE_SKILL/scripts/debate.py" doctor
python3 "$DEBATE_SKILL/scripts/debate.py" capabilities
```

`doctor --config /路径/providers.json` 可检查指定配置。不联网，只检查本地字段、Key 是否存在和文件适配能力；不能据此声明远端调用成功。

## 创建会话与首轮

先明确议题、参与者与附件范围。默认五个层级可在配置顶层的 `levels` 数组中调整为 3～5 项，每项包含唯一 `id`、`title`、`checks`（非空问题数组）。在 `init` 前完成调整；已初始化会话保留配置快照，编辑全局配置不会自动改变旧会话。

选择一个新的、位于仓库外的会话目录：

```bash
DEBATE_SESSION="$HOME/debate-sessions/example-discussion"
python3 "$DEBATE_SKILL/scripts/debate.py" init \
  --session "$DEBATE_SESSION" \
  --topic '需要讨论的具体问题'
python3 "$DEBATE_SKILL/scripts/debate.py" doctor --session "$DEBATE_SESSION"
python3 "$DEBATE_SKILL/scripts/debate.py" round \
  --session "$DEBATE_SESSION" --mode independent \
  --question '请独立检查本层问题，给出依据、反例和待验证条件。'
```

有原始附件时，在 `init` 增加一个或多个 `--file /原件路径`。程序复制原件并校验字节，不解析；本步骤只在本地操作。所有参与者均通过能力预检后才能上传。**TokenHub 示例阵容不支持附件**，不能用默认阵容演示 PDF 上传。

用户已授权实际讨论及其分发范围后执行：

```bash
python3 "$DEBATE_SKILL/scripts/debate.py" run --session "$DEBATE_SESSION" --live
```

此步骤可能计费，默认最多 3 个并发工作线程。Host 应读取真实响应后作出判定，不得用模板判定冒充证据审查。

## 后续轮次、收尾和中断

首轮完成后，按 [Host 判定手册](decisions.md) 编写判定 JSON，执行 `decide --file`。只有判定继续才在同层准备 `exchange` 轮；推进后下一层重新 `independent`。每层最多 4 轮，全场最多 16 轮。未解决分歧需保留，不能用多数票代替审查。

查看状态：

```bash
python3 "$DEBATE_SKILL/scripts/debate.py" status --session "$DEBATE_SESSION"
```

错误后保留已成功结果；再次 `run --live` 不重复调用成功者。超时、连接断开等不确定结果需要告知可能重复计费，得到用户授权后才能加 `--retry-uncertain`。不自动重传失效文件；`refresh-files`、用户补充、压缩与最终结论的命令及格式均见 [判定手册](decisions.md)。

旧会话的参数来自自身 `state.json` 快照。不要为了套用新配置直接篡改正在进行的请求；新参数优先用于新会话，必要的旧会话迁移应先备份并明确说明影响。

## 不消耗 API 额度的演示

```bash
DEBATE_DEMO_ROOT="$(mktemp -d)"
python3 "$DEBATE_SKILL/scripts/demo.py" --output "$DEBATE_DEMO_ROOT/demo"
```

输出 5 层、10 轮的 MOCK 报告。模拟会话不能切换成真实会话，也不构成真实模型参与或附件理解的证据。
