# ruff: noqa: E402

from __future__ import annotations

import pytest

from cubie.api.server import clamp_inference_estimate_mb
from cubie.vram import helpers as vram_helpers


@pytest.mark.parametrize(
    ("raw_estimate", "expected_estimate", "expect_warning"),
    [
        (-5_000, 1, True),
        (0, 1, True),
        (1, 1, False),
        (5_000, 5_000, False),
    ],
)
def testclamp_inference_estimate_mb(
    monkeypatch: pytest.MonkeyPatch,
    raw_estimate: int,
    expected_estimate: int,
    expect_warning: bool,
) -> None:
    warnings: list[tuple[str, dict[str, object]]] = []

    class FakeLogger:
        def warning(self, event: str, **kwargs: object) -> None:
            if event == "estimate_inference_vram_mb_nonpositive":
                warnings.append((event, kwargs))

    monkeypatch.setattr(vram_helpers, "_logger", FakeLogger())

    estimate = clamp_inference_estimate_mb(
        raw_value=raw_estimate,
        model="trellis2",
        batch_size=3,
        options={
            "resolution": 1024,
            "seed": 7,
        },
    )

    assert estimate == expected_estimate
    if expect_warning:
        assert len(warnings) == 1
        event, metadata = warnings[0]
        assert event == "estimate_inference_vram_mb_nonpositive"
        assert metadata["model"] == "trellis2"
        assert metadata["raw"] == raw_estimate
        assert metadata["clamped"] == 1
        assert metadata["batch_size"] == 3
        assert metadata["options"] == ["resolution", "seed"]
        return

    assert warnings == []
