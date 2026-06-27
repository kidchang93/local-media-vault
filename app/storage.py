from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4
import re
import shutil
import subprocess

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps

TOKEN_PATTERN = re.compile(r"\{([a-z_]+)\}")
SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9가-힣._ -]+")
ALLOWED_TOKENS = {
    "user",
    "device",
    "year",
    "month",
    "day",
    "date",
    "folder",
    "media_type",
    "original_name",
    "uuid",
}

IMAGE_MIME_PREFIX = "image/"
VIDEO_MIME_PREFIX = "video/"
COMMON_ROOT_PREFIX = "family"
DEFAULT_STORAGE_TEMPLATE = "{folder}/{date}/{uuid}-{original_name}"


def sanitize_filename(name: str) -> str:
    base = Path(name or "upload").name.strip().replace("/", "_").replace("\\", "_")
    base = SAFE_NAME_PATTERN.sub("_", base)
    return base or "upload"


def normalize_relative_folder(path: str) -> str:
    cleaned = (path or "").strip().strip("/")
    if not cleaned:
        return ""
    if Path(cleaned).is_absolute():
        raise HTTPException(status_code=400, detail="절대경로는 사용할 수 없습니다.")

    parts = []
    for part in Path(cleaned).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise HTTPException(status_code=400, detail="상위 폴더 참조는 사용할 수 없습니다.")
        parts.append(sanitize_filename(part))
    return "/".join(parts)


def classify_media(mime_type: str) -> str:
    if mime_type.startswith(IMAGE_MIME_PREFIX):
        return "image"
    if mime_type.startswith(VIDEO_MIME_PREFIX):
        return "video"
    raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {mime_type}")


def render_template(
    template: str,
    *,
    user: str,
    device: str,
    folder: str,
    media_type: str,
    original_name: str,
) -> str:
    unknown = set(TOKEN_PATTERN.findall(template)) - ALLOWED_TOKENS
    if unknown:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 저장 템플릿 토큰입니다: {sorted(unknown)}")

    now = datetime.now()
    file_uuid = uuid4().hex
    safe_original = sanitize_filename(original_name)
    values = {
        "user": sanitize_filename(user),
        "device": sanitize_filename(device or user),
        "year": f"{now:%Y}",
        "month": f"{now:%m}",
        "day": f"{now:%d}",
        "date": f"{now:%Y-%m-%d}",
        "folder": normalize_relative_folder(folder),
        "media_type": media_type,
        "original_name": safe_original,
        "uuid": file_uuid,
    }

    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)

    if "{original_name}" not in template:
        rendered = f"{rendered.rstrip('/')}/{file_uuid}-{safe_original}"

    return rendered


def build_user_storage_path(root_prefix: str, folder: str, rendered_template: str, template: str) -> str:
    root = normalize_relative_folder(root_prefix)
    folder_path = normalize_relative_folder(folder)
    rendered = normalize_relative_folder(rendered_template)

    if folder_path and "{folder}" not in template:
        rendered = f"{folder_path}/{rendered}"

    if not root:
        raise HTTPException(status_code=400, detail="사용자 저장 루트가 설정되지 않았습니다.")
    return f"{root}/{rendered}" if rendered else root


def build_family_storage_path(folder: str, original_name: str, media_type: str) -> str:
    folder_path = normalize_relative_folder(folder)
    if not folder_path:
        raise HTTPException(status_code=400, detail="저장할 앨범 폴더를 선택하세요.")

    rendered = render_template(
        DEFAULT_STORAGE_TEMPLATE,
        user=COMMON_ROOT_PREFIX,
        device=COMMON_ROOT_PREFIX,
        folder=folder_path,
        media_type=media_type,
        original_name=original_name,
    )
    return build_user_storage_path(
        COMMON_ROOT_PREFIX,
        folder_path,
        rendered,
        DEFAULT_STORAGE_TEMPLATE,
    )


def resolve_inside(root: Path, relative_path: str) -> Path:
    root_resolved = root.resolve()
    target = (root_resolved / relative_path).resolve()
    if not target.is_relative_to(root_resolved):
        raise HTTPException(status_code=400, detail="저장 경로가 허용된 루트 밖으로 벗어났습니다.")
    return target


async def save_upload_file(upload: UploadFile, target: Path, max_size_bytes: int) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with target.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > max_size_bytes:
                output.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="파일 크기 제한을 초과했습니다.")
            output.write(chunk)
    return size


def create_thumbnail(source: Path, thumbnail_root: Path, media_type: str, upload_id: int) -> str | None:
    thumbnail_root.mkdir(parents=True, exist_ok=True)
    relative = Path(f"{upload_id}.jpg")
    target = thumbnail_root / relative

    try:
        if media_type == "image":
            with Image.open(source) as image:
                image = ImageOps.exif_transpose(image)
                image.thumbnail((640, 640))
                image.convert("RGB").save(target, "JPEG", quality=82)
        elif media_type == "video":
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    "00:00:01",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale='min(640,iw)':-2",
                    str(target),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            return None
    except Exception:
        target.unlink(missing_ok=True)
        return None

    return str(relative)


def remove_file_quietly(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
