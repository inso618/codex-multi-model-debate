#!/usr/bin/env python3
"""Create a ten-round offline example. No real credentials or network."""
import argparse
import json
from pathlib import Path

import engine as e


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.output).resolve()
    if root.exists():
        raise SystemExit("输出目录已存在，不覆盖")
    root.mkdir(parents=True, mode=0o700)
    original = root / "original.txt"
    original.write_bytes("这是离线流程测试附件，不是业务分析材料。\n所有模型回答都是模拟输出。\n".encode())
    members = []
    for pid, provider, model, role in [("claude", "anthropic", "mock-claude", "Proposer"), ("qwen", "qwen", "qwen-long", "Reviewer"), ("grok", "grok", "mock-grok", "Challenger")]:
        members.append({"id": pid, "provider": provider, "enabled": True, "model": model, "base_url": "https://example.invalid/v1", "api_key_env": "MOCK_KEY_UNUSED", "role": role, "focus": "离线机制验证", "max_context_chars": 200000})
    config = root / "config.json"
    e.write_json(config, {"participants": members})
    directory = root / "session"
    e.make_session(config, directory, "MOCK：分层 Debate 流程演示", [original], mock=True)
    state = e.read_json(directory / "state.json")
    for _ in range(5):
        level = e.active_level(state)
        for mode in ("independent", "exchange"):
            e.new_round(directory, state, "离线验证 " + level["title"] + "，不生成真实业务建议", mode)
            e.run_round(directory, state)
            decision = {"verdict": "continue" if mode == "independent" else "converged", "reason": "MOCK 状态机测试，非真实模型共识", "checks": [{"question": q, "answer": "MOCK：程序检查点", "met": True} for q in level["checks"]], "unresolved_objections": [], "next_question": "MOCK：交叉审视", "consensus": {k: "MOCK 示例，不能用作业务决策" for k in e.CONSENSUS_KEYS}, "backcheck": [{"level": prev["id"], "preserved": True, "explanation": "MOCK 回溯验证"} for prev in state["levels"][:state["level_index"]]], "challenge_checked": True, "challenge_result": "MOCK 挑战检查"}
            e.decide(directory, state, decision)
    e.finalize(directory, state, "此文件仅证明程序可以跑完 5 层、10 轮、3 个模拟参与者的流程。未调用任何模型，也不证明模型读懂了附件。")
    print(json.dumps({"mock": True, "network_called": False, "report": str(directory / "discussion.md"), "rounds": len(state["rounds"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
