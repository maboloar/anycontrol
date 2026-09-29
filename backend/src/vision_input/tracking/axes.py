"""추적 결과 → 원시 축 값 (중립 기준 상대값).

단위는 물체·카메라와 무관하게 정했다. 매핑 엔진이 사용자 범위로 -1..1 에 맞춘다.
    x       중심 좌우 이동 / 프레임 폭
    y       중심 상하 이동 / 프레임 높이 (아래 +)
    depth   log(크기 / 중립 크기). 카메라에 가까워지면 + (옆 카메라에서 앞뒤 밀기)
    angle   화면상 주축 각도 변화 (도, 연속). 시계방향 +
    stretch log(길쭉함 / 중립 길쭉함). 면외 회전(옆에서 본 책상 위 회전)에서 변함
    contact 바닥 접촉선 이동 / 프레임 높이 (아래 +). 손이 위를 가려도 영향이 적은 깊이 신호
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .api import Pose
from .measure import AngleTracker, MaskMeasure

# 주의: pose.aspect 는 등록 대비 비율(1 = 그대로), 마스크 elongation 은 절대 길쭉함.
# 한 물체는 처음부터 끝까지 같은 출처를 쓰므로 stretch = log(현재/중립) 은 둘 다 올바르다.

AXES = ("x", "y", "depth", "angle", "stretch", "contact")


@dataclass
class AxisSample:
    cx: float
    cy: float
    scale: float        # 등록 크기 대비
    angle: float | None  # 연속 각도
    elongation: float | None
    bottom_y: float | None


@dataclass
class AxisState:
    frame_size: tuple[int, int]
    neutral: AxisSample | None = None
    last: AxisSample | None = None
    angle: AngleTracker = field(default_factory=AngleTracker)

    def sample(self, pose: Pose | None, meas: MaskMeasure | None, size0: float) -> AxisSample | None:
        """출처를 섞지 않는다 (섞으면 값이 튄다).

        - 트래커가 pose(가림 포함 전체 물체 추정, 각도는 등록 대비 연속값)를 주면 위치·크기·각도·길쭉함은 모두 pose.
        - pose 가 없으면 보이는 마스크의 모멘트.
        - 접촉선은 항상 보이는 마스크에서 (손이 위를 가려도 아래 경계는 보통 보인다). 없으면 직전 값.
        """
        if pose is None and meas is None:
            return None
        prev_bottom = self.last.bottom_y if self.last else None
        bottom = meas.bottom_y if meas is not None else prev_bottom
        if pose is not None:
            s = AxisSample(pose.cx, pose.cy, pose.scale, pose.angle, pose.aspect, bottom)
        else:
            assert meas is not None
            ang = self.angle.update(meas.angle, meas.angle_valid)
            s = AxisSample(meas.cx, meas.cy, meas.size / size0, ang, meas.elongation, bottom)
        self.last = s
        if self.neutral is None:
            self.neutral = s
        return s

    # 책상 축 (보정했을 때만). (x m, z m, yaw 도|None)
    desk: tuple[float, float, float | None] | None = None
    desk_neutral: tuple[float, float, float | None] | None = None

    def sample_desk(self, d: tuple[float, float, float | None] | None) -> None:
        if d is None:
            return
        if self.desk_neutral is None or (self.desk_neutral[2] is None and d[2] is not None):
            self.desk_neutral = d
        self.desk = d

    def clear_desk(self) -> None:
        self.desk = self.desk_neutral = None

    def rebase(self, before: AxisSample | None, after: AxisSample | None) -> None:
        """다시 등록(모양 다시 기억)하면 크기·각도·길쭉함의 기준이 새 마스크로 바뀐다. 중립도 같은 만큼 옮겨
        같은 자세에서 축 값(depth·angle·stretch)이 그대로이게 한다. 위치(x·y·contact)는 절대값이라 그대로 둔다."""
        n = self.neutral
        if n is None or before is None or after is None:
            return
        scale = n.scale * after.scale / before.scale if before.scale > 0 else n.scale
        angle = n.angle
        if n.angle is not None and before.angle is not None and after.angle is not None:
            angle = n.angle + (after.angle - before.angle)
        elong = n.elongation
        if n.elongation and before.elongation and after.elongation:
            elong = n.elongation * after.elongation / before.elongation
        self.neutral = AxisSample(n.cx, n.cy, scale, angle, elong, n.bottom_y)

    def set_neutral(self) -> None:
        if self.last is not None:
            self.neutral = self.last
        if self.desk is not None:
            self.desk_neutral = self.desk

    def desk_values(self) -> dict[str, float | None]:
        d, n = self.desk, self.desk_neutral
        if d is None or n is None:
            return {"desk_x": None, "desk_z": None, "desk_yaw": None}
        yaw = None if d[2] is None or n[2] is None else round(d[2] - n[2], 3)
        return {"desk_x": round(d[0] - n[0], 5), "desk_z": round(d[1] - n[1], 5), "desk_yaw": yaw}

    def values(self) -> dict[str, float | None]:
        s, n = self.last, self.neutral
        if s is None or n is None:
            return dict.fromkeys(AXES)
        w, h = self.frame_size

        def diff(a: float | None, b: float | None, k: float = 1.0) -> float | None:
            return None if a is None or b is None else round((a - b) / k, 5)

        return {
            "x": diff(s.cx, n.cx, w),
            "y": diff(s.cy, n.cy, h),
            "depth": round(math.log(max(s.scale, 1e-6) / max(n.scale, 1e-6)), 5),
            "angle": diff(s.angle, n.angle),
            "stretch": None if not (s.elongation and n.elongation) else round(math.log(s.elongation / n.elongation), 5),
            "contact": diff(s.bottom_y, n.bottom_y, h),
        }
