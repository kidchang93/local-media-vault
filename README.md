# local-media-vault

같은 Wi-Fi에서만 사용하는 개인용 로컬 미디어 업로드 서버입니다.

모바일 웹으로 접속해 iPhone 원본 사진과 영상을 업로드하고, 맥북에 마운트된 J3 같은 로컬/외장 저장소에 저장하는 것을 목표로 합니다. 클라우드 저장소나 외부 공개 서버 없이, 업로드할 때만 Docker로 서버를 켜는 흐름을 전제로 합니다.

## 목표 기능

- 로컬 Wi-Fi 전용 모바일 웹 업로드
- `lck`, `cse` 로그인 기반 사용자 구분
- 공통 `family` 저장소 아래 앨범 폴더 생성/선택
- 앨범별 날짜 폴더 자동 생성
- 사진 썸네일과 영상 대표 프레임 미리보기
- Docker 기반 실행
- SQLite 기반 로컬 메타데이터 저장

## 실행 흐름

```bash
cp .env.example .env
# .env에서 J3_MOUNT_PATH, APP_BASE_URL, 초기 비밀번호를 수정
docker compose up
```

백그라운드로 실행하려면 다음처럼 실행합니다.

```bash
docker compose up -d
```

코드나 정적 UI를 수정한 뒤 이미지를 다시 만들고 컨테이너를 교체하려면 다음 순서로 실행합니다.

```bash
docker compose build
docker compose up -d
```

상태와 로그 확인:

```bash
docker compose ps
docker compose logs -f app
curl -s http://127.0.0.1:8000/health
```

중지:

```bash
docker compose down
```

서버가 시작되면 접속 URL과 QR 코드를 출력합니다. Docker 컨테이너 안에서는 맥의 Wi-Fi IP를 자동으로 안정적으로 알 수 없으므로, 모바일에서 바로 스캔하려면 `.env`의 `APP_BASE_URL`을 맥의 같은 Wi-Fi 주소로 설정하세요.

예:

```env
APP_BASE_URL=http://192.168.0.10:8000
```

맥의 Wi-Fi IP는 다음 명령으로 확인할 수 있습니다.

```bash
ipconfig getifaddr en0
```

명령 결과가 `192.168.0.10`이라면 `.env`에 다음처럼 적습니다.

```env
APP_BASE_URL=http://192.168.0.10:8000
```

`en0`에서 값이 나오지 않으면 현재 Wi-Fi 인터페이스 이름을 확인합니다.

```bash
networksetup -listallhardwareports
```

출력에서 `Hardware Port: Wi-Fi` 아래의 `Device` 값을 확인한 뒤, 예를 들어 `en1`이면 다음처럼 실행합니다.

```bash
ipconfig getifaddr en1
```

모바일 브라우저에서는 같은 Wi-Fi에 연결한 뒤 `.env`에 적은 주소로 접속합니다.

```text
http://192.168.0.10:8000
```

기본 계정은 첫 실행 시 SQLite DB에 생성됩니다.

- `admin`
- `lck`
- `cse`

초기 비밀번호는 `.env`의 `ADMIN_PASSWORD`, `LCK_PASSWORD`, `CSE_PASSWORD` 값입니다. DB가 이미 생성된 뒤에는 환경 변수를 바꿔도 기존 비밀번호가 자동 변경되지는 않습니다.

## 로컬 검증용 실행

J3나 외장 저장소를 연결하지 않고 앱 기동만 확인할 때는 임시로 `/tmp`를 마운트해서 실행할 수 있습니다. 실제 미디어 저장용이 아니라 개발 검증용입니다.

```bash
J3_MOUNT_PATH=/tmp docker compose build
J3_MOUNT_PATH=/tmp docker compose up -d
curl -s http://127.0.0.1:8000/health
J3_MOUNT_PATH=/tmp docker compose logs --tail=60 app
```

검증용 컨테이너를 중지하려면 다음을 실행합니다.

```bash
J3_MOUNT_PATH=/tmp docker compose down
```

이미 SQLite DB가 생성된 뒤에는 `.env`의 초기 비밀번호를 바꿔도 기존 계정 비밀번호는 자동 갱신되지 않습니다. 개발 중 초기 계정을 다시 만들려면 서버를 내린 뒤 `./data/vault.sqlite3`를 삭제하고 다시 실행합니다.

