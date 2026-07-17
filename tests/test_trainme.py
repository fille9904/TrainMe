from __future__ import annotations

import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode


TEST_DIR = tempfile.TemporaryDirectory()
os.environ["TRAINME_DB_PATH"] = str(Path(TEST_DIR.name) / "trainme-test.db")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("OPENAI_API_KEY", None)

from app import ai_coach  # noqa: E402
from app.db import ensure_db, query_all, query_one  # noqa: E402
from app.main import TrainMeHandler  # noqa: E402


class FakeOpenAIResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {
                "output": [
                    {"content": [{"type": "output_text", "text": "Use an easy recovery run tomorrow."}]}
                ]
            }
        ).encode("utf-8")


class TrainMeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_db()
        cls.start_server()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stop_server()
        TEST_DIR.cleanup()

    @classmethod
    def start_server(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), TrainMeHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def stop_server(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, method: str, path: str, data: dict[str, str] | None = None, cookie: str = ""):
        body = urlencode(data or {})
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if cookie:
            headers["Cookie"] = cookie
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=body if method == "POST" else None, headers=headers)
        response = connection.getresponse()
        content = response.read().decode("utf-8")
        result = (response.status, dict(response.getheaders()), content)
        connection.close()
        return result

    def test_account_persists_logout_works_and_categories_are_ordered(self) -> None:
        status, _, home = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertLess(home.index("Open Getting started"), home.index("Open Active"))
        self.assertLess(home.index("Open Active"), home.index("Open Athlete"))

        status, headers, _ = self.request(
            "POST",
            "/registrera",
            {
                "username": "persistent-user",
                "email": "persistent@example.com",
                "password": "correct-password",
                "category": "komma-igang",
                "height": "181",
                "weight": "82.5",
                "goal": "Build a lasting routine",
            },
        )
        self.assertEqual(status, 303)
        cookie = headers["Set-Cookie"].split(";", 1)[0]

        status, _, signed_in_page = self.request("GET", "/spar/komma-igang", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertNotIn("{csrf_input(user)}", signed_in_page)
        self.assertIn('name="csrf_token"', signed_in_page)

        status, _, coach_page = self.request("GET", "/ai-coach", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn('action="/ai-chat"', coach_page)
        self.assertIn("AI coach for Getting started", coach_page)

        user = query_one("SELECT * FROM users WHERE email = ?", ("persistent@example.com",))
        self.assertIsNotNone(user)
        self.assertEqual(user["category"], "komma-igang")
        self.assertEqual(user["goal"], "Build a lasting routine")
        self.assertEqual(float(user["weight"]), 82.5)
        weights = query_all("SELECT * FROM weight_entries WHERE user_id = ?", (user["id"],))
        self.assertEqual(len(weights), 1)

        status, headers, _ = self.request("POST", "/logga-ut", cookie=cookie)
        self.assertEqual(status, 303)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertIsNone(query_one("SELECT * FROM sessions WHERE token = ?", (cookie.split("=", 1)[1],)))

        self.stop_server()
        self.start_server()
        status, headers, _ = self.request(
            "POST",
            "/logga-in",
            {"email": "persistent@example.com", "password": "correct-password"},
        )
        self.assertEqual(status, 303)
        restarted_cookie = headers["Set-Cookie"].split(";", 1)[0]
        status, _, profile = self.request("GET", "/profile", cookie=restarted_cookie)
        self.assertEqual(status, 200)
        self.assertIn("persistent-user", profile)
        self.assertIn("Build a lasting routine", profile)
        self.assertIn("82.5", profile)

    def test_ai_coach_uses_api_and_has_safe_fallback(self) -> None:
        user = query_one("SELECT * FROM users WHERE email = ?", ("persistent@example.com",))
        self.assertIsNotNone(user)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch.object(
            ai_coach, "urlopen", return_value=FakeOpenAIResponse()
        ) as mocked_urlopen:
            answer = ai_coach.generate_coach_reply(
                user,
                "How should I recover?",
                "5 km, 30 min, 350 kcal burned",
            )
        self.assertEqual(answer, "Use an easy recovery run tomorrow.")
        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertIn("350 kcal burned", payload["input"])
        self.assertIn("How should I recover?", payload["input"])

        with patch.dict(os.environ, {}, clear=True):
            fallback = ai_coach.generate_coach_reply(user, "What does my pace mean?", "5:45 min/km")
        self.assertIn("Strava tempo and kcal data", fallback)


if __name__ == "__main__":
    unittest.main()
