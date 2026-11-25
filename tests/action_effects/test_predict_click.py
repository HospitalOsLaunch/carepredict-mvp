import io
import json
import unittest
from unittest.mock import patch

from scripts.computer_use.predict_click import DEMO, MODEL, predict_click


class ExternalClickTests(unittest.TestCase):
    @patch("scripts.computer_use.predict_click.urlopen")
    def test_request_and_hypothetical_response(self, post):
        content = "<predicted_observation>[1] checkbox checked</predicted_observation>"
        choice = {"finish_reason": "stop", "message": {"content": content}}
        reply = {"model": MODEL, "choices": [choice]}
        post.return_value = io.BytesIO(json.dumps(reply).encode())
        result = predict_click("http://localhost:8000/v1", DEMO, "1")
        request = post.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:8000/v1/chat/completions")
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], MODEL)
        self.assertIn(DEMO, payload["messages"][1]["content"])
        self.assertIn('click(bid="1")', payload["messages"][1]["content"])
        self.assertEqual(result["kind"], "simulated_ui_state")
        self.assertEqual(result["predicted_observation"], "[1] checkbox checked")

    @patch("scripts.computer_use.predict_click.urlopen")
    def test_invalid_response(self, post):
        valid = "<predicted_observation>page</predicted_observation>"
        for model, reason, content in (
            (MODEL, "length", valid), ("other", "stop", valid), (MODEL, "stop", ""),
            (MODEL, "stop", valid + valid),
        ):
            with self.subTest(model=model, reason=reason, content=content):
                choice = {"finish_reason": reason, "message": {"content": content}}
                reply = {"model": model, "choices": [choice]}
                post.return_value = io.BytesIO(json.dumps(reply).encode())
                with self.assertRaises(ValueError):
                    predict_click("http://localhost:8000/v1", DEMO, "1")
