"""트래커 공통 인터페이스.

모든 트래커(기준선, 본 트래커, 오프라인 참조 모델)는 이 계약을 지킨다.
평가 하네스와 실시간 엔진이 같은 인터페이스를 쓰므로, 하네스 점수가 곧 실사용 동작이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

import numpy as np


class TrackState(str, Enum):
    TRACKING = "tracking"            # 물체가 보이고 측정이 신뢰됨
    GRASPED = "grasped"              # 손에 쥐어 크게 가려졌지만 손 결합으로 유지
    OCCLUDED = "occluded"            # 가려짐: 값 유지, 전역 탐색 금지
    SEARCHING = "searching"          # 신뢰도 낮음: 넓은 영역 탐색 중
    LOST = "lost"                    # 놓침: 전역 재검출

    @property
    def visible(self) -> bool:
        return self in (TrackState.TRACKING, TrackState.GRASPED)


@dataclass(slots=True)
class Pose:
    """물체의 화면 포즈. scale 은 등록 시 크기 대비 배율, angle 은 도(연속, wrap 없음)."""

    cx: float
    cy: float
    scale: float = 1.0
    angle: float = 0.0
    aspect: float = 1.0  # 등록 대비 종횡비 변화 (측면 카메라의 면외 회전 신호)


Box = tuple[float, float, float, float]  # x1, y1, x2, y2


@dataclass(slots=True)
class RefinedMask:
    """마스크 모델(Tier 1)이 본 가장 최근 마스크. 비동기라 몇 프레임 늦게 도착한다.

    M 은 그 마스크 시각 → 지금으로 옮기는 2x3 유사변환 (원본 좌표, 그 사이 Tier 0 움직임).
    펜촉처럼 정밀한 기하가 필요할 때 Tier 0 마스크(색·형태 추정) 대신 쓴다."""

    mask: np.ndarray                     # bool (H, W) 원본 해상도
    M: np.ndarray                        # (2, 3)
    age: float                           # 초


@dataclass(slots=True)
class TrackOutput:
    """계약: state.visible 이면 pose 는 None 이 아니다. pose.angle 은 등록 대비 연속 각도."""

    state: TrackState
    box: Box | None = None               # 보이는 부분 박스
    pose: Pose | None = None             # 가림 포함 전체 물체(amodal) 포즈
    mask: np.ndarray | None = None       # 보이는 부분 bool (H, W), 선택
    confidence: float = 0.0
    debug: dict = field(default_factory=dict)
    refined: RefinedMask | None = None   # 정밀 마스크를 요청한 물체만 (InitPrompt.kind == "pen")


@dataclass(slots=True)
class InitPrompt:
    """등록 입력. 박스 또는 마스크 (둘 다 있으면 마스크 우선).

    kind="pen": 가늘고 긴 물체. 트래커는 Tier 1 마스크를 원본 해상도로 함께 내보낸다 (TrackOutput.refined)."""

    box: Box | None = None
    mask: np.ndarray | None = None
    kind: str = "object"


class Tracker(Protocol):
    name: str

    def add(self, frame: np.ndarray, obj_id: int, prompt: InitPrompt) -> TrackOutput:
        """frame 에서 물체를 등록한다."""

    def step(self, frame: np.ndarray, t: float) -> dict[int, TrackOutput]:
        """다음 프레임. t 는 초 단위 캡처 시각 (프레임을 건너뛰면 간격이 커진다)."""

    def remove(self, obj_id: int) -> None: ...


def mask_to_box(mask: np.ndarray) -> Box | None:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    return float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)


def box_iou(a: Box | None, b: Box | None) -> float:
    if a is None or b is None:
        return 0.0
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0
