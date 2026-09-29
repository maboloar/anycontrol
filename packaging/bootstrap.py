"""Installer runs from the verified bundle with managed Python, never system packages."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_files(root: Path, manifest: dict) -> list[str]:
    return [name for name, sha in manifest['files'].items()
            if not (root / name).is_file() or digest(root / name) != sha]


def expected_versions(lock: Path) -> dict[str, str]:
    return dict(re.findall(r'^([\w.-]+)==([^\s;\\]+)', lock.read_text(), re.M))


def run_logged(cmd: list[str], log: Path, env: dict, cwd: Path | None = None) -> None:
    with log.open('a') as out:
        out.write('\n$ ' + ' '.join(cmd) + '\n'); out.flush()
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            print(line, end='', flush=True); out.write(line); out.flush()
        if p.wait():
            raise RuntimeError(f'구성 작업이 실패했습니다. 인터넷/디스크를 확인한 뒤 재실행하세요. 로그: {log}')


def probe(python: Path, versions: dict, env: dict) -> tuple[bool, str]:
    if not python.is_file():
        return False, 'Python 실행 환경 없음'
    code = '''import sys, json, importlib.metadata as m
expected=json.loads(sys.argv[1])
errors=[]
for name, version in expected.items():
 try:
  actual=m.version(name)
  if actual!=version: errors.append(f"{name}: {actual} (필요: {version})")
 except m.PackageNotFoundError: errors.append(f"{name}: 미설치")
if errors: print("\\n".join(errors)); sys.exit(1)
assert sys.version_info[:2]==(3,13)
import cv2, numpy, torch, torchvision, mediapipe, fastapi, uvicorn, websockets
import AVFoundation, CoreMedia, Quartz, libdispatch, Vision
from vision_input.hands.detector import available_backends
assert 'vision' in available_backends(), available_backends()
import efficient_track_anything
from vision_input.server.app import create_app
# Run tiny native computations to catch shared-library/ABI issues before serving.
assert numpy.ones((2,2)).sum()==4
assert cv2.cvtColor(numpy.zeros((2,2,3),dtype=numpy.uint8),cv2.COLOR_BGR2GRAY).shape==(2,2)
assert (torch.ones(2)+1).tolist()==[2.,2.]
if torch.backends.mps.is_available():
 assert (torch.ones(2,device='mps')+1).cpu().tolist()==[2.,2.]
print('환경 검사 통과 · MPS: '+str(torch.backends.mps.is_available()))
'''
    try:
        r = subprocess.run([str(python), '-c', code, json.dumps(versions)], env=env,
                           capture_output=True, text=True, timeout=90)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def existing_server(port: int, version: str) -> bool:
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as r:
            data = json.load(r)
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1) as r:
            title = r.read(2048)
        return data.get('ok') is True and data.get('version') == version and b'AnyControl' in title
    except Exception:
        return False


def choose_port(preferred: int) -> int:
    for port in range(preferred, min(preferred + 30, 65536)):
        with socket.socket() as s:
            try: s.bind(('127.0.0.1', port)); return port
            except OSError: pass
    raise RuntimeError('사용 가능한 로컬 포트가 없습니다.')


def main() -> int:
    parser = argparse.ArgumentParser(description='AnyControl 자동 설치·실행')
    parser.add_argument('--install-dir', type=Path, required=True)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--uv', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='설치·환경 검사 후 종료')
    parser.add_argument('--repair', action='store_true', help='라이브러리 재설치')
    args, server_args = parser.parse_known_args()
    base, root = args.install_dir.resolve(), args.release.resolve()
    source = Path(__file__).resolve().parents[1]
    manifest = json.loads((source / 'manifest.json').read_text())
    logs = base / 'logs'; logs.mkdir(parents=True, exist_ok=True)
    log = logs / ('setup-' + time.strftime('%Y%m%d-%H%M%S') + '.log')
    print(f'설치 위치: {base}\n로그: {log}', flush=True)
    # One installer at a time; a failed process releases this lock automatically.
    with (base / 'setup.lock').open('a') as guard:
        print('프로그램·설치 상태 검사 중…', flush=True)
        fcntl.flock(guard, fcntl.LOCK_EX)
        damaged = verify_files(root, manifest)
        for name in damaged:
            target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target)
        if source != root: shutil.copy2(source / 'manifest.json', root / 'manifest.json')
        if damaged: print(f'누락·손상된 파일 {len(damaged)}개를 복구했습니다.', flush=True)
        lock = root / 'packaging/requirements-macos-arm64.lock'
        # Different dependency sets get separate environments; updates never mutate a running one.
        venv = base / 'environments' / ('py313-' + digest(lock)[:16])
        python = venv / 'bin/python'
        env = os.environ.copy()
        env['PYTHONPATH'] = os.pathsep.join([str(root / 'backend/src'), str(root / 'third_party/EfficientTAM')])
        env['PYTHONNOUSERSITE'] = '1'; env['PYTHONUNBUFFERED'] = '1'
        env['MPLCONFIGDIR'] = str(base / 'cache/matplotlib')
        env['VI_MODELS_DIR'] = str(root / 'models')
        env['UV_SYSTEM_CERTS'] = 'true'
        versions = expected_versions(lock)
        good, detail = probe(python, versions, env)
        if args.repair or not good:
            print('필요한 라이브러리를 설치·복구합니다. 처음에는 수 분 걸릴 수 있습니다.\n' + detail, flush=True)
            if shutil.disk_usage(base).free < 4 * 1024**3:
                raise RuntimeError('초기 설치에는 여유 공간 4GB 이상이 필요합니다.')
            # A broken Python executable/venv is preserved for diagnostics and recreated.
            try:
                python_ok = python.exists() and subprocess.run([str(python), '-c', 'import sys; assert sys.version_info[:2]==(3,13)'], capture_output=True).returncode == 0
            except OSError:
                python_ok = False
            if not python_ok:
                if venv.exists(): venv.rename(venv.with_name(venv.name + '-broken-' + str(time.time_ns())))
                run_logged([str(args.uv), 'venv', str(venv), '--python', sys.executable], log, env)
            cmd = [str(args.uv), 'pip', 'install', '--python', str(python), '--require-hashes', '-r', str(lock)]
            if args.repair or python.exists(): cmd.append('--reinstall')
            run_logged(cmd, log, env)
            run_logged([str(args.uv), 'pip', 'check', '--python', str(python)], log, env)
            good, detail = probe(python, versions, env)
            if not good: raise RuntimeError('설치 후 호환성 검사가 실패했습니다.\n' + detail + '\n로그: ' + str(log))
        print(detail, flush=True)
        with log.open('a') as out: out.write(detail + '\n')
        # Verify the bundled hand model through MediaPipe's native task loader.
        marker = venv / ('models-' + manifest['files']['models/hand_landmarker.task'][:16] + '.ok')
        if not marker.exists() or args.repair:
            code = """from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import os
