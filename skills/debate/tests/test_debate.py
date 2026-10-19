import copy
import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import engine as e
from providers import Adapter, DebateError, HTTP, MockHTTP, RequestFailure, capability
from credentials import resolve_key, validate_source


def member(pid, provider="anthropic"):
    models = {"anthropic": "claude-test", "qwen": "qwen-long", "deepseek": "deepseek-flash"}
    return {"id": pid, "provider": provider, "enabled": True, "model": models.get(provider, "test-model"), "base_url": "https://example.invalid/v1", "api_key_env": "DEBATE_TEST_KEY", "role": "Proposer" if pid == "a" else "Reviewer", "focus": "verify source evidence", "max_output_tokens": 1000, "max_context_chars": 100000, "file_mode": "vendor_extract"}


def judgment(state, verdict="converged"):
    level = e.active_level(state)
    return {"verdict": verdict, "reason": "offline test judgment", "checks": [{"question": q, "answer": "test evidence", "met": True} for q in level["checks"]], "unresolved_objections": [], "next_question": "cross-review", "consensus": {k: "test consensus" for k in e.CONSENSUS_KEYS}, "backcheck": [{"level": l["id"], "preserved": True, "explanation": "preserved in test"} for l in state["levels"][:state["level_index"]]], "challenge_checked": True, "challenge_result": "test challenge"}


class Recording(MockHTTP):
    records = []
    fails = set()
    uncertain = set()
    texts = {}
    guard = threading.Lock()

    def request(self, method, path, body=None, raw=False, multipart=None):
        pid = self.participant["id"]
        with self.guard:
            self.records.append((pid, method, path, copy.deepcopy(body), multipart))
        if method == "POST" and body:
            if pid in self.fails:
                raise RequestFailure("test error", uncertain=pid in self.uncertain)
            response = super().request(method, path, body, raw, multipart)
            text = self.texts.get(pid, "PRIVATE-" + pid)
            if path == "/messages":
                response["content"][0]["text"] = text
            elif path == "/responses":
                response["output"][0]["content"][0]["text"] = text
            else:
                response["choices"][0]["message"]["content"] = text
            return response
        if raw:
            return "KIMI-ONLY-EXTRACT"
        return super().request(method, path, body, raw, multipart)


class DebateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = self.root / "config.json"
        self.session = self.root / "session"
        self.file = self.root / "原始文件.pdf"
        self.blob = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\noriginal bytes, no local parsing\n%%EOF"
        self.file.write_bytes(self.blob)
        Recording.records, Recording.fails, Recording.uncertain, Recording.texts = [], set(), set(), {}

    def tearDown(self):
        self.tmp.cleanup()

    def init(self, members=None, mock=True, files=True):
        self.config.write_text(json.dumps({"participants": members or [member("a"), member("b", "qwen")]}))
        e.make_session(self.config, self.session, "test debate", [self.file] if files else [], mock=mock)
        return e.read_json(self.session / "state.json")

    def run_round(self, state, **kwargs):
        return e.run_round(self.session, state, transport_factory=Recording, **kwargs)

    def test_original_bytes_independent_uploads_and_context_barrier(self):
        state = self.init()
        e.new_round(self.session, state, "independent", "independent")
        self.run_round(state)
        uploads = [r for r in Recording.records if r[4]]
        self.assertEqual(len(uploads), 2)
        self.assertTrue(all(r[4][1] == self.blob for r in uploads))
        refs = [next(iter(state["uploads"][p].values()))["reference"]["file_id"] for p in ("a", "b")]
        self.assertNotEqual(refs[0], refs[1])
        for pid, method, path, body, multipart in Recording.records:
            if body:
                self.assertNotIn("PRIVATE-", json.dumps(body))
        e.decide(self.session, state, judgment(state, "continue"))
        e.new_round(self.session, state, "review", "exchange")
        for pid, job in state["rounds"][-1]["jobs"].items():
            self.assertIn("PRIVATE-a", job["prompt"])
            self.assertIn("PRIVATE-b", job["prompt"])
            self.assertEqual([h["text"] for h in job["history"] if h["role"] == "assistant"], ["PRIVATE-" + pid])
        self.run_round(state)
        self.assertEqual(len([r for r in Recording.records if r[4]]), 2)

    def test_partial_failure_resume_only_failed_member(self):
        state = self.init()
        e.new_round(self.session, state, "test")
        Recording.fails = {"b"}
        self.assertEqual(self.run_round(state)["status"], "open")
        with self.assertRaises(DebateError):
            e.new_round(self.session, state, "next", "exchange")
        resumed = e.read_json(self.session / "state.json")
        Recording.fails = set()
        self.assertEqual(self.run_round(resumed)["status"], "complete")
        self.assertEqual(len([r for r in Recording.records if r[0] == "a" and r[3]]), 1)
        self.assertEqual(len(resumed["histories"]["a"]), 2)
        self.assertEqual(len(resumed["histories"]["b"]), 2)
        before = len(Recording.records)
        self.run_round(resumed)
        self.assertEqual(len(Recording.records), before)

    def test_uncertain_retry_requires_explicit_flag(self):
        state = self.init()
        e.new_round(self.session, state, "test")
        Recording.fails = Recording.uncertain = {"b"}
        self.run_round(state)
        with self.assertRaises(DebateError):
            self.run_round(state)
        Recording.fails = set()
        self.assertEqual(self.run_round(state, retry_uncertain=True)["status"], "complete")

    def test_unsupported_pdf_fails_before_any_network(self):
        state = self.init([member("a"), member("b", "deepseek")])
        e.new_round(self.session, state, "test")
        with self.assertRaises(DebateError):
            self.run_round(state)
        self.assertEqual(Recording.records, [])

    def test_changed_snapshot_prevents_upload(self):
        state = self.init()
        (self.session / state["files"][0]["snapshot"]).write_bytes(b"changed")
        e.new_round(self.session, state, "test")
        with self.assertRaises(DebateError):
            self.run_round(state)
        self.assertFalse(Recording.records)

    def test_source_changes_do_not_change_snapshot(self):
        state = self.init()
        self.file.write_bytes(b"new file version")
        e.new_round(self.session, state, "test")
        self.run_round(state)
        self.assertTrue(all(r[4][1] == self.blob for r in Recording.records if r[4]))

    def test_kimi_vendor_content_stays_private(self):
        state = self.init([member("a"), member("b", "kimi")])
        e.new_round(self.session, state, "test")
        self.run_round(state)
        for pid, _, _, body, _ in Recording.records:
            if body:
                self.assertEqual("KIMI-ONLY-EXTRACT" in json.dumps(body), pid == "b")

    def test_kimi_extraction_must_be_explicit(self):
        p = member("b", "kimi")
        p.pop("file_mode")
        state = self.init([member("a"), p])
        self.assertFalse(e.preflight(state)["ok"])

    def test_real_session_requires_live_and_keys(self):
        state = self.init(mock=False)
        e.new_round(self.session, state, "test")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(DebateError):
                self.run_round(state)
            with self.assertRaises(DebateError):
                self.run_round(state, live=True)
        self.assertFalse(Recording.records)

    def test_mock_cannot_be_promoted_to_live(self):
        state = self.init()
        e.new_round(self.session, state, "test")
        with self.assertRaises(DebateError):
            self.run_round(state, live=True)

    def test_mandatory_backcheck_and_no_false_consensus(self):
        state = self.init()
        e.new_round(self.session, state, "test")
        self.run_round(state)
        bad = judgment(state)
        bad["unresolved_objections"] = ["still disputed"]
        with self.assertRaises(DebateError):
            e.decide(self.session, state, bad)
        e.decide(self.session, state, judgment(state))
        e.new_round(self.session, state, "L2")
        self.run_round(state)
        bad = judgment(state)
        bad["backcheck"] = []
        with self.assertRaises(DebateError):
            e.decide(self.session, state, bad)
        e.decide(self.session, state, judgment(state))
        self.assertEqual(state["level_index"], 2)

    def test_level_round_cap(self):
        state = self.init()
        for i in range(4):
            e.new_round(self.session, state, "question", "independent" if i == 0 else "exchange")
            self.run_round(state)
            if i < 3:
                e.decide(self.session, state, judgment(state, "continue"))
        with self.assertRaises(DebateError):
            e.decide(self.session, state, judgment(state, "continue"))
        e.decide(self.session, state, judgment(state, "adjudicated"))

    def test_user_intervention_round_boundary(self):
        state = self.init()
        e.new_round(self.session, state, "question")
        with self.assertRaises(DebateError):
            e.intervene(self.session, state, "new constraint")
        self.run_round(state)
        e.intervene(self.session, state, "new constraint")
        e.decide(self.session, state, judgment(state, "continue"))
        e.new_round(self.session, state, "question", "exchange")
        for job in state["rounds"][-1]["jobs"].values():
            self.assertIn("new constraint", job["prompt"])

    def test_compaction_retains_archive_and_private_summaries(self):
        state = self.init()
        for i in range(3):
            e.new_round(self.session, state, "question", "independent" if i == 0 else "exchange")
            self.run_round(state)
            e.decide(self.session, state, judgment(state, "continue"))
        before = copy.deepcopy(state["histories"])
        e.compact(self.session, state, {"reason": "test", "summaries": {"a": "A-PRIVATE-SUMMARY", "b": "B-PRIVATE-SUMMARY"}})
        self.assertEqual(before, state["histories"])
        e.new_round(self.session, state, "question", "exchange")
        for pid, j in state["rounds"][-1]["jobs"].items():
            self.assertEqual(len(j["history"]), 4)
            self.assertIn(pid.upper() + "-PRIVATE-SUMMARY", j["system"])
            self.assertNotIn(("B" if pid == "a" else "A") + "-PRIVATE-SUMMARY", j["system"])

    def test_output_truncation_is_not_a_success(self):
        for provider, response in [
            ("anthropic", {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "partial"}]}),
            ("grok", {"status": "incomplete", "output": []}),
            ("qwen", {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}),
        ]:
            with self.assertRaises(RequestFailure):
                Adapter(member("a", provider), None).parse(response)

    def test_secrets_redacted_from_response_and_history(self):
        state = self.init()
        secret = "test-secret-not-real-0921"
        Recording.texts = {"a": secret, "b": secret}
        e.new_round(self.session, state, "test")
        with patch.dict(os.environ, {"DEBATE_TEST_KEY": secret}):
            self.run_round(state)
        for f in self.session.rglob("*.json"):
            self.assertNotIn(secret, f.read_text())

    def test_env_is_not_executed(self):
        path = self.root / "keys.env"
        marker = self.root / "must-not-exist"
        path.write_text("DEBATE_TEST_ENV=$(touch " + str(marker) + ")\n")
        path.chmod(0o600)
        with patch.dict(os.environ, {}, clear=True):
            e.load_env(path)
            self.assertTrue(os.environ["DEBATE_TEST_ENV"].startswith("$(touch"))
        self.assertFalse(marker.exists())

    def test_lock_prevents_concurrent_mutation(self):
        self.init()
        with e.locked(self.session):
            with self.assertRaises(DebateError):
                with e.locked(self.session):
                    pass

    def test_full_lifecycle_and_final_report(self):
        state = self.init()
        for _ in range(5):
            e.new_round(self.session, state, "independent")
            self.run_round(state)
            e.decide(self.session, state, judgment(state, "continue"))
            e.new_round(self.session, state, "cross review", "exchange")
            self.run_round(state)
            e.decide(self.session, state, judgment(state))
        e.finalize(self.session, state, "MOCK final report")
        restored = e.read_json(self.session / "state.json")
        self.assertEqual(restored["status"], "completed")
        self.assertEqual(len(restored["rounds"]), 10)
        self.assertIn("MOCK final report", (self.session / "discussion.md").read_text())

    def test_all_adapter_request_shapes(self):
        for provider in ("anthropic", "openai", "grok", "qwen", "kimi", "deepseek"):
            p = member("a", provider)
            e.validate_participant(p)
            ref = {"file_id": "file-a", "name": "image.png" if provider == "deepseek" else "report.pdf", "vendor_content": "KIMI-DATA"}
            path, body = Adapter(p, None).build("sys", [{"role": "user", "text": "old"}, {"role": "assistant", "text": "answer"}], "new", [ref])
            self.assertEqual(body["model"], p["model"])
            if provider == "kimi":
                self.assertIn("KIMI-DATA", json.dumps(body))
            else:
                self.assertIn("file-a", json.dumps(body))
            self.assertIn("answer", json.dumps(body))

    def test_final_only_retains_latest_level_objections(self):
        state = self.init()
        e.new_round(self.session, state, "independent")
        self.run_round(state)
        decision = judgment(state, "continue")
        decision["unresolved_objections"] = ["later resolved"]
        e.decide(self.session, state, decision)
        e.new_round(self.session, state, "resolve", "exchange")
        self.run_round(state)
        e.decide(self.session, state, judgment(state))
        e.new_round(self.session, state, "L2")
        self.run_round(state)
        decision = judgment(state, "adjudicated")
        decision["unresolved_objections"] = ["still unresolved"]
        e.decide(self.session, state, decision)
        e.finalize(self.session, state, "test conclusion", "stop early in test")
        self.assertEqual(state["final"]["unresolved"], [{"level": "L2", "objection": "still unresolved"}])
        report = (self.session / "discussion.md").read_text()
        self.assertIn("各层最后判定仍保留的异议", report)
        self.assertIn("服务返回模型", report)


