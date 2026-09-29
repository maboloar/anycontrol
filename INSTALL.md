# 설치 및 배포 / Installation and distribution

사용자 설치·실행·종료·삭제·문제 해결

개발 및 배포 파일 빌드: [DEVELOPMENT.md](DEVELOPMENT.md).

## 실행파일 옵션 / Launcher options

```bash
./AnyControl-v1.0.0-macOS.command --check   # 설치·환경 검사 / Install and check
./AnyControl-v1.0.0-macOS.command --repair  # 라이브러리 복구 후 실행 / Repair and run
```

## 삭제 도구 옵션 / Uninstaller options

```bash
./AnyControl-Uninstall-v1.0.0-macOS.command --dry-run
./AnyControl-Uninstall-v1.0.0-macOS.command --yes                 # 프로필 보존 / Keep profiles
./AnyControl-Uninstall-v1.0.0-macOS.command --yes --remove-profiles
```

릴리스의 `.sha256` 파일을 실행파일과 같은 폴더에 내려받고 다음과 같이 무결성을 확인할 수 있습니다.
Download each `.sha256` file alongside its executable to verify integrity:

```bash
shasum -a 256 -c AnyControl-v1.0.0-macOS.command.sha256
shasum -a 256 -c AnyControl-Uninstall-v1.0.0-macOS.command.sha256
```
