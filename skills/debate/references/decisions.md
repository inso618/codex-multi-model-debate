# Host 判定、会话管理与恢复

`DEBATE_SKILL` 指安装后的 skill 目录。

## Host 判定

将判定保存为 JSON 文件再传给 `decide --file`。`checks` 必须逐条对应当前层级配置中的检验问题。

继续：

```json
{
  "verdict": "continue",
  "reason": "需核实问题与人群边界",
  "checks": [
    {"question": "能否用一句话描述问题？", "answer": "已有条件性描述，但未核实", "met": false},
    {"question": "核心利益相关者是否覆盖？", "answer": "尚缺关键人群", "met": false}
  ],
  "unresolved_objections": ["缺少关键人群的证据"],
  "next_question": "针对各方上一轮观点，检查问题边界与遗漏人群，给出依据。"
}
```

推进：

```json
{
  "verdict": "converged",
  "reason": "检查点均通过，结构性反对意见已解决",
  "checks": [
    {"question": "能否用一句话描述问题？", "answer": "填写实际问题定义与出处", "met": true},
    {"question": "核心利益相关者是否覆盖？", "answer": "填写实际覆盖范围与出处", "met": true}
  ],
  "unresolved_objections": [],
  "consensus": {
    "Ideal State": "填写已确认的理想态，未定项明确标出",
    "Key Constraints": "填写约束",
    "Chosen Path": "填写当前选择或待定项",
    "Allowed Downgrades": "无 / 实际允许的调整及理由"
  },
  "backcheck": [],
  "challenge_checked": true,
  "challenge_result": "填写实际提出的挑战与检验结果"
}
```

L1 无前置层，`backcheck` 为空。L2 需一项：

```json
{"level":"L1","preserved":true,"explanation":"逐条说明 L1 承诺如何被保留"}
```

后续层依次覆盖之前所有层。若 `preserved=false`，必须增加 `allowed_downgrade` 说明，并同步共识区。`adjudicated` 与 `converged` 使用相同结构，但允许保留未解决问题；前者不是达成共识。

```bash
python3 "$DEBATE_SKILL/scripts/debate.py" decide --session /会话路径 --file /判定.json
python3 "$DEBATE_SKILL/scripts/debate.py" round --session /会话路径 --mode exchange --question '针对上一轮分歧进行互评'
python3 "$DEBATE_SKILL/scripts/debate.py" run --session /会话路径 --live
```

每层首轮 independent，后续 exchange。推进后下一层重新独立提交，但允许保留已公开的前层历史和共识。

## 恢复、干预、压缩

- `status --session ...`：查看状态，不联网。
- 对同一轮再次 `run --live`：跳过成功者，重试失败者。超时/连接断开/5xx 视为结果不确定，不自动重试；只有用户接受重复计费风险后才加 `--retry-uncertain`。并非 exactly-once；程序不能保证网络中断时远端未执行。
- 文件尚在处理：稍后重跑；已保存 file_id，不重复上传。过期或不可用：`refresh-files --participant ID --reason '原因'` 清空本地引用，下次 run 重传原件。远端旧文件不自动删除。
- `intervene --text '用户新增意见'`：在轮次边界记录，下一轮全员收到。已冻结但尚未开始模型调用的轮次可 `discard-round --reason ...` 后加意见并重新生成。部分成功的一轮不能悄悄删除。
- `compact --file /压缩.json`：只在完整且已判定的轮次边界执行。文件格式：`{"reason":"原因","summaries":{"参与者ID":"该参与者可见历史的忠实摘要"}}`。每个参与者均需独立摘要；保留最近两轮自身历史与全部原始日志。不自动压缩原始文件。超过供应商 Token 上限时明确报错，字数检查不能保证 API 一定容纳。
- `finalize --file /最终结论.md`：所有层完成后收尾；提前结束需 `--force-reason '具体原因'`。
- `export`：重新生成可读报告。

## 会话文件

```text
会话目录/
  state.json          权威状态；独立历史、共识、判定和各家文件引用
  discussion.md       可读报告；新轮在前，最终结论在末尾
  originals/          原件字节快照，仅复制和校验，不解析
  requests/           实际请求体，无认证头；可检查每次模型看到了什么
  responses/          提供方完整响应（含引用/用量等字段）
  compactions/        显式上下文压缩记录
```

会话目录和 Key 含私有资料，默认分别 700/600 权限。`state.json` 中 Kimi 的 vendor_content 只属于 Kimi 的私有文件引用；不进入其他模型上下文。文件默认按提供方规则保留在远端；本版不自动删除远端文件，不保证零留存。

## 离线验证

```bash
python3 -m unittest discover -s "$DEBATE_SKILL/tests" -v
python3 "$DEBATE_SKILL/scripts/demo.py" --output /新的演示目录
```

mock 会话不可切换成 live。演示回答全部有 MOCK 标记，不验证真实模型能力或远端 schema 接受情况。真实验证需要配置 Key，选用用户明确授权的非敏感附件，先跑一轮再扩大。