options=vision.HandLandmarkerOptions(base_options=python.BaseOptions(model_asset_path=os.path.join(os.environ['VI_MODELS_DIR'],'hand_landmarker.task')))
with vision.HandLandmarker.create_from_options(options): pass
print('손 추적 모델 검사 통과')
"""
            run_logged([str(python), '-c', code], log, env)
            marker.write_text('ok\n')
        print('필수 파일·환경 준비 완료.', flush=True)
    if args.check:
        return 0
    port = 8767
    if '--port' in server_args:
        port = int(server_args[server_args.index('--port') + 1])
    if existing_server(port, manifest['version']):
        if '--no-browser' not in server_args: webbrowser.open(f'http://127.0.0.1:{port}')
        print('이미 실행 중인 AnyControl을 열었습니다.'); return 0
    selected = choose_port(port)
    if selected != port:
        print(f'{port} 포트가 사용 중이므로 {selected} 포트에서 실행합니다.')
    if '--port' in server_args: server_args[server_args.index('--port') + 1] = str(selected)
    else: server_args += ['--port', str(selected)]
    print('카메라 권한 요청이 나타나면 허용하세요. 실제 입력 권한은 앱에서 별도로 설정합니다.', flush=True)
    # Managed runtime lives outside the project and has a stable path for macOS permissions.
    return subprocess.call([str(python), '-m', 'vision_input', 'serve', *server_args], cwd=root, env=env)


if __name__ == '__main__':
    try: raise SystemExit(main())
    except KeyboardInterrupt: raise SystemExit(130)
    except Exception as exc:
        print(f'\nAnyControl 설정 실패: {exc}', file=sys.stderr, flush=True)
        raise SystemExit(1)
