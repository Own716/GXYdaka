"""Tenant-isolated storage for optional per-user clock-in photos."""
from __future__ import annotations

import hashlib
import fcntl
import io
import json
import logging
import os
import re
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PHOTOS = 20
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_BATCH_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 25_000_000
MAX_IMAGE_SIDE = 1920
MAX_ENCODED_BYTES = 1024 * 1024
_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
_ROOT = Path(__file__).resolve().parent / "images" / "clockin_photos"
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
logger = logging.getLogger(__name__)


class PhotoError(ValueError):
    """Invalid photo operation or upload."""


def _identity_key(tenant_id: str, user_id: int) -> str:
    return hashlib.sha256(str(tenant_id or "default").encode("utf-8")).hexdigest()[:24] + f"/{int(user_id)}"


def _directory(tenant_id: str, user_id: int) -> Path:
    return _ROOT / _identity_key(tenant_id, user_id)


def _lock(tenant_id: str, user_id: int) -> threading.RLock:
    key = _identity_key(tenant_id, user_id)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _locked_directory(tenant_id: str, user_id: int):
    directory = _directory(tenant_id, user_id)
    with _lock(tenant_id, user_id):
        # server/images may itself be a deployment symlink; descendants must not be.
        if _ROOT.is_symlink() or directory.parent.is_symlink() or directory.is_symlink():
            raise PhotoError("照片存储路径无效")
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = directory / ".lock"
        if lock_path.is_symlink():
            raise PhotoError("照片存储路径无效")
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield directory
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _manifest_path(directory: Path) -> Path:
    return directory / "manifest.json"


def _load_manifest(directory: Path) -> list[dict[str, str]]:
    if _manifest_path(directory).is_symlink():
        raise PhotoError("照片清单路径无效")
    try:
        raw = json.loads(_manifest_path(directory).read_text("utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError):
        raise PhotoError("照片清单损坏")
    if not isinstance(raw, list):
        raise PhotoError("照片清单损坏")
    result = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        photo_id, filename, name = row.get("id"), row.get("filename"), row.get("name")
        if (isinstance(photo_id, str) and re.fullmatch(r"[0-9a-f]{32}", photo_id)
                and isinstance(filename, str) and filename == f"{photo_id}.jpg"
                and isinstance(name, str)):
            result.append({"id": photo_id, "filename": filename, "name": name[:200]})
    return result


def _save_manifest(directory: Path, rows: list[dict[str, str]]) -> None:
    if _manifest_path(directory).is_symlink():
        raise PhotoError("照片清单路径无效")
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / f".manifest-{uuid.uuid4().hex}.tmp"
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, _manifest_path(directory))
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            logger.debug("Photo manifest temporary file already removed")


def normalize_image(data: bytes) -> bytes:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise PhotoError("每张图片不得超过10MB且不能为空")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in _ALLOWED_FORMATS:
                raise PhotoError("仅支持 JPEG、PNG 或 WebP 图片")
            width, height = image.size
            if width < 1 or height < 1 or width * height > MAX_PIXELS:
                raise PhotoError("图片像素尺寸超出限制")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in _ALLOWED_FORMATS:
                raise PhotoError("仅支持 JPEG、PNG 或 WebP 图片")
            image = ImageOps.exif_transpose(image)
            image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
            if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            while True:
                for quality in (85, 75, 65, 55, 45):
                    output = io.BytesIO()
                    image.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
                    data = output.getvalue()
                    if len(data) <= MAX_ENCODED_BYTES:
                        return data
                width, height = image.size
                if max(width, height) <= 320:
                    raise PhotoError("图片无法压缩到1MB以内")
                resized = (max(1, int(width * 0.8)), max(1, int(height * 0.8)))
                image = image.resize(resized, Image.Resampling.LANCZOS)
    except PhotoError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning, ValueError) as exc:
        raise PhotoError("图片无法解码或已损坏") from exc


