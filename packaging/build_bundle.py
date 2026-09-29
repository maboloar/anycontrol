"""Build one executable .command containing verified app, models, UI and uv."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tomllib

UV_SHA = 'a9a8df1eedeb192f2e47e40e2faabfb387db4b850209118786d42f89dde3e0ba'


def build(root: Path, uv_archive: Path, output: Path) -> dict:
    if hashlib.sha256(uv_archive.read_bytes()).hexdigest() != UV_SHA:
        raise ValueError('uv archive checksum does not match official uv 0.12.19 arm64 release')
    version = tomllib.loads((root / 'backend/pyproject.toml').read_text())['project']['version']
    files: dict[str, bytes] = {}
    for name in ('backend/src', 'third_party/EfficientTAM', 'models', 'frontend/dist'):
        for path in sorted((root / name).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo'):
                files[str(path.relative_to(root))] = path.read_bytes()
    for name in ('backend/pyproject.toml', 'packaging/bootstrap.py', 'packaging/uninstall.command.in', 'packaging/requirements-macos-arm64.lock', 'INSTALL.md', 'README.md', 'README-en.md', 'DEVELOPMENT.md', 'THIRD_PARTY.md'):
        files[name] = (root / name).read_bytes()
    for name in ('models/efficienttam_ti_512x512.pt', 'models/hand_landmarker.task', 'frontend/dist/index.html'):
        if not files.get(name): raise ValueError(f'Missing required asset: {name}')
    with tarfile.open(uv_archive) as archive:
        f = archive.extractfile('uv-aarch64-apple-darwin/uv')
        if f is None: raise ValueError('Missing uv binary')
        files['packaging/uv'] = f.read()
    for path in (root / 'packaging/licenses').glob('*'):
        if path.is_file(): files[str(path.relative_to(root))] = path.read_bytes()
    manifest = {'version': version, 'platform': 'macos-14-arm64',
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files['manifest.json'] = json.dumps(manifest, sort_keys=True, indent=2).encode()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as tar:
            for name, data in sorted(files.items()):
                info = tarfile.TarInfo(name); info.size = len(data)
                info.mode = 0o755 if name == 'packaging/uv' else 0o644
                tar.addfile(info, io.BytesIO(data))
    payload = buf.getvalue(); sha = hashlib.sha256(payload).hexdigest()
    template = (root / 'packaging/launcher.sh.in').read_text()
    header = template.replace('@VERSION@', version).replace('@BUNDLE_ID@', version + '-' + sha[:16]).replace('@PAYLOAD_SHA@', sha)
    offset = 1
    while True:
        complete = header.replace('@PAYLOAD_START@', str(offset)).encode()
        actual = len(complete) + 1
        if actual == offset: break
        offset = actual
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix('.tmp')
    tmp.write_bytes(complete + payload); tmp.chmod(0o755); tmp.replace(output)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + '.sha256').write_text(checksum + '  ' + output.name + '\n')
    # 삭제 도구: 같은 폴더에 따로 둔다 (설치 실행파일을 지운 뒤에도 쓸 수 있게)
    un = output.with_name(f'AnyControl-Uninstall-v{version}-macOS.command')
    un_tmp = un.with_suffix('.tmp')
    un_tmp.write_text((root / 'packaging/uninstall.command.in').read_text().replace('@VERSION@', version))
    un_tmp.chmod(0o755); un_tmp.replace(un)
    un_sha = hashlib.sha256(un.read_bytes()).hexdigest()
    un.with_suffix(un.suffix + '.sha256').write_text(un_sha + '  ' + un.name + '\n')
    return {'file': str(output), 'bytes': output.stat().st_size, 'version': version, 'files': len(manifest['files']), 'sha256': checksum,
            'uninstall': str(un), 'uninstall_sha256': un_sha}


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--uv-archive',type=Path,required=True);p.add_argument('--out',type=Path)
    args=p.parse_args();root=Path(__file__).resolve().parents[1]
    version=tomllib.loads((root/'backend/pyproject.toml').read_text())['project']['version']
    output=args.out or root/f'releases/AnyControl-v{version}-macOS.command'
    print(json.dumps(build(root,args.uv_archive,output),ensure_ascii=False,indent=2))
