from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import uvicorn

# Allow `python serve.py` from the repo root as well as `python -m gen3d.serve`
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gen3d.api.server import create_app, run_real_mode_preflight
from gen3d.config import ServingConfig


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run or validate the gen3d service.")
    parser.add_argument(
        "--check-real-env",
        action="store_true",
        help="Run real-mode deployment self-check and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    config = ServingConfig()
    if args.check_real_env:
        try:
            report = asyncio.run(run_real_mode_preflight(config))
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "provider_mode": config.provider_mode,
                        "artifact_store_mode": config.artifact_store_mode,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            raise SystemExit(1) from exc

        print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
        return

    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level=config.log_level,
    )


if __name__ == "__main__":
    main()