## 저장소 원칙

- 원본 미디어 파일은 DB에 넣지 않고 외장/로컬 파일시스템에 저장합니다.
- DB에는 사용자, 권한, 폴더 메타데이터, 업로드 기록, 썸네일 상태만 저장합니다.
- 실제 저장소 루트는 환경 변수로 설정합니다.
- SQLite DB와 썸네일은 Docker named volume이 아니라 로컬 `./data` 폴더에 저장합니다.

예시:

```env
UPLOAD_ROOT=/media/j3/local-media-vault
```

Docker Compose에서는 호스트의 `J3_MOUNT_PATH`를 컨테이너의 `/media/j3`에 연결합니다.

`J3_MOUNT_PATH`에는 `/Volumes` 같은 상위 폴더가 아니라 실제 마운트된 디스크 경로를 넣어야 합니다.

예:

```env
J3_MOUNT_PATH=/Volumes/SAMSUNG
```

실행 전에 맥에서 쓰기 가능한지 확인합니다.

```bash
mkdir -p "$J3_MOUNT_PATH/local-media-vault"
touch "$J3_MOUNT_PATH/local-media-vault/.write-test"
rm "$J3_MOUNT_PATH/local-media-vault/.write-test"
```

여기서 실패하면 Docker에서도 `/media/j3/local-media-vault`를 만들 수 없습니다. 외장 디스크가 읽기 전용으로 마운트되었는지, 실제 디스크 경로가 맞는지, macOS Finder에서 해당 위치에 파일을 만들 수 있는지 먼저 확인하세요.

마운트 상태는 다음 명령으로 확인할 수 있습니다.

```bash
mount | grep /Volumes/SAMSUNG
```

출력에 `ntfs`와 `read-only`가 보이면 macOS가 해당 디스크를 읽기 전용으로 마운트한 상태입니다. 이 경우 앱과 Docker 모두 저장할 수 없습니다. 해결 방법은 다음 중 하나를 선택합니다.

- 외장 디스크를 exFAT 또는 APFS처럼 macOS에서 쓰기 가능한 파일시스템으로 포맷합니다.
- macOS에서 NTFS 쓰기를 지원하는 별도 드라이버를 사용합니다.
- 우선 개발 검증은 맥 내부의 쓰기 가능한 폴더나 `/tmp`로 실행합니다.

쓰기 가능한 맥 내부 폴더로 임시 실행하는 예:

```bash
mkdir -p "$HOME/local-media-vault-storage"
J3_MOUNT_PATH="$HOME/local-media-vault-storage" docker compose up -d
```

## 저장 규칙

업로드 파일은 공통 `family` 폴더 아래에 저장됩니다. 사용자는 화면에서 앨범 폴더를 만들거나 기존 폴더를 선택하고, 앱은 그 아래에 날짜 폴더를 자동으로 만듭니다.

예:

```text
local-media-vault/family/travel/jeju/2026-06-27/uuid-IMG_0012.HEIC
local-media-vault/family/events/birthday/2026-06-27/uuid-IMG_0013.MOV
```

앨범 폴더는 `travel/jeju`처럼 계층형으로 입력할 수 있습니다. 절대경로나 `..` 상위 폴더 참조는 사용할 수 없습니다.

## SQLite 확인

DB 파일은 로컬 `./data/vault.sqlite3`에 저장됩니다. 컨테이너를 내렸다가 다시 올려도 이 파일은 유지됩니다.

```bash
sqlite3 ./data/vault.sqlite3
```

자주 확인하는 쿼리:

```sql
SELECT id, username, display_name, root_prefix, created_at FROM users;
SELECT id, original_name, stored_relative_path, created_at FROM uploads ORDER BY id DESC LIMIT 20;
```

## 로컬 API

- `POST /api/login`
- `POST /api/logout`
- `GET /api/me`
- `GET /api/folders`
- `POST /api/folders`
- `PATCH /api/folders/{id}`
- `POST /api/uploads`
- `GET /api/uploads`
- `GET /api/uploads/{id}/thumbnail`

## 주의

- 인터넷 공개를 전제로 하지 않습니다. 같은 Wi-Fi 로컬 접속용입니다.
- iPhone 원본 사진/영상은 그대로 저장하고, 미리보기 생성 실패는 업로드 실패로 처리하지 않습니다.
