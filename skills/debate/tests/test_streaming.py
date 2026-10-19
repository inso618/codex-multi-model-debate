import contextlib
import copy
import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import engine as e
from providers import Adapter, ChatStream, DebateError, HTTP, MockHTTP, RequestFailure
import test_debate as fixtures
from test_debate import judgment, member


def event(delta=None, finish=None, usage=None):
    return {"id": "response-1", "model": "kimi-k3", "choices": [] if usage else [
        {"index": 0, "delta": delta or {}, "finish_reason": finish}], **({"usage": usage} if usage else {})}


def wire(value):
    return ("data: " + json.dumps(value, ensure_ascii=False) + "\r\n\r\n").encode()


@contextlib.contextmanager
def server(parts, content_type="text/event-stream"):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            try:
                for delay, data in parts:
                    time.sleep(delay)
                    self.wfile.write(data)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(srv.server_port)
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join()


class StreamTests(unittest.TestCase):
    def test_utf8_fragmentation_full_message_usage_and_finish(self):
        events = [event({"role": "assistant", "reasoning_content": "私有"}),
                  event({"reasoning_content": "上下文", "vendor_info": {"signature": "signed"}}),
                  event({"content": "正式"}), event({"content": "回答"}, "stop"),
                  event(usage={"total_tokens": 99})]
        parser = ChatStream()
        data = b": heartbeat\r\n\r\n" + b"".join(wire(v) for v in events) + b"data: [DONE]\r\n\r\n"
        for byte in data:
            parser.feed(bytes([byte]))
        result = parser.finish()
        message = result["choices"][0]["message"]
        self.assertEqual(message["content"], "正式回答")
        self.assertEqual(message["reasoning_content"], "私有上下文")
        self.assertEqual(message["vendor_info"], {"signature": "signed"})
        self.assertEqual(result["usage"]["total_tokens"], 99)

    def test_stream_error_and_missing_done_are_uncertain(self):
        parser = ChatStream()
        parser.feed(wire(event({"content": "partial"}, "stop")))
        with self.assertRaises(RequestFailure) as failure:
            parser.finish()
        self.assertTrue(failure.exception.uncertain)
        with self.assertRaises(RequestFailure):
            ChatStream().feed(wire({"error": {"message": "upstream"}}))

    def test_sse_length_finish_is_not_accepted(self):
        parser = ChatStream()
        parser.feed(wire(event({"content": "cut"}, "length")) + b"data: [DONE]\n\n")
        with self.assertRaises(RequestFailure):
            Adapter(member("a", "tokenhub"), None).parse(parser.finish())

    def test_live_http_delivers_events_before_completion(self):
        seen = []
        parts = [(0, wire(event({"reasoning_content": "private"}))),
                 (.08, wire(event({"content": "answer"}, "stop"))),
                 (.08, wire(event(usage={"total_tokens": 5})) + b"data: [DONE]\n\n")]
        with server(parts) as url:
            http = HTTP(url, "test", "tokenhub", timeout=2, allow_local=True)
            http.on_event = lambda ev: seen.append(time.monotonic())
            response = http.request("POST", "/chat/completions", {"stream": True})
            self.assertEqual(response["choices"][0]["message"]["content"], "answer")
            self.assertLess(seen[0], seen[-1] - .1)
            self.assertLess(http.metrics["first_token_seconds"], http.metrics["elapsed_seconds"])

    def test_total_deadline_not_reset_by_heartbeats(self):
        with server([(.03, b": ping\n\n")] * 30) as url:
            http = HTTP(url, "test", "tokenhub", timeout=.2, allow_local=True)
            with self.assertRaises(RequestFailure) as failure:
                http.request("POST", "/chat/completions", {"stream": True})
            self.assertTrue(failure.exception.uncertain)
            self.assertLess(http.metrics["elapsed_seconds"], .6)

    def test_idle_timeout_retains_received_event(self):
        seen = []
        with server([(0, wire(event({"content": "partial"}))), (.3, b"data: [DONE]\n\n")]) as url:
            http = HTTP(url, "test", "tokenhub", timeout=2, idle_timeout=.08, allow_local=True)
            http.on_event = seen.append
            with self.assertRaises(RequestFailure) as failure:
                http.request("POST", "/chat/completions", {"stream": True})
            self.assertIn("阶段=stream", str(failure.exception))
            self.assertEqual(len(seen), 1)

    def test_nonstream_http_compatibility(self):
        with server([(0, b'{"ok":true}')], "application/json") as url:
            self.assertEqual(HTTP(url, "test", "deepseek", allow_local=True).request("POST", "/test", {}), {"ok": True})

    def test_kimi_model_specific_parameters(self):
        p = member("a", "tokenhub")
        p["model"] = "kimi-k3"
        body = Adapter(p, None).build("system", [], "question", [])[1]
        self.assertEqual(body["max_completion_tokens"], p["max_output_tokens"])
        self.assertNotIn("max_tokens", body)
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertTrue(body["stream"])
        for generation in ({"thinking": {"type": "disabled"}}, {"reasoning_effort": "medium"},
                           {"temperature": .5}, {"max_completion_tokens": 10}):
            with self.assertRaises(DebateError):
                Adapter({**p, "generation": generation}, None).build("system", [], "question", [])


