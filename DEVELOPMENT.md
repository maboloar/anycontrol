# 개발 / Development

macOS 14 이상·Apple Silicon 환경에서 실행합니다. Python 3.12 이상(3.13 권장), Node.js 빌드 22.12 이상 / 테스트 22.22.2 이상 또는 24.15 이상이 필요합니다.
Run on macOS 14+ and Apple Silicon. Use Python 3.12+ (3.13 recommended), Node.js 22.12+ for builds, and 22.22.2+ or 24.15+ for tests.

## 환경 구성 / Setup

프로젝트 루트에서 실행합니다. Python 3.13으로 잠금 파일을 설치하는 것을 권장합니다. 모델 2개는 `models/`에 있으며 외부 소스는 `third_party/EfficientTAM/`에서 직접 로드합니다.
Run from the project root. Python 3.13 is recommended for the locked dependencies. The two runtime models are in `models/`; vendored code is loaded directly from `third_party/EfficientTAM/`.

```bash
python3.13 -m venv backend/.venv
backend/.venv/bin/python -m pip install --require-hashes -r packaging/requirements-macos-arm64.lock
backend/.venv/bin/python -m pip install -e 'backend[dev]'
npm --prefix frontend ci
npm --prefix frontend run build
python3 server.py
```

## 검사 / Checks

```bash
PYTHONPATH=backend/src:third_party/EfficientTAM backend/.venv/bin/python -m pytest backend/tests -q -p no:warnings
npm --prefix frontend run typecheck
npm --prefix frontend test
backend/.venv/bin/python packaging/test_packaging.py
```

## 릴리스 빌드 / Build a release

프런트엔드를 다시 빌드한 다음 uv 공식 릴리스에서 고정된 아카이브를 받습니다. 빌더가 SHA-256을 검사합니다.
Rebuild the frontend, then download the pinned archive from the official uv release. The builder checks its SHA-256.

```bash
npm --prefix frontend run build
curl -fL https://github.com/astral-sh/uv/releases/download/0.12.19/uv-aarch64-apple-darwin.tar.gz -o /tmp/anycontrol-uv.tar.gz
backend/.venv/bin/python packaging/build_bundle.py --uv-archive /tmp/anycontrol-uv.tar.gz
```

`releases/`에 생성된 설치·삭제 `.command`와 두 `.sha256` 파일을 GitHub Release에 첨부합니다. 실행파일에는 모델·빌드된 화면·필수 외부 소스가 포함됩니다. 소스나 화면을 수정하면 반드시 재빌드하세요.
Attach the launcher, uninstaller and both `.sha256` files from `releases/` to the GitHub Release. The launcher includes models, the built UI and required external code. Rebuild after changing source or UI.

`node_modules/`, `.venv/`, 빌드·캐시와 `releases/`는 Git에서 제외합니다. 앱 버전은 `backend/pyproject.toml`, `backend/src/vision_input/__init__.py`, npm 패키지·잠금 파일, `frontend/index.html`과 배포 안내에서 함께 갱신합니다.
Dependencies, environments, generated files and `releases/` are ignored by Git. Update the app version together in backend metadata, `__init__.py`, npm manifests and lock files, the frontend title and distribution guides.