def list_photos(tenant_id: str, user_id: int) -> list[dict[str, str]]:
    with _locked_directory(tenant_id, user_id) as directory:
        return [{"id": row["id"], "name": row["name"]} for row in _load_manifest(directory)]


def add_photos(tenant_id: str, user_id: int, uploads: list[tuple[str, bytes]]) -> list[dict[str, str]]:
    if not uploads:
        raise PhotoError("请选择至少一张图片")
    if len(uploads) > MAX_PHOTOS:
        raise PhotoError("每次最多上传20张图片")
    if sum(len(data) for _, data in uploads) > MAX_BATCH_BYTES:
        raise PhotoError("单批图片总大小不得超过30MB")
    # Decode and normalize the whole batch before touching persistent files.
    normalized = [(str(name or "图片")[:200], normalize_image(data)) for name, data in uploads]
    created: list[Path] = []
    with _locked_directory(tenant_id, user_id) as directory:
        rows = _load_manifest(directory)
        if len(rows) + len(normalized) > MAX_PHOTOS:
            raise PhotoError("最多保存20张打卡图片")
        try:
            directory.mkdir(parents=True, exist_ok=True)
            added = []
            for name, data in normalized:
                photo_id = uuid.uuid4().hex
                filename = f"{photo_id}.jpg"
                target = directory / filename
                temp = directory / f".{photo_id}.tmp"
                with temp.open("xb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, target)
                created.append(target)
                added.append({"id": photo_id, "filename": filename, "name": name})
            _save_manifest(directory, rows + added)
            rows.extend(added)
            return [{"id": row["id"], "name": row["name"]} for row in rows]
        except Exception:
            for path in created:
                try:
                    path.unlink()
                except OSError:
                    logger.warning("Failed to roll back an incomplete photo upload")
            raise


def delete_photo(tenant_id: str, user_id: int, photo_id: str) -> list[dict[str, str]]:
    if not re.fullmatch(r"[0-9a-f]{32}", str(photo_id or "")):
        raise FileNotFoundError
    with _locked_directory(tenant_id, user_id) as directory:
        rows = _load_manifest(directory)
        match = next((row for row in rows if row["id"] == photo_id), None)
        if not match:
            raise FileNotFoundError
        remaining = [row for row in rows if row["id"] != photo_id]
        # Commit manifest before removing data; failed manifest writes preserve the photo.
        _save_manifest(directory, remaining)
        try:
            (directory / match["filename"]).unlink()
        except FileNotFoundError:
            logger.debug("Photo file was already absent after manifest update")
        return [{"id": row["id"], "name": row["name"]} for row in remaining]


def read_photo(tenant_id: str, user_id: int, photo_id: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{32}", str(photo_id or "")):
        raise FileNotFoundError
    with _locked_directory(tenant_id, user_id) as directory:
        row = next((item for item in _load_manifest(directory) if item["id"] == photo_id), None)
        if not row:
            raise FileNotFoundError
        path = directory / row["filename"]
        if path.parent != directory or path.is_symlink():
            raise FileNotFoundError
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise FileNotFoundError from None


def choose_photo_bytes(tenant_id: str, user_id: int) -> bytes:
    import random
    with _locked_directory(tenant_id, user_id) as directory:
        rows = _load_manifest(directory)
        if not rows:
            raise PhotoError("已启用打卡照片，但尚未上传照片")
        row = random.choice(rows)
        path = directory / row["filename"]
        if path.parent != directory or path.is_symlink() or not path.is_file():
            raise PhotoError("打卡照片文件缺失")
        return path.read_bytes()


def response_photos(tenant_id: str, user_id: int, enabled: bool, url_prefix: str) -> dict[str, Any]:
    photos = list_photos(tenant_id, user_id)
    for photo in photos:
        photo["url"] = f"{url_prefix}/{photo['id']}"
    return {"photos": photos, "enabled": enabled is True}
