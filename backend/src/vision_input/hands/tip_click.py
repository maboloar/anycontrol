"""검지·중지 끝점 추적 결과 → 클릭. 순수 로직.

'원래 자리(손가락을 들고 있을 때의 끝점)에서 일정 거리 이상 내려와 물체에 가까이 닿으면' 누른 것으로 본다.
- 원래 자리(rest)는 랜드마크를 믿을 수 있어 점을 보정하는 동안(손가락이 곧게 들린 상태)의 점을 물체 기준 좌표로 기억한다
  → 손과 물체가 함께 움직여도 기준이 따라온다.
- 눌림 = (rest 에서 이동 ≥ drop) 이고 (끝-물체 박스 거리 ≤ touch) 이고 (rest 보다 물체에 그만큼 가까워짐).
- 검지 = 오른쪽, 중지 = 왼쪽. 누르는 동안 버튼이 눌려 있고 (드래그), 원래 자리 근처로 돌아오면 뗀다.
- 단위는 모두 손 크기. 손 크기는 랜드마크를 볼 때 물체 크기와의 비로 기억해, 랜드마크가 없을 때도 물체 크기로 환산한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .finger_click import BUTTON, CLICKING, FingerClickOutput
from .tip_track import TipFrame


@dataclass
class TipClickConfig:
    drop: float = 0.30            # rest 에서 이만큼(손 크기) 이동해야 누름 후보
    touch: float = 0.20           # 끝-물체 거리 한도 (손 크기)
    release_ratio: float = 0.6    # 이동이 drop 의 이 비율 아래로 돌아오면 뗌
    rearm_ratio: float = 0.4      # 뗀 뒤 이 비율 아래로 돌아와 있어야 다시 누를 수 있음
    press_frames: int = 2
    release_frames: int = 2
    rest_frames: int = 3          # 곧게 든 점이 이만큼 보여야 rest 확정
    rest_adapt: float = 0.3
    min_conf: float = 0.35
    lost_release_s: float = 0.2   # 점을 잃은 채 눌려 있으면 이 시간 뒤 뗌
    ambiguity: float = 0.1        # 두 손가락이 함께 내려가면 이 이상 차이 나야 한쪽으로 인정
    freeze_approach_s: float = 0.35
    freeze_after_press_s: float = 0.12
    freeze_after_release_s: float = 0.1


@dataclass
class _F:
    rest_q: np.ndarray | None = None     # 물체 기준 좌표 (물체 중심에서의 오프셋 / 손 크기)
    rest_n: int = 0
    armed: bool = False
    down: bool = False
    on: int = 0
    off: int = 0
    t_down: float = -1e9
    t_release: float = -1e9
    t_seen: float = -1e9
    moved: float = 0.0
    gap: float = 9.0


@dataclass
class TipClickDetector:
    cfg: TipClickConfig = field(default_factory=TipClickConfig)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.f = {n: _F() for n in BUTTON}
        self.hs_rel: float | None = None     # 손 크기(px) / 물체 박스 높이(px)
        self.approach_since: float | None = None

    def has_rest(self, name: str) -> bool:
        return self.f[name].rest_q is not None

    @property
    def ready_any(self) -> bool:
        """한 손가락이라도 rest 가 잡혀 있다 (없는 손가락은 호출한 쪽이 다른 방식으로 채운다)."""
        return any(self.f[n].rest_q is not None for n in CLICKING)

    def debug(self, name: str) -> dict:
        f = self.f[name]
        return {"moved": round(f.moved, 2), "gap": round(f.gap, 2), "armed": f.armed, "rest": f.rest_q is not None}

    @property
    def ready(self) -> bool:
        """두 손가락 모두 rest 가 잡혀 이 방식으로 판정할 수 있다."""
        return all(self.f[n].rest_q is not None for n in CLICKING)

    def update(self, t: float, frame: TipFrame | None, box: tuple[float, float, float, float] | None) -> FingerClickOutput:
        c = self.cfg
        if frame is None or box is None:
            return self._lost(t)
        w, h = frame.size
        b = np.array([box[0] * w, box[1] * h, box[2] * w, box[3] * h], float)
        bh = max(b[3] - b[1], 1.0)
        center = np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])
        if frame.landmark_fresh and frame.hand_size > 0:
            r = frame.hand_size / bh
            self.hs_rel = r if self.hs_rel is None else 0.7 * self.hs_rel + 0.3 * r
        if self.hs_rel is None:
            return self._lost(t)
        hs = self.hs_rel * bh

        def gap_of(p: np.ndarray) -> float:
            return float(np.linalg.norm(p - np.clip(p, b[:2], b[2:]))) / hs

        for name in CLICKING:
            f, tip = self.f[name], frame.tips[name]
            if tip.valid and tip.conf >= c.min_conf:
                f.t_seen = t
                p = tip.xy
                raised_now = (t - tip.anchored_t <= 0.15 and not f.down
                              and (f.rest_q is None or f.moved < 0.5 * c.drop))  # 내려가는 중의 점으로 기준을 끌어내리지 않는다
                if raised_now:
                    q = (p - center) / hs
                    f.rest_q = q if f.rest_q is None else f.rest_q + c.rest_adapt * (q - f.rest_q)
                    f.rest_n += 1
                    if f.rest_n >= c.rest_frames:
                        f.armed = True
                if f.rest_q is not None:
                    rest_p = center + f.rest_q * hs
                    f.moved = float(np.linalg.norm(p - rest_p)) / hs
                    f.gap = gap_of(p)
                    gap_rest = gap_of(rest_p)
                    near = f.gap <= c.touch and (gap_rest - f.gap) >= 0.5 * c.drop
                    if not f.down:
                        if not f.armed and f.moved <= c.rearm_ratio * c.drop:
                            f.rest_n += 1
                            f.armed = f.rest_n >= c.rest_frames
                        f.on = f.on + 1 if (f.armed and f.moved >= c.drop and near) else 0
                    else:
                        far_now = f.moved < c.release_ratio * c.drop or f.gap > c.touch * 1.8
                        f.off = f.off + 1 if far_now else 0
            elif f.down and t - f.t_seen > c.lost_release_s:
                f.down, f.off, f.on = False, 0, 0
                f.t_release, f.armed, f.rest_n = t, False, 0
            elif not f.down:
                f.on = 0

        # 두 손가락이 함께 내려가면 (손 전체가 내려앉음) 더 많이 내려간 쪽만 인정
        i, m = self.f["index"], self.f["middle"]
        both = i.on > 0 and m.on > 0
        if both and abs(i.moved - m.moved) < c.ambiguity:
            i.on = m.on = 0
        elif both:
            (m if i.moved > m.moved else i).on = 0
        for f in self.f.values():
            if not f.down and f.on >= c.press_frames:
                f.down, f.on, f.off, f.t_down, f.armed, f.rest_n = True, 0, 0, t, False, 0
            elif f.down and f.off >= c.release_frames:
                f.down, f.off, f.t_release = False, 0, t
        return self._out(t)

    def _lost(self, t: float) -> FingerClickOutput:
        for f in self.f.values():
            if f.down and t - f.t_seen > self.cfg.lost_release_s:
                f.down, f.t_release = False, t
        return self._out(t)

    def _out(self, t: float) -> FingerClickOutput:
        c = self.cfg
        any_down = any(f.down for f in self.f.values())
        just = any(f.down and t - f.t_down < c.freeze_after_press_s for f in self.f.values()) or \
            any(not f.down and t - f.t_release < c.freeze_after_release_s for f in self.f.values())
        approaching = next((n for n in CLICKING if not self.f[n].down and self.f[n].armed
                            and self.f[n].moved >= 0.4 * c.drop and t - self.f[n].t_seen < 0.2), None)
        freeze = just
        if approaching is not None and not any_down:
            if self.approach_since is None:
                self.approach_since = t
            freeze = freeze or t - self.approach_since < c.freeze_approach_s
        else:
            self.approach_since = None
        return FingerClickOutput(self.f["middle"].down, self.f["index"].down, freeze, approaching,
                                 {n: round(self.f[n].moved, 3) for n in CLICKING}, any(self.f[n].gap <= c.touch for n in CLICKING))
