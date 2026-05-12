"""Unit tests for dream.py — auth backend selection and CLI call path."""

import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to import the module without a live Neo4j connection
# ---------------------------------------------------------------------------
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import dream as dream_mod  # noqa: E402


# ---------------------------------------------------------------------------
# _resolve_auth
# ---------------------------------------------------------------------------
class TestResolveAuth:
    def test_flag_sdk(self, monkeypatch):
        monkeypatch.delenv("DREAM_AUTH", raising=False)
        assert dream_mod._resolve_auth("sdk") == "sdk"

    def test_flag_cli(self, monkeypatch):
        monkeypatch.delenv("DREAM_AUTH", raising=False)
        assert dream_mod._resolve_auth("cli") == "cli"

    def test_flag_overrides_env(self, monkeypatch):
        monkeypatch.setenv("DREAM_AUTH", "sdk")
        assert dream_mod._resolve_auth("cli") == "cli"

    def test_env_used_when_no_flag(self, monkeypatch):
        monkeypatch.setenv("DREAM_AUTH", "cli")
        assert dream_mod._resolve_auth("") == "cli"

    def test_default_is_sdk(self, monkeypatch):
        monkeypatch.delenv("DREAM_AUTH", raising=False)
        assert dream_mod._resolve_auth("") == "sdk"

    def test_invalid_flag_raises(self, monkeypatch):
        monkeypatch.delenv("DREAM_AUTH", raising=False)
        with pytest.raises(SystemExit, match="must be 'sdk' or 'cli'"):
            dream_mod._resolve_auth("banana")

    def test_invalid_env_raises(self, monkeypatch):
        monkeypatch.setenv("DREAM_AUTH", "banana")
        with pytest.raises(SystemExit, match="must be 'sdk' or 'cli'"):
            dream_mod._resolve_auth("")


