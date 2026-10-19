"""물체가 '내려놓고 가만히 있는' 순간을 알아챈다 (물체마다 하나).

쓰임 (pipeline)
- 기준점: 흔들거나 뒤집는 동안 광학 흐름 기준점이 물체 옆·위로 밀려날 수 있다. 정지가 anchor_s 이상 이어지면 한 번,
  기준점을 마스크의 바닥 아래-가운데에서 다시 찍는다.
- 자동 분할 재지정: 놓쳤다가 다시 잡은 직후 마스크는 등록 때보다 부정확한 경우가 많다. 다시 잡은 뒤 정지가
  reseg_after_recover_s 이어지면, 또 오래(reseg_long_s) 가만히 있으면 그때마다 지금 프레임에서 다시 분할한다.

정지 판정: 추적 중(쥐지 않음, 손이 거의 안 덮음)이고 정지가 시작된 순간의 중심·크기에서 물체 크기의 몇 % 안에 머무름.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .api import TrackOutput, TrackState


@dataclass
class SettleConfig:
    still_pos: float = 0.04             # 정지 시작 때 중심에서 이 이상(물체 크기 대비) 움직이면 정지가 아니다
    still_scale: float = 0.05           # |log 크기 변화|
    max_hand: float = 0.05              # 손이 덮은 비율이 이보다 크면 정지로 보지 않는다 (손 가림 처리를 켰을 때)
    anchor_s: float = 1.0               # 이만큼 가만히 있으면 기준점을 바닥으로 다시 찍는다 (정지 구간마다 한 번)
    lost_s: float = 0.3                 # 이보다 오래 안 보였다 다시 잡히면 '재추적'
    reseg_after_recover_s: float = 1.0  # 재추적 뒤 이만큼 가만히 있으면 자동 분할 재지정
    reseg_long_s: float = 15.0          # 이만큼 계속 가만히 있으면 자동 분할 재지정 (정지가 이어지면 이 간격마다)
    cooldown_s: float = 5.0             # 자동 재지정 사이 최소 간격


class SettleWatch:
    def __init__(self, cfg: SettleConfig | None = None) -> None:
        self.cfg = cfg or SettleConfig()
        self.ref: tuple[float, float, float, float] | None = None   # 정지 시작 때 (cx, cy, size, scale)
        self.since: float | None = None      # 정지 시작 시각
        self.lost_at: float | None = None    # 안 보이기 시작한 시각
        self.recovered = False               # 재추적 후 아직 다시 분할하지 않음
        self.anchor_done = False             # 이번 정지 구간에 기준점을 이미 다시 찍었나
        self.reseg_at: float | None = None   # 마지막 자동 재지정 시각 (정지 구간 기준)
        self.last_reseg: float = -1e9
        self.pending = False                 # 자동 재지정 요청이 나가 있음

    def update(self, out: TrackOutput, t: float) -> None:
        cfg = self.cfg
        if not out.state.visible:
            if self.lost_at is None:
                self.lost_at = t
            self._break()
            return
        if self.lost_at is not None:
            if t - self.lost_at >= cfg.lost_s:
                self.recovered = True
            self.lost_at = None
        hand = float(out.debug.get("hand_frac", 0.0)) if out.debug else 0.0
        if out.state != TrackState.TRACKING or out.pose is None or out.box is None or hand > cfg.max_hand:
            self._break()
            return
        b = out.box
        size = math.sqrt(max(1.0, (b[2] - b[0]) * (b[3] - b[1])))
        cx, cy, sc = out.pose.cx, out.pose.cy, max(out.pose.scale, 1e-6)
        if self.ref is not None:
            rx, ry, rs, rsc = self.ref
            if math.hypot(cx - rx, cy - ry) <= cfg.still_pos * rs and abs(math.log(sc / rsc)) <= cfg.still_scale:
                return
        self._break()
        self.ref, self.since = (cx, cy, size, sc), t

    def _break(self) -> None:
        self.ref = self.since = self.reseg_at = None
        self.anchor_done = False

    def still_for(self, t: float) -> float:
        return 0.0 if self.since is None else t - self.since

    def anchor_due(self, t: float) -> bool:
        if self.anchor_done or self.still_for(t) < self.cfg.anchor_s:
            return False
        self.anchor_done = True
        return True

    def reseg_due(self, t: float) -> str | None:
        """'recovered' | 'long_still' | None. 돌려주면 pending 이 되고, 끝나면 reseg_done 을 불러야 한다."""
        cfg = self.cfg
        if self.pending or t - self.last_reseg < cfg.cooldown_s:
            return None
        still = self.still_for(t)
        why = None
        if self.recovered and still >= cfg.reseg_after_recover_s:
            why = "recovered"
        elif still >= cfg.reseg_long_s and (self.reseg_at is None or t - self.reseg_at >= cfg.reseg_long_s):
            why = "long_still"
        if why is not None:
            self.pending = True
        return why

    def reseg_done(self, t: float, ok: bool) -> None:
        self.pending = False
        self.last_reseg = t
        if ok:
            self.recovered = False
        self.reseg_at = t
