import unittest

from tests import _path  # noqa: F401

try:
    from fastapi.testclient import TestClient

    from research_engine.api import create_app

    _HAS_FASTAPI = True
except ImportError:  # the 'api' extra isn't installed
    _HAS_FASTAPI = False


@unittest.skipUnless(_HAS_FASTAPI, "requires the 'api' extra (fastapi)")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app())

    def test_health(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_research_offline_returns_session_json(self):
        # offline + no_llm => deterministic, no network, no API key needed.
        resp = self.client.post(
            "/research",
            json={
                "topic": "Renewable Energy",
                "max_subtopics": 2,
                "offline": True,
                "no_llm": True,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["request"]["topic"], "Renewable Energy")
        self.assertTrue(data["evidence"])
        self.assertTrue(data["findings"])
        self.assertIn("markdown", data["report"])
        self.assertIn("# Research Report: Renewable Energy", data["report"]["markdown"])

    def test_research_stream_emits_events_then_session(self):
        # The SSE stream should carry progress frames and end with the full
        # session. Offline + no_llm keeps it deterministic and network-free.
        import json

        with self.client.stream(
            "POST",
            "/research/stream",
            json={
                "topic": "Renewable Energy",
                "max_subtopics": 2,
                "offline": True,
                "no_llm": True,
            },
        ) as resp:
            self.assertEqual(resp.status_code, 200)
            self.assertIn("text/event-stream", resp.headers["content-type"])
            payloads = []
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    payloads.append(json.loads(line[len("data: "):]))

        types = [p["type"] for p in payloads]
        self.assertIn("SessionStarted", types)
        self.assertIn("PlanReady", types)
        self.assertIn("SessionComplete", types)
        # SessionComplete carries the full serialized session for the UI.
        final = next(p for p in payloads if p["type"] == "SessionComplete")
        session = final["session"]
        self.assertEqual(session["status"], "completed")
        self.assertIn("markdown", session["report"])
        # The terminal Done frame closes the stream.
        self.assertEqual(types[-1], "Done")

    def test_stream_error_frame_on_bad_request(self):
        # A whitespace-only topic passes Pydantic (min_length on the raw string)
        # but the engine rejects it — surfaced as an in-band Error frame, not a
        # broken stream.
        import json

        with self.client.stream(
            "POST", "/research/stream", json={"topic": "   ", "offline": True, "no_llm": True}
        ) as resp:
            self.assertEqual(resp.status_code, 200)
            payloads = [
                json.loads(line[len("data: "):])
                for line in resp.iter_lines()
                if line.startswith("data: ")
            ]
        types = [p["type"] for p in payloads]
        self.assertIn("Error", types)
        err = next(p for p in payloads if p["type"] == "Error")
        self.assertEqual(err["status"], 400)

    def test_empty_topic_is_rejected(self):
        # Pydantic validation (min_length=1) -> 422 unprocessable entity.
        resp = self.client.post("/research", json={"topic": ""})
        self.assertEqual(resp.status_code, 422)

    def test_out_of_range_subtopics_rejected(self):
        resp = self.client.post(
            "/research", json={"topic": "X", "max_subtopics": 99}
        )
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