# ---------------------------------------------------------------------------
# _find_claude_cli
# ---------------------------------------------------------------------------
class TestFindClaudeCli:
    def test_explicit_env_var(self, monkeypatch):
        monkeypatch.setenv("DREAM_CLAUDE_BIN", "/custom/claude")
        assert dream_mod._find_claude_cli() == "/custom/claude"

    def test_falls_back_to_which(self, monkeypatch):
        monkeypatch.delenv("DREAM_CLAUDE_BIN", raising=False)
        with patch("dream.shutil.which", return_value="/usr/bin/claude"):
            assert dream_mod._find_claude_cli() == "/usr/bin/claude"

    def test_raises_when_not_found(self, monkeypatch):
        monkeypatch.delenv("DREAM_CLAUDE_BIN", raising=False)
        with patch("dream.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="claude CLI binary was found"):
                dream_mod._find_claude_cli()


# ---------------------------------------------------------------------------
# _parse_memories
# ---------------------------------------------------------------------------
class TestParseMemories:
    def test_valid_json(self):
        text = '{"memories": [{"path": "p.md", "content": "c"}]}'
        result = dream_mod._parse_memories(text)
        assert result == [{"path": "p.md", "content": "c"}]

    def test_json_embedded_in_prose(self):
        text = 'Here you go:\n{"memories": []} done.'
        assert dream_mod._parse_memories(text) == []

    def test_empty_memories_list(self):
        assert dream_mod._parse_memories('{"memories": []}') == []

    def test_no_json_raises(self):
        with pytest.raises(ValueError, match="no JSON"):
            dream_mod._parse_memories("no json here")


# ---------------------------------------------------------------------------
# _build_user_msg
# ---------------------------------------------------------------------------
def test_build_user_msg():
    msg = dream_mod._build_user_msg("T", "E")
    assert "<existing_memories>" in msg
    assert "<events>" in msg
    assert "T" in msg
    assert "E" in msg


# ---------------------------------------------------------------------------
# _call_claude_cli
# ---------------------------------------------------------------------------
class TestCallClaudeCli:
    def _make_result(self, stdout, returncode=0):
        return SimpleNamespace(stdout=stdout, returncode=returncode, stderr="")

    def test_success(self, monkeypatch):
        payload = '{"memories": [{"path": "a.md", "content": "b"}]}'
        monkeypatch.setenv("DREAM_CLAUDE_BIN", "/fake/claude")
        with patch("dream.subprocess.run", return_value=self._make_result(payload)) as mock_run:
            result = dream_mod._call_claude_cli("transcript", "existing")
        assert result == [{"path": "a.md", "content": "b"}]
        call_args = mock_run.call_args
        # prompt must NOT appear in argv (stdin path)
        argv = call_args[0][0]
        assert "transcript" not in argv
        assert "existing" not in argv
        # user message must be piped via input=
        assert "transcript" in call_args.kwargs.get("input", "")

    def test_non_zero_exit_raises_with_stderr(self, monkeypatch):
        monkeypatch.setenv("DREAM_CLAUDE_BIN", "/fake/claude")
        with patch("dream.subprocess.run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="boom")):
            with pytest.raises(RuntimeError, match="boom"):
                dream_mod._call_claude_cli("t", "e")

    def test_non_zero_exit_falls_back_to_stdout(self, monkeypatch):
        monkeypatch.setenv("DREAM_CLAUDE_BIN", "/fake/claude")
        with patch("dream.subprocess.run", return_value=SimpleNamespace(returncode=1, stdout="out-msg", stderr="")):
            with pytest.raises(RuntimeError, match="out-msg"):
                dream_mod._call_claude_cli("t", "e")


# ---------------------------------------------------------------------------
# _call_claude_sdk
# ---------------------------------------------------------------------------
class TestCallClaudeSdk:
    def test_success(self):
        fake_block = SimpleNamespace(type="text", text='{"memories": []}')
        fake_msg = SimpleNamespace(content=[fake_block])
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_msg
        result = dream_mod._call_claude_sdk(fake_client, "transcript", "existing")
        assert result == []

    def test_passes_system_prompt(self):
        fake_block = SimpleNamespace(type="text", text='{"memories": []}')
        fake_msg = SimpleNamespace(content=[fake_block])
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_msg
        dream_mod._call_claude_sdk(fake_client, "t", "e")
        _, kwargs = fake_client.messages.create.call_args
        system = kwargs.get("system") or fake_client.messages.create.call_args[1]["system"]
        assert any(dream_mod.SYSTEM_PROMPT in block["text"] for block in system)


# ---------------------------------------------------------------------------
# call_claude dispatch
# ---------------------------------------------------------------------------
class TestCallClaudeDispatch:
    def test_uses_sdk_when_client_provided(self):
        with patch("dream._call_claude_sdk", return_value=[]) as sdk_mock:
            with patch("dream._call_claude_cli") as cli_mock:
                dream_mod.call_claude(MagicMock(), "t", "e")
        sdk_mock.assert_called_once()
        cli_mock.assert_not_called()

    def test_uses_cli_when_client_is_none(self):
        with patch("dream._call_claude_sdk") as sdk_mock:
            with patch("dream._call_claude_cli", return_value=[]) as cli_mock:
                dream_mod.call_claude(None, "t", "e")
        cli_mock.assert_called_once()
        sdk_mock.assert_not_called()


# ---------------------------------------------------------------------------
# main — argument parsing / early exits
# ---------------------------------------------------------------------------
class TestMainEarlyExits:
    def test_sdk_without_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("sys.argv", ["dream.py", "--auth", "sdk"]):
            with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY is not set"):
                dream_mod.main()

    def test_invalid_auth_exits(self, monkeypatch):
        monkeypatch.delenv("DREAM_AUTH", raising=False)
        with patch("sys.argv", ["dream.py", "--auth", "bad"]):
            with pytest.raises(SystemExit):
                dream_mod.main()

    def test_cli_validates_binary_before_db(self, monkeypatch):
        monkeypatch.delenv("DREAM_CLAUDE_BIN", raising=False)
        with patch("sys.argv", ["dream.py", "--auth", "cli"]):
            with patch("dream.shutil.which", return_value=None):
                # Should raise on missing binary, never reaching get_driver()
                with patch("dream.get_driver") as mock_driver:
                    with pytest.raises(RuntimeError, match="claude CLI binary was found"):
                        dream_mod.main()
                mock_driver.assert_not_called()


# ---------------------------------------------------------------------------
# --max-events / DREAM_MAX_EVENTS
# ---------------------------------------------------------------------------
def _make_main_mocks(monkeypatch, argv, sessions, *, auth="cli", claude_bin="/fake/claude"):
    """Patch everything external so main() runs fully in memory."""
    monkeypatch.setenv("DREAM_CLAUDE_BIN", claude_bin)

    fake_driver = MagicMock()
    fake_driver.__enter__ = lambda s: s
    fake_driver.__exit__ = MagicMock(return_value=False)

    with patch("sys.argv", argv), \
         patch("dream.get_driver", return_value=fake_driver), \
         patch("dream.fetch_events", return_value=sessions), \
         patch("dream.fetch_existing_memories", return_value=[]), \
         patch("dream.call_claude", return_value=[]) as mock_call, \
         patch("dream.write_memories", return_value=0) as mock_write:
        dream_mod.main()

    return mock_call, mock_write


class TestMaxEvents:
    def _events(self, n):
        return [{"timestamp": f"2026-01-01T00:00:0{i}.000Z", "event_name": "Stop"} for i in range(n)]

    def test_session_under_limit_is_processed(self, monkeypatch, capsys):
        sessions = [("ses-small", self._events(5))]
        mock_call, mock_write = _make_main_mocks(
            monkeypatch,
            ["dream.py", "--auth", "cli", "--max-events", "10"],
            sessions,
        )
        mock_call.assert_called_once()
        mock_write.assert_called_once()

    def test_session_over_limit_is_skipped(self, monkeypatch, capsys):
        sessions = [("ses-big", self._events(50))]
        mock_call, mock_write = _make_main_mocks(
            monkeypatch,
            ["dream.py", "--auth", "cli", "--max-events", "10"],
            sessions,
        )
        mock_call.assert_not_called()
        mock_write.assert_not_called()
        assert "skipping" in capsys.readouterr().out

    def test_skipped_session_watermark_not_updated(self, monkeypatch):
        """Regression: oversized sessions must not advance last_dreamed_at."""
        sessions = [("ses-big", self._events(50))]
        _, mock_write = _make_main_mocks(
            monkeypatch,
            ["dream.py", "--auth", "cli", "--max-events", "10"],
            sessions,
        )
        mock_write.assert_not_called()

    def test_zero_means_no_limit(self, monkeypatch):
        sessions = [("ses-huge", self._events(9999))]
        mock_call, _ = _make_main_mocks(
            monkeypatch,
            ["dream.py", "--auth", "cli", "--max-events", "0"],
            sessions,
        )
        mock_call.assert_called_once()

    def test_env_var_respected(self, monkeypatch):
        monkeypatch.setenv("DREAM_MAX_EVENTS", "10")
        sessions = [("ses-big", self._events(50))]
        mock_call, _ = _make_main_mocks(
            monkeypatch,
            ["dream.py", "--auth", "cli"],  # no --max-events flag
            sessions,
        )
        mock_call.assert_not_called()

    def test_flag_overrides_env_var(self, monkeypatch):
        monkeypatch.setenv("DREAM_MAX_EVENTS", "10")
        sessions = [("ses-big", self._events(50))]
        mock_call, _ = _make_main_mocks(
            monkeypatch,
            ["dream.py", "--auth", "cli", "--max-events", "100"],
            sessions,
        )
        mock_call.assert_called_once()

    def test_mixed_sessions_only_large_skipped(self, monkeypatch, capsys):
        sessions = [
            ("ses-small", self._events(5)),
            ("ses-big", self._events(50)),
            ("ses-medium", self._events(8)),
        ]
        mock_call, mock_write = _make_main_mocks(
            monkeypatch,
            ["dream.py", "--auth", "cli", "--max-events", "10"],
            sessions,
        )
        assert mock_call.call_count == 2   # small + medium
        assert mock_write.call_count == 2
        assert "skipping" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Per-session error recovery: a failing session must not abort the whole run
# ---------------------------------------------------------------------------
class TestPerSessionErrorRecovery:
    def _events(self, n):
        return [{"timestamp": f"2026-01-01T00:00:0{i}.000Z", "event_name": "Stop"} for i in range(n)]

    def test_error_on_one_session_continues_to_next(self, monkeypatch, capsys):
        """Regression: RuntimeError from call_claude previously crashed the whole run."""
        sessions = [
            ("ses-a", self._events(5)),
            ("ses-b", self._events(5)),  # this one will raise
            ("ses-c", self._events(5)),
        ]
        call_count = 0

        def flaky_call_claude(client, transcript, existing):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Prompt is too long")
            return []

        monkeypatch.setenv("DREAM_CLAUDE_BIN", "/fake/claude")
        fake_driver = MagicMock()

        with patch("sys.argv", ["dream.py", "--auth", "cli"]), \
             patch("dream.get_driver", return_value=fake_driver), \
             patch("dream.fetch_events", return_value=sessions), \
             patch("dream.fetch_existing_memories", return_value=[]), \
             patch("dream.call_claude", side_effect=flaky_call_claude), \
             patch("dream.write_memories", return_value=0) as mock_write:
            dream_mod.main()

        # ses-a and ses-c must still be written; ses-b skipped
        assert mock_write.call_count == 2
        written_ids = [c.args[1] for c in mock_write.call_args_list]  # args: driver, session_id, ...
        assert "ses-a" in written_ids
        assert "ses-c" in written_ids
        assert "ses-b" not in written_ids
        assert "ERROR" in capsys.readouterr().err

    def test_error_does_not_advance_watermark(self, monkeypatch):
        """Watermark for a failed session must not be updated."""
        sessions = [("ses-fail", self._events(5))]

        monkeypatch.setenv("DREAM_CLAUDE_BIN", "/fake/claude")
        fake_driver = MagicMock()

        with patch("sys.argv", ["dream.py", "--auth", "cli"]), \
             patch("dream.get_driver", return_value=fake_driver), \
             patch("dream.fetch_events", return_value=sessions), \
             patch("dream.fetch_existing_memories", return_value=[]), \
             patch("dream.call_claude", side_effect=RuntimeError("too long")), \
             patch("dream.write_memories") as mock_write:
            dream_mod.main()

        mock_write.assert_not_called()


# ---------------------------------------------------------------------------
# Regression: error detail was silently dropped when stderr was empty
# ---------------------------------------------------------------------------
class TestErrorDetail:
    def test_stderr_shown_in_error(self, monkeypatch):
        monkeypatch.setenv("DREAM_CLAUDE_BIN", "/fake/claude")
        result = SimpleNamespace(returncode=1, stdout="", stderr="context window exceeded")
        with patch("dream.subprocess.run", return_value=result):
            with pytest.raises(RuntimeError, match="context window exceeded"):
                dream_mod._call_claude_cli("t", "e")

    def test_stdout_shown_when_stderr_empty(self, monkeypatch):
        """Regression: exit code 1 with empty stderr used to show no detail at all."""
        monkeypatch.setenv("DREAM_CLAUDE_BIN", "/fake/claude")
        result = SimpleNamespace(returncode=1, stdout="rate limit hit", stderr="")
        with patch("dream.subprocess.run", return_value=result):
            with pytest.raises(RuntimeError, match="rate limit hit"):
                dream_mod._call_claude_cli("t", "e")

    def test_fallback_message_when_both_empty(self, monkeypatch):
        monkeypatch.setenv("DREAM_CLAUDE_BIN", "/fake/claude")
        result = SimpleNamespace(returncode=1, stdout="", stderr="")
        with patch("dream.subprocess.run", return_value=result):
            with pytest.raises(RuntimeError, match="no output"):
                dream_mod._call_claude_cli("t", "e")
