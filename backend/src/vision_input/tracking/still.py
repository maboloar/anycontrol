"""정지 잠금: 물체가 확실히 멈춰 있을 때 포즈·마스크를 붙잡아 둔다.

왜 필요한가 (bench/still 실측, 10초 정지 장면)
- 여러 출처의 측정(색 영역 마스크, Tier 1 마스크, 2초마다 하는 재분할 보정)은 각자 조금씩 다른 면적·중심을 낸다.
  가만히 있어도 칼만 필터가 이 측정들 사이를 오가고, 특히 재분할 보정이 2초마다 크기를 0.7% 밀어낸다.
- 크기 기반 깊이 커서는 크기 변화를 앞뒤 이동으로 읽으므로 이 작은 변화가 커서를 흔든다 (24 px/s, 10초에 50 px 흐름).
- 점 추적의 정지 판정(ZUPT)은 그 프레임의 점 추적 이동만 0 으로 만들 뿐, 다른 측정이 밀어내는 것은 막지 못한다.

동작
- 점 추적이 일정 프레임 연속으로 조용하면 '잠금'. 잠긴 동안
  · 점 추적 이동은 누적했다가 잡음 수준을 넘을 때만 반영한다 (느린 실제 이동은 놓치지 않고, 잡음은 쌓이지 않는다).
  · 색 영역·Tier 1·재분할 보정 측정은 포즈에서 충분히 벗어나는 상태가 연속 몇 번 확인될 때만 받는다 (잡음 수준은 버림).
  · 보이는 마스크는 잠금 직전 프레임들의 다수결로 고정해 윤곽이 깜빡이지 않게 한다. 색 모델도 학습하지 않는다.
- 즉시 푼다: 점 추적이 의미 있는 이동을 보일 때, 손이 닿거나 가려질 때, 상태가 TRACKING 이 아닐 때, 순간이동(재검출·재정렬).
  풀 때 칼만 위치 불확실성을 다시 키워 곧바로 따라갈 수 있게 한다.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np


@dataclass
class StillConfig:
    enabled: bool = True                 # bench/still (정지 떨림 65배↓, 이동 반응 유지)와 회귀 평가(합성 50개 무회귀) 통과로 기본 켬
    enter_frames: int = 10               # 점 추적이 이만큼 연속으로 조용하면 잠금 (30fps 에서 약 0.33초)
    min_region_conf: float = 0.3         # 잠글 때 색 영역도 물체를 보고 있어야 한다
    max_hand_frac: float = 0.05          # 손이 이만큼 이상 덮으면 잠그지 않고, 잠겼으면 푼다
    # 점 추적 이동 누적: 이 값을 넘으면 포즈에 반영 (물체 크기 배, 하한 px / log-scale / 도)
    pos_commit: float = 0.015
    pos_commit_floor: float = 0.8
    ls_commit: float = 0.012
    th_commit: float = 0.8
    # 다른 측정이 이만큼 벗어나야 '불일치'. confirm 번 연속이면 푼다 (한 번의 튐은 버린다)
    pos_gate: float = 0.04
    pos_gate_floor: float = 2.5
    ls_gate: float = 0.05
    th_gate: float = 3.0
    confirm: int = 3
    lost_points_frames: int = 15         # 점 추적을 이만큼 못 얻으면 (움직임 증거가 없다) 푼다
    release_sigma: float = 0.02          # 풀 때 위치 표준편차를 물체 크기의 이 비율 이상으로 (정지 아닌 구간의 보통 수준; 크게 키우면 가려진 구간의 편향된 측정을 과신한다)
    mask_votes: int = 9                  # 잠글 때 마스크 다수결에 쓰는 최근 프레임 수


@dataclass
class StillStats:
    locks: int = 0
    releases: dict = field(default_factory=dict)
    rejected: dict = field(default_factory=dict)
    committed: int = 0


class StillLock:
    """물체 하나의 정지 상태. ViTracker 가 단계마다 부른다."""

    def __init__(self, cfg: StillConfig) -> None:
        self.cfg = cfg
        self.locked = False
        self.calm = 0
        self.acc = np.zeros(4)
        self.breach = 0
        self.no_points = 0
        self.masks: deque = deque(maxlen=cfg.mask_votes)
        self.stats = StillStats()

    # ---------------------------------------------------------------- 점 추적
    def commit_limits(self, size: float) -> np.ndarray:
        c = self.cfg
        return np.array([max(c.pos_commit_floor, c.pos_commit * size)] * 2 + [c.ls_commit, c.th_commit])

    def integrate(self, raw: np.ndarray, size: float) -> np.ndarray | None:
        """잠긴 동안 점 추적이 낸 프레임 간 이동(dx, dy, dlog s, dθ)을 누적한다.
        한 축이라도 한계를 넘으면 지금까지 누적을 돌려주고 비운다 (그 이동만 포즈에 반영). 아니면 None.
        잡음은 √n 으로 쌓이고 실제 이동은 n 으로 쌓이므로, 느리게 움직이는 물체도 결국 반영된다."""
        self.no_points = 0
        self.acc += raw
        lim = self.commit_limits(size)
        if np.any(np.abs(self.acc) >= lim):
            step, self.acc = self.acc.copy(), np.zeros(4)
            self.stats.committed += 1
            return step
        return None

    def missing_points(self) -> bool:
        """점 추적을 못 얻은 프레임. 오래 이어지면 움직임 증거가 없으므로 푼다. True 면 풀어야 한다."""
        self.no_points += 1
        return self.locked and self.no_points >= self.cfg.lost_points_frames

    # ---------------------------------------------------------------- 상태
    def observe(self, calm: bool, mask: np.ndarray | None) -> None:
        """잠기기 전에 매 프레임 부른다: 조용한 프레임 수와 최근 마스크를 센다."""
        self.calm = self.calm + 1 if calm else 0
        if mask is not None and mask.any() and calm:
            self.masks.append(mask)
        elif not calm:
            self.masks.clear()

    def ready(self, *, hand_frac: float, region_conf: float, tracking: bool, disagree: int) -> bool:
        c = self.cfg
        return (c.enabled and not self.locked and tracking and self.calm >= c.enter_frames
                and hand_frac <= c.max_hand_frac and region_conf >= c.min_region_conf and disagree == 0
                and len(self.masks) >= 3)

    def lock(self) -> np.ndarray:
        """잠근다. 최근 마스크의 다수결을 고정 마스크로 돌려준다."""
        stack = np.stack(list(self.masks)).astype(np.uint8)
        stable = stack.sum(0) * 2 > len(stack)
        if not stable.any():
            stable = self.masks[-1]
        self.locked = True
        self.acc[:] = 0
        self.breach = 0
        self.no_points = 0
        self.stats.locks += 1
        return stable

    def release(self, reason: str) -> bool:
        """푼다. 잠겨 있었으면 True."""
        was = self.locked
        self.locked = False
        self.calm = 0
        self.acc[:] = 0
        self.breach = 0
        self.no_points = 0
        self.masks.clear()
        if was:
            self.stats.releases[reason] = self.stats.releases.get(reason, 0) + 1
        return was

    # ---------------------------------------------------------------- 다른 측정
    def accept(self, src: str, d_pos: float, d_ls: float | None, d_th: float | None, size: float) -> bool:
        """잠긴 동안 들어온 측정(현재 포즈 대비 차이)을 받을지. 안 잠겼으면 항상 True.

        포즈에서 크게 벗어나는 상태가 연속 confirm 번 확인되면 True (그리고 호출한 쪽이 release 한다)."""
        if not self.locked:
            return True
        c = self.cfg
        breach = (d_pos > max(c.pos_gate_floor, c.pos_gate * size)
                  or (d_ls is not None and abs(d_ls) > c.ls_gate)
                  or (d_th is not None and abs(d_th) > c.th_gate))
        if breach:
            self.breach += 1
            if self.breach >= c.confirm:
                return True
        else:
            self.breach = 0
        self.stats.rejected[src] = self.stats.rejected.get(src, 0) + 1
        return False
