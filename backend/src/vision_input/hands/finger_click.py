"""마우스를 쥔 것처럼 물체를 엄지·새끼로 잡고, 검지·중지를 든 채로 쓰는 클릭. 순수 로직 (랜드마크만 받는다).

- 기본 자세: 검지·중지(·약지)는 항상 들려 있다. 이 높이를 손가락마다 '기준(ref)' 으로 기억한다.
- 클릭: 손가락이 기준보다 일정 비율 이하로 내려가고(press), 끝이 물체에 닿아 있으면(touch) 누른 것으로 본다.
  물체를 알 수 없는 맨손 마우스에서는 내려감만 본다.
- 검지 = 오른쪽 클릭, 중지 = 왼쪽 클릭. 누르고 있는 동안 버튼이 눌려 있고(드래그), 다시 올라오면 뗀다.
- 높이 = 손바닥 축(손목→가운뎃손가락 뿌리) 방향의 (끝 - 뿌리) / 손 크기. 카메라 거리·손 회전과 무관하다.
- 오인식 방지: 한 번 '들린 상태'를 확인한 뒤에만 누를 수 있고(무장), 약지까지 같이 내려가거나 두 손가락이
  비슷하게 내려가면 손 전체가 구부러진 것으로 보고 무시한다. 손을 크게 휘두르는 동안도 무시한다.
- 누르기 직전 잠깐 커서를 고정하고(손가락이 내려가는 동안 물체가 끌려가는 것 방지), 누른 직후도 잠깐 고정한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .detector import Hand

# (뿌리, 끝) 랜드마크 번호
FINGERS = {"index": (5, 8), "middle": (9, 12), "ring": (13, 16)}
CLICKING = ("index", "middle")
BUTTON = {"index": "right", "middle": "left"}


@dataclass
class FingerClickConfig:
    press: float = 0.60           # 기준 높이의 이 비율 이하로 내려가면 누름 후보
    release: float = 0.75         # 이 비율 이상으로 올라오면 뗌 (히스테리시스)
    armed: float = 0.85           # 이 비율 이상으로 들려 있어야 다음 누름이 가능 (무장)
    armed_frames: int = 3
    press_frames: int = 2
    release_frames: int = 2
    min_ref: float = 0.35         # 기준 높이가 이보다 낮으면 '든 손가락' 이 아니라서 쓰지 않는다
    max_ref: float = 1.3
    ambiguity: float = 0.15       # 두 손가락이 이 이상 차이 나게 내려가지 않으면 손 전체 변형으로 본다
    palm_speed: float = 1.2       # 손바닥 이동 한도 (손 크기/초)
    touch_gap: float = 0.20       # 끝-물체 거리 한도 (손 크기 대비). box 가 있을 때만
    adapt: float = 0.05
    freeze_approach_s: float = 0.35
    freeze_after_press_s: float = 0.12
    freeze_after_release_s: float = 0.1


@dataclass
class _Finger:
    ref: float | None = None
    ratio: float = 1.0
    armed: bool = False
    up: int = 0
    on: int = 0
    off: int = 0
    down: bool = False
    t_down: float = -1e9
    t_release: float = -1e9


@dataclass
class FingerClickOutput:
    left: bool
    right: bool
    freeze: bool
    approaching: str | None       # 내려가는 중인 손가락
    ratios: dict[str, float] = field(default_factory=dict)
    touching: bool = False


def _gap(p: np.ndarray, box: tuple[float, float, float, float]) -> float:
    lo, hi = np.array(box[:2], float), np.array(box[2:], float)
    return float(np.linalg.norm(p - np.clip(p, lo, hi)))


@dataclass
class FingerClickDetector:
    cfg: FingerClickConfig = field(default_factory=FingerClickConfig)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.fingers = {n: _Finger() for n in FINGERS}
        self.prev_palm: np.ndarray | None = None
        self.prev_t: float | None = None
        self.approach_since: float | None = None

    def update(self, hand: Hand | None, t: float,
               box: tuple[float, float, float, float] | None = None) -> FingerClickOutput:
        cfg = self.cfg
        if hand is None or hand.score < 0.5:
            self.reset()
            return FingerClickOutput(False, False, False, None)
        p = hand.points.astype(np.float64)
        axis = p[9] - p[0]
        size = max(float(np.linalg.norm(axis)), 1e-4)
        a = axis / size
        palm = p[[0, 5, 9, 13, 17]].mean(0)
        speed = 0.0
        if self.prev_palm is not None and self.prev_t is not None and t > self.prev_t:
            speed = float(np.linalg.norm(palm - self.prev_palm)) / size / (t - self.prev_t)
        self.prev_palm, self.prev_t = palm, t
        moving = speed > cfg.palm_speed

        for n, (mcp, tip) in FINGERS.items():
            f = self.fingers[n]
            h = float((p[tip] - p[mcp]) @ a) / size
            if f.ref is None:
                f.ref = float(np.clip(h, 0.0, cfg.max_ref))
            if h > f.ref:
                f.ref = min(h, cfg.max_ref)
            f.ratio = h / f.ref if f.ref > 1e-3 else 1.0
            if not f.down and f.ratio >= cfg.release and not moving:
                f.ref += cfg.adapt * (h - f.ref)     # 평소(안 누른) 높이를 천천히 따라간다
            usable = f.ref >= cfg.min_ref
            if usable and f.ratio >= cfg.armed:
                f.up += 1
                if f.up >= cfg.armed_frames:
                    f.armed = True
            else:
                f.up = 0

        r = {n: f.ratio for n, f in self.fingers.items()}
        ring_down = r["ring"] < cfg.press  # 약지까지 내려가면 손 전체가 구부러진 것
        i, m = r["index"], r["middle"]
        # 두 손가락이 비슷하게 내려가면 (손 구부림·기울임) 한쪽을 고를 수 없다
        both_low = i < cfg.release and m < cfg.release
        chosen = None if both_low and abs(i - m) < cfg.ambiguity else ("index" if i < m else "middle")
        touching = True
        if box is not None:
            touching = any(_gap(p[FINGERS[n][1]], box) / size <= cfg.touch_gap for n in CLICKING)

        approaching = None
        for n in CLICKING:
            f = self.fingers[n]
            fingertip_touch = True if box is None else _gap(p[FINGERS[n][1]], box) / size <= cfg.touch_gap
            if not f.down:
                want = (f.armed and f.ratio < cfg.press and fingertip_touch and chosen == n
                        and not ring_down and not moving and f.ref is not None and f.ref >= cfg.min_ref)
                f.on = f.on + 1 if want else 0
                if f.on >= cfg.press_frames:
                    f.down, f.on, f.off, f.armed, f.t_down = True, 0, 0, False, t
                elif f.armed and f.ratio < cfg.armed - 0.05 and not ring_down:
                    approaching = approaching or n
            else:
                f.off = f.off + 1 if f.ratio >= cfg.release else 0
                if f.off >= cfg.release_frames:
                    f.down, f.off, f.t_release = False, 0, t

        # 커서 고정
        just = any(f.down and t - f.t_down < cfg.freeze_after_press_s for f in self.fingers.values()) \
            or any(not f.down and t - f.t_release < cfg.freeze_after_release_s for f in self.fingers.values())
        freeze = just
        if approaching is not None and not any(f.down for f in self.fingers.values()):
            if self.approach_since is None:
                self.approach_since = t
            freeze = freeze or t - self.approach_since < cfg.freeze_approach_s
        else:
            self.approach_since = None
        return FingerClickOutput(self.fingers["middle"].down, self.fingers["index"].down, freeze, approaching,
                                 {k: round(v, 3) for k, v in r.items()}, touching)
