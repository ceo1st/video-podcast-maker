#!/usr/bin/env python3
"""Pre-flight check: verify required CLIs exist and the resolved TTS backend has its env vars.

Backend is resolved with the same precedence as generate_tts.py:
    env TTS_BACKEND > user_prefs.json (global.tts.backend) > 'edge' default

Prose output (default for TTY; preserved for SKILL.md back-compat):
    ALL_OK (backend=<name>)
    MISSING:<space-separated items> (backend=<name>)

JSON output (default when stdout is piped; --format json forces it):
    success: { "ok": true,  "data": { backend, backend_source, required_bins, required_env_vars }, "meta": ... }
    failure: { "ok": false, "error": { code: tool_missing | auth_missing_env, message,
                                        retryable: false, missing_bins, missing_env_vars,
                                        backend, backend_source }, "meta": ... }

Exit codes:
    0 — all prerequisites satisfied
    2 — at least one required binary or env var is missing
        (was 'always 0' historically; SKILL.md only reads stdout so the
        change is additive — orchestrators can now use && chaining)
"""
import argparse
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cli_envelope  # noqa: E402
from tts.backends import BACKENDS, resolve_backend  # noqa: E402


REQUIRED_BINS = ["node", "python3", "ffmpeg"]


def check_prereqs(env=None):
    """Compute prereq state. Returns dict with backend, backend_source,
    required_bins, required_env_vars, missing_bins, missing_env_vars.

    `env` overrides os.environ for testing (default: os.environ).
    Tool presence is checked via shutil.which and is not mockable through
    `env` — tests should monkeypatch shutil.which directly if needed.
    """
    env = env if env is not None else os.environ
    try:
        backend, backend_source = resolve_backend()
    except Exception:
        # user_prefs.json malformed or unreadable — fall back to env/default.
        # Mirrors generate_tts.py's defensive fallback so the prereq check
        # never crashes and always reports something actionable.
        backend = env.get("TTS_BACKEND", "edge")
        backend_source = "env" if env.get("TTS_BACKEND") else "default"

    required_env_vars = BACKENDS.get(backend, {}).get("env", [])
    missing_bins = [b for b in REQUIRED_BINS if not shutil.which(b)]
    missing_env_vars = [v for v in required_env_vars if not env.get(v)]

    return {
        "backend": backend,
        "backend_source": backend_source,
        "required_bins": REQUIRED_BINS,
        "required_env_vars": required_env_vars,
        "missing_bins": missing_bins,
        "missing_env_vars": missing_env_vars,
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cli_envelope.add_format_arg(parser)
    args = parser.parse_args()
    started_at = time.time()

    state = check_prereqs()
    backend = state["backend"]
    missing_bins = state["missing_bins"]
    missing_env_vars = state["missing_env_vars"]

    if not missing_bins and not missing_env_vars:
        if cli_envelope.use_json(args):
            sys.exit(cli_envelope.emit_success(args, {
                "backend": backend,
                "backend_source": state["backend_source"],
                "required_bins": state["required_bins"],
                "required_env_vars": state["required_env_vars"],
            }, started_at=started_at))
        print(f"ALL_OK (backend={backend})")
        sys.exit(0)

    # Some prereqs missing. Tool-missing dominates: a missing binary needs
    # an install; missing env vars only need export. Both map to exit 2 in
    # cli_envelope.ERROR_CODES so the orchestrator-side routing is the same,
    # but the code field tells the agent what kind of fix to suggest.
    code = "tool_missing" if missing_bins else "auth_missing_env"
    all_missing = missing_bins + missing_env_vars

    if cli_envelope.use_json(args):
        sys.exit(cli_envelope.emit_error(
            args, code,
            f"{len(all_missing)} prereq(s) missing for backend '{backend}'",
            extra={
                "backend": backend,
                "backend_source": state["backend_source"],
                "missing_bins": missing_bins,
                "missing_env_vars": missing_env_vars,
            },
            started_at=started_at,
        ))
    print(f"MISSING:{' '.join(all_missing)} (backend={backend})")
    sys.exit(2)


if __name__ == "__main__":
    main()
