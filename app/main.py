from __future__ import annotations

import errno
from pathlib import Path
import re
import sqlite3
import socket

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.db import (
    authenticate_user,
    connect,
    create_session,
    delete_session,
    get_user_by_session,
    init_db,
)
from app.storage import (
    COMMON_ROOT_PREFIX,
    classify_media,
    build_family_storage_path,
    normalize_relative_folder,
    prune_empty_directories,
    remove_file_quietly,
    resolve_inside,
    save_upload_file,
)

try:
    import qrcode
except ImportError:
    qrcode = None

app = FastAPI(title="local-media-vault")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

SESSION_COOKIE = "lmv_session"
DATE_FOLDER_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FolderCreate(BaseModel):
    relativePath: str
    displayName: str | None = None


class FolderUpdate(BaseModel):
    relativePath: str | None = None
    displayName: str | None = None


@app.on_event("startup")
def startup() -> None:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    ensure_writable_upload_root(settings.upload_root)
    init_db(
        settings.db_path,
        {
            "admin": settings.admin_password,
            "lck": settings.lck_password,
            "cse": settings.cse_password,
        },
    )
    print_startup_urls(settings)


def ensure_writable_upload_root(upload_root: Path) -> None:
    try:
        upload_root.mkdir(parents=True, exist_ok=True)
        probe = upload_root / ".local-media-vault-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        if exc.errno == errno.EROFS:
            hint = (
                f"{upload_root} is read-only. Check that J3_MOUNT_PATH points to the actual "
                "mounted drive, not /Volumes, and that the drive is writable on macOS."
            )
        else:
            hint = f"{upload_root} is not writable: {exc}"
        raise RuntimeError(hint) from exc


def print_startup_urls(settings: Settings) -> None:
    urls = []
    if settings.app_base_url:
        urls.append(settings.app_base_url.rstrip("/"))
    elif running_in_docker():
        urls.append(f"http://localhost:{settings.app_port}")
    else:
        for ip in detect_lan_ips():
            urls.append(f"http://{ip}:{settings.app_port}")

    if not urls:
        urls = [f"http://localhost:{settings.app_port}"]

    print("\nlocal-media-vault is ready.")
    if running_in_docker() and not settings.app_base_url:
        print(
            "Docker detected. Set APP_BASE_URL=http://<Mac Wi-Fi IP>:"
            f"{settings.app_port} for a mobile-friendly URL and QR code."
        )
    for url in urls:
        print(f"Mobile URL: {url}")
        if qrcode is not None:
            qr = qrcode.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        else:
            print("QR output skipped because qrcode is not installed.")
    print()


def running_in_docker() -> bool:
    return Path("/.dockerenv").exists()


def detect_lan_ips() -> list[str]:
    ips = []
    hostname = socket.gethostname()
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET)
    except socket.gaierror:
        return ips

    for info in infos:
        ip = info[4][0]
        if not ip.startswith("127.") and ip not in ips:
            ips.append(ip)
    return ips


def folder_response(
    relative_path: str,
    *,
    folder_id: int | None = None,
    display_name: str | None = None,
    created_at: str | None = None,
) -> dict:
    parts = relative_path.split("/") if relative_path else []
    parent_path = "/".join(parts[:-1]) if len(parts) > 1 else ""
    return {
        "id": folder_id,
        "relativePath": relative_path,
        "displayName": display_name or (parts[-1] if parts else relative_path),
        "createdAt": created_at,
        "depth": max(len(parts) - 1, 0),
        "parentPath": parent_path,
    }


def discover_family_folders(upload_root: Path) -> set[str]:
    family_root = resolve_inside(upload_root, COMMON_ROOT_PREFIX)
    if not family_root.exists():
        return set()

    folders = set()
    for path in family_root.rglob("*"):
        if path.is_dir():
            relative = path.relative_to(family_root).as_posix()
            parts = relative.split("/")
            if relative and not any(DATE_FOLDER_PATTERN.match(part) for part in parts):
                folders.add(relative)
    return folders


