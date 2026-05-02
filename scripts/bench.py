from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_SAMPLE_IMAGE_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z/C/HwAF/gL+Q6UkWQAAAABJRU5ErkJggg=="
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke helper for the Cubie 3D service.",
    )
    parser.add_argument(
        "mode",
        choices=("success", "cancel", "events"),
        help="Smoke flow to run against a live Cubie 3D server.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:18001",
        help="Cubie 3D base URL.",
    )
    parser.add_argument(
        "--token",
        default="dev-local-token",
        help="Bearer token for Cubie 3D.",
    )
    parser.add_argument(
        "--image-url",
        default=DEFAULT_SAMPLE_IMAGE_URL,
        help="Source image URL used for the mock request.",
    )
    parser.add_argument(
        "--resolution",
        type=int,
        default=1024,
        help="Requested generation resolution.",
    )
    parser.add_argument(
        "--failure-stage",
        default=None,
        choices=("preprocessing", "gpu_ss", "gpu_shape", "gpu_material", "exporting"),
        help="Optional mock failure injection stage.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=5.0,
        help="Polling timeout for success/cancel flows.",
    )
    return parser


def auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def create_task(client: httpx.Client, args: argparse.Namespace) -> dict:
    payload = {
        "type": "image_to_3d",
        "image_url": args.image_url,
        "options": {"resolution": args.resolution},
    }
    if args.failure_stage:
        payload["options"]["mock_failure_stage"] = args.failure_stage
    response = client.post("/v1/tasks", headers=auth_headers(args.token), json=payload)
    response.raise_for_status()
    return response.json()


def get_task(client: httpx.Client, token: str, task_id: str) -> dict:
    response = client.get(f"/v1/tasks/{task_id}", headers=auth_headers(token))
    response.raise_for_status()
    return response.json()


def wait_for_statuses(
    client: httpx.Client,
    token: str,
    task_id: str,
    *,
    accepted_statuses: set[str],
    timeout_seconds: float,
) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        payload = get_task(client, token, task_id)
        if payload["status"] in accepted_statuses:
            return payload
        time.sleep(0.05)
    raise TimeoutError(
        f"task {task_id} did not reach one of {sorted(accepted_statuses)} in time"
    )


def run_success(client: httpx.Client, args: argparse.Namespace) -> int:
    task = create_task(client, args)
    final_task = wait_for_statuses(
        client,
        args.token,
        task["taskId"],
        accepted_statuses={"succeeded", "failed", "cancelled"},
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(final_task, indent=2, ensure_ascii=False))
    return 0 if final_task["status"] == "succeeded" else 1


def run_cancel(client: httpx.Client, args: argparse.Namespace) -> int:
    task = create_task(client, args)
    wait_for_statuses(
        client,
        args.token,
        task["taskId"],
        accepted_statuses={"gpu_queued", "failed", "succeeded"},
        timeout_seconds=args.timeout_seconds,
    )
    response = client.post(
        f"/v1/tasks/{task['taskId']}/cancel",
        headers=auth_headers(args.token),
    )
    response.raise_for_status()
    final_task = get_task(client, args.token, task["taskId"])
    print(json.dumps(final_task, indent=2, ensure_ascii=False))
    return 0 if final_task["status"] == "cancelled" else 1


def run_events(client: httpx.Client, args: argparse.Namespace) -> int:
    task = create_task(client, args)
    terminal_statuses = {"succeeded", "failed", "cancelled"}
    with client.stream(
        "GET",
        f"/v1/tasks/{task['taskId']}/events",
        headers={"Authorization": f"Bearer {args.token}"},
    ) as response:
        response.raise_for_status()
        current_event: str | None = None
        for line in response.iter_lines():
            if not line:
                continue
            if line.startswith("event: "):
                current_event = line.removeprefix("event: ")
                continue
            if not line.startswith("data: "):
                continue
            payload = json.loads(line.removeprefix("data: "))
            payload["event"] = current_event
            print(json.dumps(payload, ensure_ascii=False))
            if payload["status"] in terminal_statuses:
                return 0
    return 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=args.timeout_seconds) as client:
        if args.mode == "success":
            return run_success(client, args)
        if args.mode == "cancel":
            return run_cancel(client, args)
        return run_events(client, args)


if __name__ == "__main__":
    raise SystemExit(main())
