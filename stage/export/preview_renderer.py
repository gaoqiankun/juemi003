from __future__ import annotations

import io
import math
import os
import sys
import traceback
from pathlib import Path

from gen3d.stage.export.preview_protocol import read_message_sync, write_message_sync


class PreviewRenderRuntime:
    def __init__(self) -> None:
        if sys.platform.startswith("linux"):
            os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

        import numpy as np
        import pyrender
        import trimesh
        from PIL import Image

        self._np = np
        self._pyrender = pyrender
        self._trimesh = trimesh
        self._image_cls = Image
        self._renderer = pyrender.OffscreenRenderer(viewport_width=512, viewport_height=512)

    def close(self) -> None:
        self._renderer.delete()

    def warmup(self) -> bytes:
        dummy_scene = self._trimesh.creation.box(extents=(1.0, 1.0, 1.0)).scene()
        return self._render_scene_to_png_bytes(dummy_scene)

    def render_model_path(self, model_path: Path) -> bytes:
        return self._render_loaded_scene(
            self._trimesh.load(model_path, force="scene"),
        )

    def render_model_bytes(self, model_bytes: bytes) -> bytes:
        return self._render_loaded_scene(
            self._trimesh.load(io.BytesIO(model_bytes), file_type="glb", force="scene"),
        )

    def _render_loaded_scene(self, loaded) -> bytes:
        if isinstance(loaded, self._trimesh.Trimesh):
            trimesh_scene = loaded.scene()
        elif isinstance(loaded, self._trimesh.Scene):
            trimesh_scene = loaded
        else:
            raise RuntimeError(f"unsupported GLB scene type: {type(loaded)!r}")

        if not trimesh_scene.geometry:
            raise RuntimeError("exported GLB contains no renderable geometry")

        return self._render_scene_to_png_bytes(trimesh_scene)

    def _render_scene_to_png_bytes(self, trimesh_scene) -> bytes:
        center, radius = _scene_center_and_radius(trimesh_scene, self._np)
        scene = self._pyrender.Scene.from_trimesh_scene(
            trimesh_scene,
            bg_color=self._np.array([42 / 255, 42 / 255, 42 / 255, 1.0], dtype=float),
            ambient_light=self._np.array([0.18, 0.18, 0.18], dtype=float),
        )
        camera = self._pyrender.PerspectiveCamera(yfov=math.radians(45.0), aspectRatio=1.0)
        scene.add(camera, pose=_camera_pose(center, radius, self._np))

        for position, intensity in _light_rig(center, radius, self._np):
            scene.add(
                self._pyrender.PointLight(color=self._np.ones(3), intensity=intensity),
                pose=_translation_pose(position, self._np),
            )

        color, _ = self._renderer.render(scene)
        image_mode = "RGBA" if color.ndim == 3 and color.shape[-1] == 4 else "RGB"
        buffer = io.BytesIO()
        self._image_cls.fromarray(color, mode=image_mode).save(buffer, format="PNG")
        return buffer.getvalue()


def render_preview_png(model_path: Path, output_path: Path) -> None:
    runtime = PreviewRenderRuntime()
    try:
        output_path.write_bytes(runtime.render_model_path(model_path))
    finally:
        runtime.close()


def _scene_center_and_radius(trimesh_scene, np):
    bounds = trimesh_scene.bounds
    if bounds is None or not np.isfinite(bounds).all():
        return np.zeros(3, dtype=float), 1.0

    center = (bounds[0] + bounds[1]) / 2.0
    radius = float(np.linalg.norm(bounds[1] - bounds[0]) / 2.0)
    if not math.isfinite(radius) or radius <= 1e-6:
        extents = bounds[1] - bounds[0]
        max_extent = float(np.max(np.abs(extents)))
        radius = max(max_extent / 2.0, 1.0)
    return center, radius


def _camera_pose(center, radius: float, np):
    azimuth = math.radians(0.0)
    elevation = math.radians(20.0)
    distance = max(radius * 2.5, 1.0)
    eye = center + np.array(
        [
            math.sin(azimuth) * math.cos(elevation) * distance,
            math.sin(elevation) * distance,
            math.cos(azimuth) * math.cos(elevation) * distance,
        ],
        dtype=float,
    )
    return _look_at_pose(eye, center, np)


def _look_at_pose(eye, target, np):
    up = np.array([0.0, 1.0, 0.0], dtype=float)
    forward = target - eye
    forward_norm = float(np.linalg.norm(forward))
    if forward_norm <= 1e-6:
        raise RuntimeError("camera eye coincides with target")
    forward = forward / forward_norm

    right = np.cross(forward, up)
    right_norm = float(np.linalg.norm(right))
    if right_norm <= 1e-6:
        up = np.array([0.0, 0.0, 1.0], dtype=float)
        right = np.cross(forward, up)
        right_norm = float(np.linalg.norm(right))
        if right_norm <= 1e-6:
            raise RuntimeError("failed to build preview camera basis")
    right = right / right_norm
    camera_up = np.cross(right, forward)

    pose = np.eye(4, dtype=float)
    pose[:3, 0] = right
    pose[:3, 1] = camera_up
    pose[:3, 2] = -forward
    pose[:3, 3] = eye
    return pose


def _light_rig(center, radius: float, np):
    scale = max(radius, 1.0)
    return [
        (center + np.array([-1.6 * scale, 1.4 * scale, 2.1 * scale], dtype=float), 24.0),
        (center + np.array([1.8 * scale, 0.6 * scale, 1.3 * scale], dtype=float), 12.0),
        (center + np.array([0.0, 1.8 * scale, -2.2 * scale], dtype=float), 18.0),
    ]


def _translation_pose(position, np):
    pose = np.eye(4, dtype=float)
    pose[:3, 3] = position
    return pose


def serve() -> int:
    runtime = PreviewRenderRuntime()
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    try:
        while True:
            try:
                header, body = read_message_sync(stdin)
            except EOFError:
                return 0

            action = str(header.get("action") or "")
            try:
                if action == "warmup":
                    runtime.warmup()
                    write_message_sync(stdout, {"status": "ok"})
                    continue
                if action == "shutdown":
                    write_message_sync(stdout, {"status": "ok"})
                    return 0
                if action != "render":
                    raise RuntimeError(f"unsupported action: {action!r}")

                input_type = str(header.get("input_type") or "")
                if input_type == "path":
                    model_path = Path(str(header.get("path") or "")).resolve()
                    png_bytes = runtime.render_model_path(model_path)
                elif input_type == "bytes":
                    png_bytes = runtime.render_model_bytes(body)
                else:
                    raise RuntimeError(f"unsupported input type: {input_type!r}")

                write_message_sync(stdout, {"status": "ok"}, png_bytes)
            except Exception as exc:
                write_message_sync(stdout, {"status": "error", "error": str(exc)})
    finally:
        runtime.close()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args == ["--serve"]:
        try:
            return serve()
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return 1

    if len(args) != 2:
        print("usage: python -m gen3d.stage.export.preview_renderer <model.glb> <preview.png>", file=sys.stderr)
        print("   or: python -m gen3d.stage.export.preview_renderer --serve", file=sys.stderr)
        return 2

    model_path = Path(args[0]).resolve()
    output_path = Path(args[1]).resolve()
    render_preview_png(model_path, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
