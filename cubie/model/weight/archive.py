from __future__ import annotations

import shutil
import tarfile
import zipfile
from pathlib import Path
from urllib.parse import urlsplit


def extract_archive(archive_path: Path, destination: Path) -> None:
    suffix = archive_path.name.lower()
    destination.mkdir(parents=True, exist_ok=True)
    if suffix.endswith(".zip"):
        extract_zip(archive_path, destination)
        return
    if suffix.endswith(".tar.gz"):
        extract_tar_gz(archive_path, destination)
        return
    raise ValueError("url source only supports .zip and .tar.gz archives")


def extract_zip(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if not members:
            raise ValueError("zip archive is empty")
        destination_root = destination.resolve()
        for member in members:
            member_path = (destination / member.filename).resolve()
            if not is_relative_to(member_path, destination_root):
                raise ValueError("zip archive contains paths outside target directory")
        archive.extractall(destination)


def extract_tar_gz(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError("tar.gz archive is empty")
        destination_root = destination.resolve()
        for member in members:
            member_path = (destination / member.name).resolve()
            if not is_relative_to(member_path, destination_root):
                raise ValueError("tar.gz archive contains paths outside target directory")
        archive.extractall(destination)


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def compute_dir_size(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def directory_has_entries(path: Path) -> bool:
    try:
        next(path.iterdir())
    except (StopIteration, FileNotFoundError):
        return False
    return True


def snapshot_has_model_weights(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    for pattern in (
        "*.safetensors",
        "pytorch_model*.bin",
        "model.ckpt*",
        "tf_model.h5",
        "flax_model.msgpack",
    ):
        try:
            next(path.rglob(pattern))
        except StopIteration:
            continue
        return True
    return False


def detect_archive_format(source_url: str) -> str | None:
    path = urlsplit(str(source_url)).path.strip().lower()
    if path.endswith(".tar.gz"):
        return ".tar.gz"
    if path.endswith(".zip"):
        return ".zip"
    return None


def prepare_target_dir(cache_dir: Path, model_id: str) -> Path:
    from . import cache_key

    cache_dir.mkdir(parents=True, exist_ok=True)
    target_dir = cache_dir / cache_key(model_id)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def prepare_dep_target_dir(cache_dir: Path, instance_id: str) -> Path:
    from . import cache_key

    dep_root = cache_dir / "deps"
    dep_root.mkdir(parents=True, exist_ok=True)
    target_dir = dep_root / cache_key(instance_id)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir
