from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import structlog
import uvicorn

# Allow `python -m cubie.serve` from the repo root as well as direct
# `python cubie/serve.py` invocation.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cubie.api.server import create_app, run_real_mode_preflight
from cubie.core.config import ServingConfig
from cubie.core.observability.logging import configure_logging


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run or validate the Cubie 3D service.")
    parser.add_argument(
        "--check-real-env",
        action="store_true",
        help="Run real-mode deployment self-check and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    config = ServingConfig()
    configure_logging(config.log_level)
    logger = structlog.get_logger(__name__)
    if args.check_real_env:
        try:
            logger.info(
                "service.real_env_check.started",
                provider_mode=config.provider_mode,
                artifact_store_mode=config.artifact_store_mode,
            )
            report = asyncio.run(run_real_mode_preflight(config))
        except Exception as exc:
            logger.exception("service.real_env_check.failed", error=str(exc))
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

        logger.info(
            "service.real_env_check.succeeded",
            model_id=report.get("model_id"),
            provider=report.get("provider", {}).get("provider"),
        )
        print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
        return

    logger.info(
        "service.starting",
        host=config.host,
        port=config.port,
        provider_mode=config.provider_mode,
        artifact_store_mode=config.artifact_store_mode,
    )
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level=config.log_level,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
