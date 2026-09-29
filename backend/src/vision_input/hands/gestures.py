"""손 제스처 → 마우스 동작. 순수 로직 (랜드마크만 받는다).

거리는 모두 손 크기(손목→가운뎃손가락 뿌리)로 나눠 카메라 거리와 무관하다.

동작
- 이동: 손바닥 중심 (손가락을 움직여도 거의 안 흔들리는 점)
- 왼쪽 클릭 / 드래그: 엄지 끝 + 검지 끝 집기 (누르고 있으면 드래그)
- 오른쪽 클릭: 엄지 끝 + 가운뎃손가락 끝 집기
- 스크롤: 검지·중지만 펴고(나머지 접고) 손을 위아래로
- 집기 직전·직후 잠깐 커서를 고정한다 (손가락을 모으는 동작 때문에 커서가 끌려가 클릭 위치가 어긋나는 것 방지)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .detector import (
    INDEX_MCP,
    INDEX_PIP,
    INDEX_TIP,
    MIDDLE_MCP,
    MIDDLE_PIP,
    MIDDLE_TIP,
    PINKY_MCP,
    PINKY_PIP,
    PINKY_TIP,
    RING_MCP,
    RING_PIP,
    RING_TIP,
    THUMB_TIP,
    WRIST,
    Hand,
)


@dataclass
class GestureConfig:
    pinch_on: float = 0.30        # 손 크기 대비. 이보다 가까우면 집음
    pinch_off: float = 0.45       # 이보다 멀어지면 놓음 (히스테리시스)
    press_frames: int = 2         # 연속 몇 프레임 집어야 누름으로 (잡음 방지)
    release_frames: int = 2
    freeze_zone: float = 0.60     # 집기 거리가 이 안으로 들어오면 커서 고정 시작
    freeze_after_press_s: float = 0.12
    freeze_max_s: float = 0.35    # 너무 오래 고정되지 않게
    extend_ratio: float = 1.08    # 손가락 끝이 PIP 보다 이 배 이상 손목에서 멀면 폄
    scroll_gain: float = 40.0     # 손바닥 이동(손 크기 단위) → 스크롤 줄 수


@dataclass
class HandFeatures:
    size: float
    palm: np.ndarray               # (2,) 정규화 이미지 좌표
    pinch_index: float
    pinch_middle: float
    extended: dict[str, bool]


def features(h: Hand, cfg: GestureConfig) -> HandFeatures:
    p = h.points.astype(np.float64)
    d = lambda a, b: float(np.linalg.norm(p[a] - p[b]))  # noqa: E731
    size = max(d(WRIST, MIDDLE_MCP), 1e-4)
    palm = p[[WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP]].mean(0)
    ext = {}
    for name, tip, pip in (("index", INDEX_TIP, INDEX_PIP), ("middle", MIDDLE_TIP, MIDDLE_PIP),
                           ("ring", RING_TIP, RING_PIP), ("pinky", PINKY_TIP, PINKY_PIP)):
        ext[name] = d(tip, WRIST) > cfg.extend_ratio * d(pip, WRIST)
    return HandFeatures(size, palm, d(THUMB_TIP, INDEX_TIP) / size, d(THUMB_TIP, MIDDLE_TIP) / size, ext)


@dataclass
class GestureOutput:
    gesture: str                   # move | left | right | scroll | none
    left: bool
    right: bool
    scroll: float                  # 이번 프레임 스크롤 줄 수 (+ 아래로 내림)
    freeze: bool                   # 커서 고정 중
    features: HandFeatures | None = None


@dataclass
class _Button:
    down: bool = False
    on_count: int = 0
    off_count: int = 0
    t_down: float = -1.0

    def update(self, closed: bool, open_: bool, cfg: GestureConfig, t: float) -> None:
        if not self.down:
            self.on_count = self.on_count + 1 if closed else 0
            if self.on_count >= cfg.press_frames:
                self.down, self.off_count, self.t_down = True, 0, t
        else:
            self.off_count = self.off_count + 1 if open_ else 0
            if self.off_count >= cfg.release_frames:
                self.down, self.on_count = False, 0


@dataclass
class GestureRecognizer:
    cfg: GestureConfig = field(default_factory=GestureConfig)
    left: _Button = field(default_factory=_Button)
    right: _Button = field(default_factory=_Button)
    scroll_anchor: float | None = None
    freeze_since: float | None = None

    def reset(self) -> None:
        self.left, self.right = _Button(), _Button()
        self.scroll_anchor, self.freeze_since = None, None

    def update(self, hand: Hand | None, t: float) -> GestureOutput:
        cfg = self.cfg
        if hand is None:
            # 손이 사라지면 누르던 버튼은 놓는다 (끼인 상태 방지)
            self.reset()
            return GestureOutput("none", False, False, 0.0, False)
        f = features(hand, cfg)
        # 어느 손가락과 집었는지는 '더 가까운 쪽' 으로 가른다. 엄지를 중지에 대면 검지도 가까워지기 쉬우므로
        # 절대 거리만으로는 구분이 안 된다. 셋이 다 붙으면(거의 같은 거리) 왼쪽으로 본다.
        left_closed = f.pinch_index < cfg.pinch_on and f.pinch_index <= f.pinch_middle * 1.2
        self.left.update(left_closed, f.pinch_index > cfg.pinch_off, cfg, t)
        right_closed = (f.pinch_middle < cfg.pinch_on and f.pinch_index > 1.3 * f.pinch_middle
                        and not self.left.down)
        self.right.update(right_closed, f.pinch_middle > cfg.pinch_off, cfg, t)

        # 스크롤: 검지·중지 펴고 약지·새끼 접음, 집지 않음
        e = f.extended
        scroll_pose = e["index"] and e["middle"] and not e["ring"] and not e["pinky"] \
            and not self.left.down and not self.right.down and f.pinch_index > cfg.pinch_off
        scroll = 0.0
        if scroll_pose:
            y = float(f.palm[1]) / f.size
            if self.scroll_anchor is not None:
                scroll = (y - self.scroll_anchor) * cfg.scroll_gain  # 손을 내리면 + (아래로)
            self.scroll_anchor = y
        else:
            self.scroll_anchor = None

        # 커서 고정: 집기 직전(거리가 좁혀지는 중) 또는 누른 직후
        approaching = min(f.pinch_index, f.pinch_middle) < cfg.freeze_zone and not (self.left.down or self.right.down)
        just_pressed = any(b.down and t - b.t_down < cfg.freeze_after_press_s for b in (self.left, self.right))
        want = approaching or just_pressed or scroll_pose
        if want:
            if self.freeze_since is None:
                self.freeze_since = t
            freeze = scroll_pose or t - self.freeze_since < cfg.freeze_max_s or just_pressed
        else:
            self.freeze_since = None
            freeze = False

        g = "left" if self.left.down else "right" if self.right.down else "scroll" if scroll_pose else "move"
        return GestureOutput(g, self.left.down, self.right.down, scroll, freeze, f)