def get_current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    settings: Settings = Depends(get_settings),
):
    if not session_token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    row = get_user_by_session(settings.db_path, session_token)
    if not row:
        raise HTTPException(
            status_code=401,
            detail="세션이 만료되었거나 유효하지 않습니다.",
        )
    return dict(row)


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/login")
def login(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    settings: Settings = Depends(get_settings),
):
    user = authenticate_user(settings.db_path, username, password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )

    token = create_session(settings.db_path, user["id"])
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return {"ok": True}


@app.post("/api/logout")
def logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    settings: Settings = Depends(get_settings),
):
    if session_token:
        delete_session(settings.db_path, session_token)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(get_current_user)):
    return {
        "username": user["username"],
        "displayName": user["display_name"],
        "role": user["role"],
        "permissions": {
            "canUpload": bool(user["can_upload"]),
            "canCreateFolder": bool(user["can_create_folder"]),
            "canModifyFolder": bool(user["can_modify_folder"]),
            "canDelete": bool(user["can_delete"]),
        },
        "rootPrefix": user["root_prefix"],
        "defaultTemplate": user["default_template"],
    }


@app.get("/api/uploads")
def list_uploads(
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    with connect(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, original_name, stored_relative_path, media_type, mime_type, size_bytes,
                   thumbnail_status, created_at
            FROM uploads
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 10
            """,
            (user["id"],),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "originalName": row["original_name"],
            "storedRelativePath": row["stored_relative_path"],
            "mediaType": row["media_type"],
            "mimeType": row["mime_type"],
            "sizeBytes": row["size_bytes"],
            "thumbnailStatus": row["thumbnail_status"],
            "createdAt": row["created_at"],
            "previewUrl": f"/api/uploads/{row['id']}/preview",
        }
        for row in rows
    ]


@app.get("/api/folders")
def list_folders(
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    root_path = resolve_inside(settings.upload_root, COMMON_ROOT_PREFIX)
    root_path.mkdir(parents=True, exist_ok=True)
    with connect(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, relative_path, display_name, created_at
            FROM folders
            ORDER BY relative_path
            """
        ).fetchall()

    by_path = {
        row["relative_path"]: folder_response(
            row["relative_path"],
            folder_id=row["id"],
            display_name=row["display_name"],
            created_at=row["created_at"],
        )
        for row in rows
    }
    for relative_path in discover_family_folders(settings.upload_root):
        by_path.setdefault(relative_path, folder_response(relative_path))

    return [by_path[key] for key in sorted(by_path)]


@app.post("/api/folders")
def create_folder(
    payload: FolderCreate,
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    if not user["can_create_folder"]:
        raise HTTPException(status_code=403, detail="폴더 생성 권한이 없습니다.")

    folder_path = normalize_relative_folder(payload.relativePath)
    if not folder_path:
        raise HTTPException(status_code=400, detail="폴더 경로가 필요합니다.")

    full_relative = f"{COMMON_ROOT_PREFIX}/{folder_path}"
    target = resolve_inside(settings.upload_root, full_relative)
    target.mkdir(parents=True, exist_ok=True)

    display_name = payload.displayName or folder_path.split("/")[-1]
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO folders (owner_user_id, relative_path, display_name)
            VALUES (?, ?, ?)
            """,
            (user["id"], folder_path, display_name),
        )

    return folder_response(folder_path, display_name=display_name)


@app.patch("/api/folders/{folder_id}")
def update_folder(
    folder_id: int,
    payload: FolderUpdate,
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    if not user["can_modify_folder"]:
        raise HTTPException(status_code=403, detail="폴더 수정 권한이 없습니다.")

    with connect(settings.db_path) as conn:
        row = conn.execute(
            """
            SELECT id, relative_path, display_name
            FROM folders
            WHERE id = ? AND owner_user_id = ?
            """,
            (folder_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다.")

        new_relative_path = row["relative_path"]
        if payload.relativePath is not None:
            new_relative_path = normalize_relative_folder(payload.relativePath)
            if not new_relative_path:
                raise HTTPException(status_code=400, detail="폴더 경로가 필요합니다.")
            existing = conn.execute(
                """
                SELECT id
                FROM folders
                WHERE owner_user_id = ? AND relative_path = ? AND id != ?
                """,
                (user["id"], new_relative_path, folder_id),
            ).fetchone()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail="대상 폴더가 이미 등록되어 있습니다.",
                )

            source = resolve_inside(
                settings.upload_root,
                f"{COMMON_ROOT_PREFIX}/{row['relative_path']}",
            )
            target = resolve_inside(
                settings.upload_root,
                f"{COMMON_ROOT_PREFIX}/{new_relative_path}",
            )
            if source.exists() and source != target:
                if target.exists():
                    raise HTTPException(
                        status_code=409,
                        detail="대상 폴더가 이미 존재합니다.",
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                source.rename(target)
            else:
                target.mkdir(parents=True, exist_ok=True)

        new_display_name = payload.displayName or row["display_name"]
        try:
            conn.execute(
                """
                UPDATE folders
                SET relative_path = ?, display_name = ?
                WHERE id = ? AND owner_user_id = ?
                """,
                (new_relative_path, new_display_name, folder_id, user["id"]),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="대상 폴더가 이미 등록되어 있습니다.",
            ) from exc

    return folder_response(new_relative_path, folder_id=folder_id, display_name=new_display_name)


@app.get("/api/uploads/{upload_id}/preview")
def preview_upload(
    upload_id: int,
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    with connect(settings.db_path) as conn:
        row = conn.execute(
            """
            SELECT stored_relative_path, mime_type
            FROM uploads
            WHERE id = ? AND user_id = ?
            """,
            (upload_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="업로드 파일을 찾을 수 없습니다.")

    path = resolve_inside(settings.upload_root, row["stored_relative_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="원본 파일이 없습니다.")
    return FileResponse(path, media_type=row["mime_type"])


@app.post("/api/test-data/clear")
def clear_test_data(
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="관리자만 테스트 데이터를 삭제할 수 있습니다.")

    with connect(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT stored_relative_path, thumbnail_relative_path
            FROM uploads
            """
        ).fetchall()

    for row in rows:
        remove_file_quietly(resolve_inside(settings.upload_root, row["stored_relative_path"]))
        if row["thumbnail_relative_path"]:
            remove_file_quietly(resolve_inside(settings.thumbnail_root, row["thumbnail_relative_path"]))

    with connect(settings.db_path) as conn:
        conn.execute("DELETE FROM uploads")
        conn.execute("DELETE FROM folders")

    prune_empty_directories(resolve_inside(settings.upload_root, COMMON_ROOT_PREFIX))
    prune_empty_directories(settings.thumbnail_root)
    return {"ok": True, "deletedUploads": len(rows)}


@app.post("/api/uploads")
async def upload_files(
    files: list[UploadFile] = File(...),
    folder: str = Form(""),
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    if not user["can_upload"]:
        raise HTTPException(status_code=403, detail="업로드 권한이 없습니다.")

    results = []

    for upload in files:
        original_name = upload.filename or "upload"
        mime_type = upload.content_type or "application/octet-stream"
        media_type = classify_media(mime_type)
        relative_path = build_family_storage_path(folder, original_name, media_type)
        target = resolve_inside(settings.upload_root, relative_path)
        size = await save_upload_file(upload, target, settings.max_file_size_bytes)

        with connect(settings.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO uploads (
                  user_id, original_name, stored_relative_path, media_type, mime_type, size_bytes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user["id"], original_name, relative_path, media_type, mime_type, size),
            )
            upload_id = cursor.lastrowid

        with connect(settings.db_path) as conn:
            conn.execute(
                """
                UPDATE uploads
                SET thumbnail_relative_path = NULL, thumbnail_status = ?
                WHERE id = ?
                """,
                ("original", upload_id),
            )

        results.append(
            {
                "id": upload_id,
                "originalName": original_name,
                "storedRelativePath": relative_path,
                "mediaType": media_type,
                "mimeType": mime_type,
                "sizeBytes": size,
                "thumbnailStatus": "original",
                "previewUrl": f"/api/uploads/{upload_id}/preview",
            }
        )

    return {"uploads": results}
