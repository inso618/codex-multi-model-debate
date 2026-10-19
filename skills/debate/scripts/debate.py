#!/usr/bin/env python3
"""CLI entry point: local-only by default; network requires run --live."""
import argparse
import json
import os
from pathlib import Path

import engine as e
from providers import DebateError, NOTES

DEFAULT_CONFIG = Path(os.environ.get("DEBATE_CONFIG", str(Path.home() / ".config/codex-debate/providers.json"))).expanduser()


def print_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser():
    p = argparse.ArgumentParser(description="Codex 主持的原始文件多模型 Debate（Python 标准库，无 MCP 服务依赖）")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="建立独立会话并复制原件；不调用网络")
    init.add_argument("--config", default=str(DEFAULT_CONFIG))
    init.add_argument("--session", required=True)
    init.add_argument("--topic", required=True)
    init.add_argument("--project")
    init.add_argument("--file", action="append", default=[])
    init.add_argument("--mock", action="store_true", help="不可切换为真实模式的离线演示")
    doctor = sub.add_parser("doctor", help="检查本地配置、文件能力和 Key 是否存在，不调用网络")
    doctor.add_argument("--config", default=str(DEFAULT_CONFIG))
    doctor.add_argument("--session")
    sub.add_parser("capabilities", help="显示已核对的提供方文件路线")
    for name in ("status", "round", "run", "decide", "intervene", "compact", "finalize", "refresh-files", "discard-round", "export"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--session", required=True)
        if name == "round":
            cmd.add_argument("--question", required=True)
            cmd.add_argument("--mode", choices=["independent", "exchange"], default="independent")
        elif name == "run":
            cmd.add_argument("--live", action="store_true", help="允许向配置的服务发送原始文件和请求，可能计费")
            cmd.add_argument("--retry-uncertain", action="store_true", help="允许重试结果不确定的请求，可能重复计费/上传")
            cmd.add_argument("--workers", type=int, default=3)
        elif name in {"decide", "compact", "finalize"}:
            cmd.add_argument("--file", required=True)
            if name == "finalize":
                cmd.add_argument("--force-reason")
        elif name == "intervene":
            cmd.add_argument("--text", required=True)
        elif name == "refresh-files":
            cmd.add_argument("--participant", required=True)
            cmd.add_argument("--reason", required=True)
        elif name == "discard-round":
            cmd.add_argument("--reason", required=True)
    return p


def main():
    args = parser().parse_args()
    try:
        if args.command == "capabilities":
            print_json(NOTES)
            return 0
        if args.command == "init":
            print_json(e.make_session(args.config, args.session, args.topic, args.file, args.project, args.mock))
            return 0
        if args.command == "doctor" and not args.session:
            path = Path(args.config).resolve()
            cfg = e.read_json(path)
            e.load_env(path.parent / cfg["env_file"] if cfg.get("env_file") else None)
            members = [p for p in cfg.get("participants", []) if p.get("enabled")]
            if len(members) < 2:
                raise DebateError("至少启用两个参与者")
            for member in members:
                e.validate_participant(member)
            result = e.preflight({"participants": members, "files": [], "mock": False}, True)
            print_json(result)
            return 0 if result["ok"] else 2
        directory = Path(args.session).resolve()
        with e.locked(directory) as state:
            command = args.command
            if command in {"doctor", "run"}:
                e.load_env(state.get("env_file"))
            if command == "doctor":
                result = e.preflight(state, not state["mock"])
                print_json(result)
                return 0 if result["ok"] else 2
            if command == "status":
                result = e.summary(state)
            elif command == "round":
                result = e.new_round(directory, state, args.question, args.mode)
            elif command == "run":
                result = e.run_round(directory, state, args.live, args.retry_uncertain, args.workers)
                print_json(result)
                return 0 if result["status"] in {"complete", "already_complete"} else 3
            elif command == "decide":
                result = e.decide(directory, state, e.read_json(args.file))
            elif command == "intervene":
                e.intervene(directory, state, args.text)
                result = {"status": "recorded", "effective": "next_round"}
            elif command == "compact":
                e.compact(directory, state, e.read_json(args.file))
                result = {"status": "compacted", "raw_history_preserved": True}
            elif command == "finalize":
                e.finalize(directory, state, Path(args.file).read_text(encoding="utf-8"), args.force_reason)
                result = e.summary(state)
            elif command == "refresh-files":
                pid = args.participant
                if pid not in state["uploads"]:
                    raise DebateError("未知参与者")
                if state["rounds"] and any(j["status"] in {"inflight", "uncertain"} for j in state["rounds"][-1]["jobs"].values()):
                    raise DebateError("存在结果不确定的模型调用，先解决重试状态")
                state["upload_archive"].append({"participant": pid, "references": state["uploads"][pid], "reason": args.reason, "at": e.now()})
                state["uploads"][pid] = {}
                e.save(directory, state)
                result = {"status": "cleared_local_references", "remote_files_deleted": False, "next_run": "reupload_originals"}
            elif command == "discard-round":
                if not state["rounds"]:
                    raise DebateError("没有可放弃的轮次")
                rnd = state["rounds"][-1]
                if any(j["status"] != "pending" or j["attempts"] for j in rnd["jobs"].values()):
                    raise DebateError("只能放弃所有模型调用均未开始的轮次；部分完成记录不能删除")
                state.setdefault("discarded_rounds", []).append({"round": state["rounds"].pop(), "reason": args.reason, "at": e.now()})
                e.save(directory, state)
                result = {"status": "discarded", "archived": True}
            elif command == "export":
                e.export(directory, state)
                result = {"report": str(directory / "discussion.md")}
            print_json(result)
        return 0
    except (DebateError, OSError, ValueError, KeyError, TypeError) as err:
        # Expected errors only; avoid printing arbitrary provider/config bodies.
        print_json({"error": str(err) if isinstance(err, DebateError) else "本地配置或文件处理失败（" + type(err).__name__ + "）；检查路径与 JSON 字段。", "network_retry": False})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