class HTTPTests(unittest.TestCase):
    def test_multipart_contains_exact_original_bytes_and_auth(self):
        captured = {}
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured["body"] = self.rfile.read(int(self.headers["Content-Length"]))
                captured["auth"] = self.headers.get("Authorization")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id":"file-local-test"}')
            def log_message(self, *args):
                pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            http = HTTP("http://127.0.0.1:" + str(server.server_port), "fake-key", "qwen", allow_local=True)
            raw = b"%PDF-1.7\x00\xff\r\nnot extracted"
            result = http.request("POST", "/files", multipart=("原件.pdf", raw, "application/pdf", {"purpose": "file-extract"}))
            self.assertEqual(result["id"], "file-local-test")
            self.assertIn(raw, captured["body"])
            self.assertEqual(captured["auth"], "Bearer fake-key")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class TokenHubTests(unittest.TestCase):
    setUp = DebateTests.setUp
    tearDown = DebateTests.tearDown
    init = DebateTests.init
    run_round = DebateTests.run_round
    def tokenhub(self):
        p = member("a", "tokenhub")
        p.update(model="hy4-preview", base_url="https://tokenhub.tencentmaas.com/v1", api_key_env="TOKENHUB_TEST_KEY",
                 thcli_key={"profile": "default", "site": "cn", "area": "gz", "alias": "default"})
        return p

    def test_thcli_key_resolution_does_not_persist_or_expose_secret(self):
        p = self.tokenhub()
        secret = "fake-tokenhub-key-for-test"
        folder = self.root / ".thcli"
        folder.mkdir()
        key_file = folder / "default.tokenhub.json"
        key_file.write_text(json.dumps({"sites": {"cn": {"gz": {"th": {"default": secret}}}}}))
        key_file.chmod(0o600)
        state = self.init([p, member("b")], mock=False, files=False)
        e.new_round(self.session, state, "test")
        Recording.texts = {"a": secret}
        with patch('credentials.Path.home', return_value=self.root), patch.dict(os.environ, {"DEBATE_TEST_KEY": "fake-official-key"}, clear=True):
            self.assertEqual(resolve_key(p), secret)
            self.assertEqual(resolve_key(member("b")), "fake-official-key")
            self.assertTrue(e.preflight(state, True)["ok"])
            self.assertEqual(e.run_round(self.session, state, live=True, transport_factory=Recording)["status"], "complete")
            with patch.dict(os.environ, {"TOKENHUB_TEST_KEY": "env-override"}):
                self.assertEqual(resolve_key(p), "env-override")
        for path in self.session.rglob('*.json'):
            self.assertNotIn(secret, path.read_text())
        self.assertEqual(json.loads(key_file.read_text())["sites"]["cn"]["gz"]["th"]["default"], secret)

    def test_thcli_endpoint_binding_and_wrong_provider_rejected(self):
        for field, value in [("base_url", "https://unrelated.invalid/v1"), ("provider", "deepseek")]:
            p = self.tokenhub()
            p[field] = value
            with self.assertRaises(DebateError):
                validate_source(p)

    def test_missing_cli_alias_and_insecure_file_fail_locally(self):
        p = self.tokenhub()
        folder = self.root / ".thcli"
        folder.mkdir()
        path = folder / 'default.tokenhub.json'
        path.write_text('{"sites": {}}')
        path.chmod(0o600)
        with patch('credentials.Path.home', return_value=self.root), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_key(p), "")
            path.chmod(0o644)
            with self.assertRaises(DebateError):
                resolve_key(p)

    def test_tokenhub_pdf_fails_before_network_and_cannot_bypass_build(self):
        p = self.tokenhub()
        state = self.init([p, member("b")])
        e.new_round(self.session, state, "test")
        with self.assertRaises(DebateError):
            self.run_round(state)
        self.assertEqual(Recording.records, [])
        with self.assertRaises(DebateError):
            Adapter(p, None).build('sys', [], 'question', [{"file_id": "file-a"}])

    def test_tokenhub_three_models_keep_independent_two_round_histories(self):
        participants = []
        for pid, model in [('a', 'hy4-preview'), ('b', 'glm-5.3-flash'), ('c', 'mimo-v2.6-pro')]:
            p = self.tokenhub()
            p.update(id=pid, model=model)
            participants.append(p)
        state = self.init(participants, files=False)
        e.new_round(self.session, state, 'first')
        self.run_round(state)
        e.decide(self.session, state, judgment(state, 'continue'))
        e.new_round(self.session, state, 'second', 'exchange')
        self.run_round(state)
        for pid in ('a', 'b', 'c'):
            bodies = [r[3] for r in Recording.records if r[0] == pid and r[3]]
            self.assertEqual(len(bodies), 2)
            assistants = [m['content'] for m in bodies[1]['messages'] if m['role'] == 'assistant']
            self.assertEqual(assistants, ['PRIVATE-' + pid])


if __name__ == "__main__":
    unittest.main()
