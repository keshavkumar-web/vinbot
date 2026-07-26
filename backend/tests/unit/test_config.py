"""Unit tests for app/config.py.

Covers the "missing configuration" edge case explicitly required by Phase 3,
and env-var overrides. The missing-key case runs in a SUBPROCESS (not an
in-process reload) so it can never leak import state into the rest of the
suite, and so it exercises the exact real-world failure mode: starting the
process without OPENAI_API_KEY set.

REQ-CFG-01, REQ-CFG-02 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import importlib
import os
import shutil
import subprocess
import sys

import pytest

from app import config as config_module

pytestmark = pytest.mark.unit


@pytest.fixture
def config_env():
    """Mutate os.environ for the test, then restore it AND reload app.config
    back to the baseline test environment (see conftest.py) as one atomic
    teardown step, so later test modules never see leaked config state."""
    original = dict(os.environ)
    yield os.environ
    os.environ.clear()
    os.environ.update(original)
    importlib.reload(config_module)


def test_missing_openai_api_key_raises_at_import(tmp_path):
    """Matches the real deployment failure mode: the process must refuse to
    start (loudly) rather than run with a broken OpenAI client.

    Runs against an ISOLATED copy of app/config.py under tmp_path (not the
    real backend/ directory) — the real backend/.env on this machine holds a
    genuine key, and python-dotenv's load_dotenv() searches upward from
    config.py's own file location (not the subprocess's cwd), so running
    directly in backend/ would silently pick that real .env up and mask the
    very failure this test exists to catch.
    """
    app_pkg = tmp_path / "app"
    app_pkg.mkdir()
    (app_pkg / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy(config_module.__file__, app_pkg / "config.py")

    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    result = subprocess.run(
        [sys.executable, "-c", "import app.config"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "OPENAI_API_KEY is not set" in result.stderr


def test_default_top_k_and_min_similarity():
    assert config_module.TOP_K == 8
    assert config_module.MIN_SIMILARITY == 0.35


def test_top_k_env_override(config_env):
    config_env["TOP_K"] = "12"
    importlib.reload(config_module)
    assert config_module.TOP_K == 12


def test_min_similarity_env_override(config_env):
    config_env["MIN_SIMILARITY"] = "0.5"
    importlib.reload(config_module)
    assert config_module.MIN_SIMILARITY == 0.5


def test_allowed_origins_parses_comma_separated_list(config_env):
    config_env["ALLOWED_ORIGINS"] = "https://vinbot.vinbox.in,https://uat-vinbot.vinbox.in"
    importlib.reload(config_module)
    assert config_module.ALLOWED_ORIGINS == [
        "https://vinbot.vinbox.in",
        "https://uat-vinbot.vinbox.in",
    ]


def test_max_history_messages_env_override(config_env):
    config_env["MAX_HISTORY_MESSAGES"] = "5"
    importlib.reload(config_module)
    assert config_module.MAX_HISTORY_MESSAGES == 5


def test_enable_followup_context_accepts_falsey_strings(config_env):
    config_env["ENABLE_FOLLOWUP_CONTEXT"] = "0"
    importlib.reload(config_module)
    assert config_module.ENABLE_FOLLOWUP_CONTEXT is False
