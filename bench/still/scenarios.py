"""정지 장면 생성.

synthetic-still : 실제 영상 한 프레임을 그대로 반복 + 센서 잡음 + 완만한 조명 변화 (물체는 진짜로 정지)
synthetic-move  : 위 장면에서 정지 뒤 카메라가 일정 속도로 평행 이동 (정지 잠금이 풀리는 속도 측정)
real-still      : 영상 파일의 처음 N 프레임 (손이 들어오기 전; 정답은 '대체로 정지')
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WIDTH = 1280


@dataclass
class Scene:
    name: str
    frames: list[np.ndarray]
    box: tuple[float, float, float, float]   # 등록 박스 (px, WIDTH 기준)
    fps: float = 30.0
    onset: int | None = None                  # 움직임 시작 프레임 (synthetic-move)
    shift: float = 0.0                        # 프레임당 이동 (px)
    moved: int = 0                            # 움직인 프레임 수
    warmup: int = 15
    truth: list | None = None                 # 프레임별 실제 이동 (dx, dy) px, 물체 패치 위상 상관 (real-still)


def read_frames(path: str, start: int, count: int, step: int = 1) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(ROOT / path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    out = []
    for i in range(count * step):
        ok, f = cap.read()
        if not ok:
            break
        if i % step == 0:
            k = WIDTH / f.shape[1]
            out.append(cv2.resize(f, (WIDTH, round(f.shape[0] * k)), interpolation=cv2.INTER_AREA))
    cap.release()
    return out


def noisy(base: np.ndarray, n: int, sigma: float = 2.5, flicker: float = 0.015, drift_gain: float = 0.04,
          seed: int = 0) -> list[np.ndarray]:
    """base 를 n 번 반복하고 프레임마다 (1) 가우시안 센서 잡음 (2) 0.5Hz 조명 깜빡임 (3) 느린 전체 밝기 변화를 얹는다."""
    rng = np.random.default_rng(seed)
    f32 = base.astype(np.float32)
    out = []
    for i in range(n):
        gain = 1.0 + flicker * np.sin(2 * np.pi * 0.5 * i / 30.0) + drift_gain * (i / max(n - 1, 1) - 0.5)
        img = f32 * gain + rng.normal(0.0, sigma, f32.shape).astype(np.float32)
        out.append(np.clip(img, 0, 255).astype(np.uint8))
    return out


def shifted(frames: list[np.ndarray], onset: int, shift: float, moved: int) -> list[np.ndarray]:
    """onset 프레임부터 moved 프레임 동안 오른쪽으로 프레임당 shift px 평행 이동 (그 뒤엔 멈춤)."""
    out = []
    for i, f in enumerate(frames):
        dx = shift * float(np.clip(i - onset + 1, 0, moved))
        if dx == 0:
            out.append(f)
            continue
        M = np.float32([[1, 0, dx], [0, 1, 0]])
        out.append(cv2.warpAffine(f, M, (f.shape[1], f.shape[0]), borderMode=cv2.BORDER_REPLICATE))
    return out


def patch_motion(frames: list[np.ndarray], box, pad: int = 40) -> list:
    """첫 프레임 대비 물체 패치의 이동 (위상 상관, 서브픽셀). 물체가 진짜 움직이는지 추적기와 독립적으로 본다."""
    x1, y1, x2, y2 = (int(v) for v in box)
    def patch(f):
        return cv2.cvtColor(f[y1 - pad:y2 + pad, x1 - pad:x2 + pad], cv2.COLOR_BGR2GRAY).astype(np.float32)
    ref = patch(frames[0])
    win = cv2.createHanningWindow(ref.shape[::-1], cv2.CV_32F)
    return [tuple(cv2.phaseCorrelate(ref, patch(f), win)[0]) for f in frames]


# test.mov 첫 프레임: 지갑이 책상에 놓여 있다 (손 없음). 1280 폭 기준 박스.
WALLET_BOX = (0.53 * WIDTH, 0.45 * 720, 0.72 * WIDTH, 0.57 * 720)


def build(name: str, seconds: float = 10.0) -> Scene:
    n = int(seconds * 30)
    if name == "synthetic-still":
        base = read_frames("samples/test.mov", 0, 1)[0]
        return Scene(name, noisy(base, n), WALLET_BOX)
    if name == "synthetic-move":
        base = read_frames("samples/test.mov", 0, 1)[0]
        frames = shifted(noisy(base, 140), onset=70, shift=2.5, moved=40)
        return Scene(name, frames, WALLET_BOX, onset=70, shift=2.5, moved=40)
    if name == "real-still":
        # 지갑에 손이 닿기 전 (프레임 ~45). 손으로 든 iPhone 이라 지갑은 천천히 화면 안에서 흘러간다 → truth 로 보정
        frames = read_frames("samples/test.mov", 0, 24, step=2)   # 60fps 원본을 30fps 로
        return Scene(name, frames, WALLET_BOX, truth=patch_motion(frames, WALLET_BOX))
    raise SystemExit(f"unknown scene {name!r}")


SCENES = ["synthetic-still", "synthetic-move", "real-still"]
