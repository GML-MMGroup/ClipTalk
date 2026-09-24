#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate_agent_scenarios import main as validate_agent_scenarios_main

MANIFEST = ROOT / "tests" / "fixtures" / "agent_capability_questions.json"


def main(argv: list[str] | None = None) -> int:
    """Run full Agent input-to-result capability scenarios.

    This wrapper intentionally reuses validate_agent_scenarios.py so each case
    uploads the video, submits the prompt to Agent, validates the selected Skill
    and plan contract, confirms the initial plan, polls execution, and checks
    terminal preview/result artifacts.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if not any(arg == "--manifest" or arg.startswith("--manifest=") for arg in args):
        args = ["--manifest", str(MANIFEST), *args]
    return validate_agent_scenarios_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