class HistoryTests(unittest.TestCase):
    def test_interrupted_stream_persists_partial_without_committing_history(self):
        fixture = fixtures.DebateTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        state = fixture.init([member("a", "tokenhub"), member("b", "tokenhub")], files=False)
        e.new_round(fixture.session, state, "independent")
        with server([(0, wire(event({"content": "partial"})))]) as url:
            with contextlib.redirect_stderr(__import__('io').StringIO()):
                result = e.run_round(fixture.session, state, transport_factory=lambda p: HTTP(url, "test", "tokenhub", allow_local=True))
        self.assertEqual(result["status"], "open")
        self.assertTrue(all(j == "uncertain" for j in result["jobs"].values()))
        self.assertEqual(state["histories"], {"a": [], "b": []})
        self.assertEqual(len(list((fixture.session / "responses").glob("*.stream.jsonl"))), 2)
        for f in (fixture.session / "responses").glob("*.stream.jsonl"):
            self.assertIn("partial", f.read_text())
            self.assertEqual(f.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(DebateError):
            e.new_round(fixture.session, state, "review", "exchange")

    def test_restart_replays_full_private_assistant_without_peer_leak(self):
        fixture = fixtures.DebateTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        state = fixture.init([member("a", "tokenhub"), member("b", "tokenhub")], files=False)

        class Thinking(MockHTTP):
            def request(self, *args, **kwargs):
                result = super().request(*args, **kwargs)
                message = result["choices"][0]["message"]
                message["reasoning_content"] = "SECRET-" + self.participant["id"]
                message["vendor_info"] = {"signature": "sig-" + self.participant["id"]}
                return result

        e.new_round(fixture.session, state, "independent")
        e.run_round(fixture.session, state, transport_factory=Thinking)
        state = e.read_json(fixture.session / "state.json")
        e.decide(fixture.session, state, judgment(state, "continue"))
        e.new_round(fixture.session, state, "review", "exchange")
        for p in state["participants"]:
            pid = p["id"]
            job = state["rounds"][-1]["jobs"][pid]
            body = Adapter(p, None).build(job["system"], job["history"], job["prompt"], [])[1]
            messages = [m for m in body["messages"] if m["role"] == "assistant"]
            original = state["rounds"][0]["jobs"][pid]["result"]["assistant_message"]
            self.assertEqual(messages, [original])
            self.assertNotIn("SECRET-", job["prompt"])
        self.assertNotIn("SECRET-", (fixture.session / "discussion.md").read_text())


if __name__ == "__main__":
    unittest.main()
