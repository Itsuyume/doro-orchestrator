import json
import unittest

from doro.domain.models import DoroError
from doro.domain.models import PlannedTurn, Session, Turn
from doro.domain.policy import ensure_public, plan_turns
from doro.domain.validation import parse_task
from doro.application.prompts import build_prompt


def public_task(message: str = "Review a public sorting example.") -> dict[str, object]:
    return {"message": message, "classification": "public",
            "allowed_providers": ["codex", "claude"], "context": ""}


class PrivacyTests(unittest.TestCase):
    def test_empty_null_and_unknown_task_fields_are_rejected(self) -> None:
        for value in (None, {}, public_task(""), {**public_task(), "files": ["secret"]}):
            with self.subTest(value=value), self.assertRaises(DoroError):
                parse_task(value)

    def test_private_input_and_credentials_never_leave_policy(self) -> None:
        dangerous = ("sk-" + "x" * 30, "ghp_" + "x" * 36,
                     "api_key=exampleSecretValue", "-----BEGIN PRIVATE KEY-----",
                     "/Users/example/private/notes.md", "person@example.com")
        for text in dangerous:
            with self.subTest(text=text), self.assertRaises(DoroError):
                ensure_public(text)
        with self.assertRaises(DoroError):
            parse_task({**public_task(), "classification": "private"})

    def test_task_is_only_explicit_text_without_file_collection(self) -> None:
        task = parse_task(public_task())
        self.assertEqual(task.message, "Review a public sorting example.")
        self.assertEqual(task.allowed_providers, ("codex", "claude"))
        self.assertEqual(task.context, "")
        self.assertNotIn("files", json.dumps(task.to_dict()))

    def test_serialized_python_decorators_are_not_mistaken_for_email(self) -> None:
        text = "```python\n@pytest.mark.parametrize('x', [1])\ndef test_x(x): pass\n```"
        ensure_public(text)
        session = Session("test", parse_task(public_task()), "fingerprint", ("codex", "claude"), 2)
        session.turns.append(Turn("codex", "draft", text, 1, None, "native"))
        prompt = build_prompt(session, PlannedTurn("claude", "review"), "Reviewer", 24000)
        self.assertIn("pytest.mark.parametrize", prompt)
        session.turns[-1] = Turn("codex", "draft", "contact person@example.com", 1, None, "native")
        with self.assertRaises(DoroError):
            build_prompt(session, PlannedTurn("claude", "review"), "Reviewer", 24000)

    def test_disabled_agy_is_not_in_any_turn_and_gpt_owns_final(self) -> None:
        turns = plan_turns(("codex", "claude"), rounds=2)
        self.assertEqual([t.provider for t in turns],
                         ["codex", "claude", "codex", "claude", "codex"])
        self.assertEqual(turns[-1].phase, "final")
        self.assertNotIn("agy", [t.provider for t in turns])


if __name__ == "__main__":
    unittest.main()
