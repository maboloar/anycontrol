"""프로필 저장소: 폴더 안의 <이름>.json.

파일 이름은 프로필 이름에서 만든다. 경로 문자·숨김 파일·폴더 탈출을 막기 위해 글자·숫자·공백·-_ 만 남긴다.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from .schema import Profile

_SAFE = re.compile(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ _-]")


def default_dir() -> Path:
    env = os.environ.get("ANYCONTROL_DATA_DIR") or os.environ.get("VI_DATA_DIR")
    base = Path(env) if env else Path.home() / "Library" / "Application Support" / "AnyControl"
    return base / "profiles"


def slug(name: str) -> str:
    s = _SAFE.sub("", name).strip()[:40]
    if not s or s.startswith("."):
        raise ValueError("프로필 이름에 쓸 수 있는 글자가 없습니다")
    return s


class ProfileStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_dir()

    def _path(self, name: str) -> Path:
        p = (self.root / f"{slug(name)}.json").resolve()
        if p.parent != self.root.resolve():
            raise ValueError("잘못된 프로필 이름")
        return p

    def list(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        out = []
        for f in sorted(self.root.glob("*.json")):
            try:
                p = Profile.model_validate_json(f.read_text(encoding="utf-8"))
                modified = f.stat().st_mtime
            except (ValueError, OSError):
                continue  # 손상된 파일은 목록에서 뺀다
            out.append({"name": p.name, "description": p.description, "mappings": len(p.mappings),
                        "modified": modified})
        return out

    def load(self, name: str) -> Profile:
        p = self._path(name)
        if not p.is_file():
            raise KeyError(name)
        return Profile.model_validate_json(p.read_text(encoding="utf-8"))

    def save(self, profile: Profile) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        p = self._path(profile.name)
        # 동시 저장 요청도 서로의 임시 파일을 덮어쓰거나 지우지 않는다.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root,
                                         prefix=f".{p.stem}-", suffix=".tmp", delete=False) as f:
            tmp = Path(f.name)
            try:
                json.dump(profile.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
                f.close()
                tmp.replace(p)
            finally:
                tmp.unlink(missing_ok=True)

    def delete(self, name: str) -> None:
        p = self._path(name)
        if not p.is_file():
            raise KeyError(name)
        p.unlink()
