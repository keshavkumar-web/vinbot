#!/usr/bin/env python3
"""Standalone smoke test for a running Vinbot instance.

Runs INDEPENDENTLY of pytest (see Phase 3 requirement: "Smoke tests must
execute independently from unit tests") — this validates a real,
already-running (or just-started) FastAPI process over real HTTP, using no
mocks. It is the "is the deployed thing actually alive and correct" check,
complementary to (not a replacement for) the mocked unit suite.

Usage
-----
    # against an already-running local dev server (uvicorn on :8000)
    python tests/smoke/smoke.py

    # launch the server itself, smoke-test it, then shut it down
    python tests/smoke/smoke.py --start-server

    # against a deployed environment (needs a real OPENAI_API_KEY on THAT server)
    python tests/smoke/smoke.py --base-url https://uat-vinbot.vinbox.in

See tests/smoke/README.md for full prerequisites and per-environment examples.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

SMOKE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SMOKE_DIR.parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "smoke-test-report.md"


@dataclass
class CheckResult:
    name: str
    status: str          # "PASS" | "FAIL" | "SKIP"
    detail: str
    duration_ms: float | None = None


@dataclass
class SmokeRun:
    base_url: str
    results: list = field(default_factory=list)

    def add(self, result: CheckResult) -> CheckResult:
        self.results.append(result)
        mark = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP"}[result.status]
        dur = f" ({result.duration_ms:.0f} ms)" if result.duration_ms is not None else ""
        print(f"[{mark}] {result.name}{dur} - {result.detail}")
        return result


def _lower_headers(headers) -> dict:
    """HTTP header names are case-insensitive; http.client's HTTPMessage
    knows this but a plain dict built from it does not, so normalise keys to
    lowercase once here rather than losing that guarantee at every call site."""
    return {k.lower(): v for k, v in headers.items()}


def _get(url: str, timeout: float = 10.0):
    start = time.perf_counter()
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        elapsed_ms = (time.perf_counter() - start) * 1000
        return resp.status, body, _lower_headers(resp.headers), elapsed_ms


def _post(url: str, payload: dict, timeout: float = 30.0):
    start = time.perf_counter()
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        elapsed_ms = (time.perf_counter() - start) * 1000
        return resp.status, body, _lower_headers(resp.headers), elapsed_ms


# --------------------------------------------------------------------------- #
# Individual checks — each returns a CheckResult, never raises for an
# ordinary failure (only for a genuine script bug), so one failing check
# never stops the rest of the run.
# --------------------------------------------------------------------------- #
def check_server_starts(run: SmokeRun, args, proc_holder: dict) -> bool:
    """If --start-server was passed, launch uvicorn and poll until healthy.
    Otherwise, just confirm the target is already reachable."""
    health_url = f"{args.base_url}/api/health"

    if args.start_server:
        # NOTE: we do NOT require OPENAI_API_KEY in *this* shell's environment
        # before attempting to start the server. app/config.py loads it via
        # python-dotenv from backend/.env at process startup regardless of the
        # launching shell's env — that's the documented, normal way to run
        # Vinbot locally (see INSTALL.md). If the key really is missing
        # (neither the shell nor backend/.env has it), the health-poll below
        # will simply time out against a process that exited immediately,
        # which check_server_starts already reports clearly.
        env = os.environ.copy()
        cmd = [sys.executable, "-m", "uvicorn", "app.main:app",
               "--host", "127.0.0.1", "--port", str(args.port)]
        proc_holder["proc"] = subprocess.Popen(
            cmd, cwd=str(BACKEND_DIR), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        start = time.perf_counter()
        deadline = start + args.startup_timeout
        while time.perf_counter() < deadline:
            if proc_holder["proc"].poll() is not None:
                out = proc_holder["proc"].stdout.read() if proc_holder["proc"].stdout else ""
                run.add(CheckResult("FastAPI starts successfully", "FAIL",
                                    f"process exited early (code {proc_holder['proc'].returncode}); "
                                    f"output: {out[-500:]}"))
                return False
            try:
                status, _, _, _ = _get(health_url, timeout=2)
                if status == 200:
                    run.add(CheckResult("FastAPI starts successfully", "PASS",
                                        f"uvicorn came up and answered {health_url}",
                                        (time.perf_counter() - start) * 1000))
                    return True
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            time.sleep(0.5)

        run.add(CheckResult("FastAPI starts successfully", "FAIL",
                            f"did not become healthy within {args.startup_timeout}s"))
        return False

    # Not asked to start it — just confirm it's already up.
    try:
        status, _, _, elapsed = _get(health_url, timeout=5)
        if status == 200:
            run.add(CheckResult("FastAPI starts successfully", "PASS",
                                "server already running and reachable", elapsed))
            return True
        run.add(CheckResult("FastAPI starts successfully", "FAIL",
                            f"unexpected status {status} from {health_url}"))
        return False
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        run.add(CheckResult("FastAPI starts successfully", "FAIL",
                            f"cannot reach {health_url}: {exc}. "
                            f"Pass --start-server to have this script launch it."))
        return False


def check_health_endpoint(run: SmokeRun, args) -> dict | None:
    try:
        status, body, _, elapsed = _get(f"{args.base_url}/api/health", timeout=args.timeout)
        parsed = json.loads(body)
        if status == 200 and parsed.get("status") == "ok":
            run.add(CheckResult("Health endpoint", "PASS",
                                f"200 OK, status={parsed.get('status')!r}", elapsed))
            return parsed
        run.add(CheckResult("Health endpoint", "FAIL", f"status={status}, body={parsed}"))
        return None
    except Exception as exc:  # noqa: BLE001
        run.add(CheckResult("Health endpoint", "FAIL", str(exc)))
        return None


def check_session_creation(run: SmokeRun, args) -> str | None:
    try:
        status, body, _, elapsed = _post(f"{args.base_url}/api/session", {}, timeout=args.timeout)
        parsed = json.loads(body)
        sid = parsed.get("session_id")
        if status == 200 and sid:
            run.add(CheckResult("Session creation", "PASS", f"session_id={sid[:12]}...", elapsed))
            return sid
        run.add(CheckResult("Session creation", "FAIL", f"status={status}, body={parsed}"))
        return None
    except Exception as exc:  # noqa: BLE001
        run.add(CheckResult("Session creation", "FAIL", str(exc)))
        return None


def check_chat_and_streaming(run: SmokeRun, args, session_id: str | None):
    if not session_id:
        run.add(CheckResult("Chat endpoint", "SKIP", "no session_id (session creation failed)"))
        run.add(CheckResult("SSE streaming", "SKIP", "no session_id (session creation failed)"))
        return

    try:
        status, body, headers, elapsed = _post(
            f"{args.base_url}/api/chat",
            {"session_id": session_id, "message": "What is UHBVN?"},
            timeout=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001
        run.add(CheckResult("Chat endpoint", "FAIL", str(exc)))
        run.add(CheckResult("SSE streaming", "SKIP", "chat request failed"))
        return

    content_type = headers.get("content-type", "")
    if status == 200 and content_type.startswith("text/event-stream"):
        run.add(CheckResult("Chat endpoint", "PASS",
                            f"200 OK, content-type={content_type}", elapsed))
    else:
        run.add(CheckResult("Chat endpoint", "FAIL",
                            f"status={status}, content-type={content_type!r}. "
                            f"NOTE: this endpoint needs a real OPENAI_API_KEY configured "
                            f"on the TARGET server."))
        run.add(CheckResult("SSE streaming", "SKIP", "chat request did not succeed"))
        return

    text = body.decode(errors="replace")
    frame_types = re.findall(r'"type":\s*"(\w+)"', text)
    if frame_types and frame_types[-1] in ("done", "error"):
        run.add(CheckResult("SSE streaming", "PASS",
                            f"{len(frame_types)} frame(s), ends with '{frame_types[-1]}'"))
    else:
        run.add(CheckResult("SSE streaming", "FAIL", f"malformed/empty SSE body: {text[:200]!r}"))


def check_sqlite_availability(run: SmokeRun, args):
    is_local_target = urlparse(args.base_url).hostname in ("localhost", "127.0.0.1")
    db_path = Path(args.db_path) if args.db_path else (BACKEND_DIR / "uhbvn_tables.db")

    if not db_path.exists():
        if is_local_target:
            run.add(CheckResult("SQLite availability", "FAIL",
                                f"{db_path} not found (structured/numeric answers will "
                                f"fall back to prose — see app/tables.py)"))
        else:
            run.add(CheckResult("SQLite availability", "SKIP",
                                f"no filesystem access to remote target {args.base_url}; "
                                f"pass --db-path to check a local copy explicitly"))
        return

    try:
        con = sqlite3.connect(str(db_path))
        (integrity,) = con.execute("PRAGMA integrity_check").fetchone()
        n_facts = None
        try:
            (n_facts,) = con.execute("SELECT COUNT(*) FROM facts").fetchone()
        except sqlite3.OperationalError:
            pass
        con.close()
        if integrity == "ok":
            detail = f"{db_path.name} OK"
            if n_facts is not None:
                detail += f", {n_facts} fact rows"
            run.add(CheckResult("SQLite availability", "PASS", detail))
        else:
            run.add(CheckResult("SQLite availability", "FAIL", f"integrity_check={integrity}"))
    except sqlite3.Error as exc:
        run.add(CheckResult("SQLite availability", "FAIL", str(exc)))


def check_knowledge_base_loaded(run: SmokeRun, health: dict | None):
    if health is None:
        run.add(CheckResult("Knowledge base loading", "SKIP", "health check did not succeed"))
        return
    chunks = health.get("knowledge_chunks", 0)
    if chunks and chunks > 0:
        run.add(CheckResult("Knowledge base loading", "PASS", f"{chunks} chunks loaded"))
    else:
        run.add(CheckResult("Knowledge base loading", "FAIL",
                            "knowledge_chunks is 0 — knowledge_db.pkl missing or empty"))


def check_configuration_validation(run: SmokeRun, args, health: dict | None):
    if health is None:
        run.add(CheckResult("Configuration validation", "SKIP", "health check did not succeed"))
        return
    missing = [k for k in ("chat_model", "embed_model") if not health.get(k)]
    if not missing:
        detail = f"chat_model={health['chat_model']!r}, embed_model={health['embed_model']!r}"
        env_path = BACKEND_DIR / ".env"
        if env_path.exists():
            detail += f"; local {env_path.name} present"
        run.add(CheckResult("Configuration validation", "PASS", detail))
    else:
        run.add(CheckResult("Configuration validation", "FAIL", f"missing: {missing}"))


def check_reset_endpoint(run: SmokeRun, args, session_id: str | None):
    if not session_id:
        run.add(CheckResult("Reset endpoint", "SKIP", "no session_id (session creation failed)"))
        return
    try:
        status, body, _, elapsed = _post(
            f"{args.base_url}/api/reset", {"session_id": session_id}, timeout=args.timeout)
        parsed = json.loads(body)
        if status == 200 and parsed.get("ok") is True:
            run.add(CheckResult("Reset endpoint", "PASS", "session cleared", elapsed))
        else:
            run.add(CheckResult("Reset endpoint", "FAIL", f"status={status}, body={parsed}"))
    except Exception as exc:  # noqa: BLE001
        run.add(CheckResult("Reset endpoint", "FAIL", str(exc)))


def check_average_response_time(run: SmokeRun, args):
    durations = []
    errors = 0
    for _ in range(args.repeat):
        try:
            _, _, _, elapsed = _get(f"{args.base_url}/api/health", timeout=args.timeout)
            durations.append(elapsed)
        except Exception:  # noqa: BLE001
            errors += 1
    if not durations:
        run.add(CheckResult("Average response time", "FAIL",
                            f"all {args.repeat} requests failed"))
        return
    avg = sum(durations) / len(durations)
    detail = (f"avg={avg:.0f} ms over {len(durations)} call(s) "
              f"(min={min(durations):.0f}, max={max(durations):.0f}, threshold={args.threshold_ms} ms)")
    if errors:
        detail += f", {errors} request(s) failed"
    if avg <= args.threshold_ms and errors == 0:
        run.add(CheckResult("Average response time", "PASS", detail))
    else:
        run.add(CheckResult("Average response time", "FAIL", detail))


# --------------------------------------------------------------------------- #
def write_report(run: SmokeRun, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for r in run.results if r.status == "PASS")
    failed = sum(1 for r in run.results if r.status == "FAIL")
    skipped = sum(1 for r in run.results if r.status == "SKIP")
    lines = [
        "# Vinbot — Smoke Test Report",
        "",
        f"- Target: `{run.base_url}`",
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Total checks: {len(run.results)} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}",
        "",
        "| Check | Status | Duration (ms) | Detail |",
        "|---|---|---|---|",
    ]
    for r in run.results:
        dur = f"{r.duration_ms:.0f}" if r.duration_ms is not None else "-"
        detail = r.detail.replace("|", "\\|")
        lines.append(f"| {r.name} | {r.status} | {dur} | {detail} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000",
                        help="Target instance base URL (default: http://127.0.0.1:8000)")
    parser.add_argument("--start-server", action="store_true",
                        help="Launch uvicorn locally before testing, and stop it afterward")
    parser.add_argument("--port", type=int, default=8000, help="Port for --start-server")
    parser.add_argument("--startup-timeout", type=float, default=30.0,
                        help="Seconds to wait for --start-server to become healthy")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="Per-request timeout in seconds")
    parser.add_argument("--repeat", type=int, default=5,
                        help="Number of calls averaged for the response-time check")
    parser.add_argument("--threshold-ms", type=float, default=1000.0,
                        help="Average response time (ms) above which the check fails")
    parser.add_argument("--db-path", default=None,
                        help="Local path to uhbvn_tables.db (defaults to backend/uhbvn_tables.db)")
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH),
                        help="Where to write the Markdown smoke test report")
    args = parser.parse_args()

    run = SmokeRun(base_url=args.base_url.rstrip("/"))
    proc_holder: dict = {"proc": None}

    print(f"=== Vinbot smoke test — target: {run.base_url} ===\n")
    try:
        server_up = check_server_starts(run, args, proc_holder)
        health = check_health_endpoint(run, args) if server_up else None
        session_id = check_session_creation(run, args) if server_up else None
        check_chat_and_streaming(run, args, session_id)
        check_sqlite_availability(run, args)
        check_knowledge_base_loaded(run, health)
        check_configuration_validation(run, args, health)
        check_reset_endpoint(run, args, session_id)
        if server_up:
            check_average_response_time(run, args)
    finally:
        proc = proc_holder.get("proc")
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    write_report(run, Path(args.report))

    passed = sum(1 for r in run.results if r.status == "PASS")
    failed = sum(1 for r in run.results if r.status == "FAIL")
    skipped = sum(1 for r in run.results if r.status == "SKIP")
    print(f"\n=== {passed} passed, {failed} failed, {skipped} skipped ===")
    print(f"Report written to {args.report}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
