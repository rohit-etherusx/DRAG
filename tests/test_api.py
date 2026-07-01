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
