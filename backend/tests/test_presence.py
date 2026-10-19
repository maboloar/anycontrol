"""사람 접근 감지: 배경보다 크게 가까워진 영역이 넓어지면 present. 전체 스케일·이동 변화는 무시."""
from __future__ import annotations

import numpy as np

from vision_input.presence import PresenceWatch


def _scene() -> np.ndarray:
    y = np.linspace(0, 1, 96)[:, None]
    return np.repeat(0.2 + 0.6 * y, 128, axis=1).astype(np.float32)  # 아래(가까운 책상)로 갈수록 가까움


def test_empty_scene_and_global_rescale_are_not_presence() -> None:
    w = PresenceWatch()
    assert w.update(_scene())["present"] is False          # 첫 깊이 = 배경
    assert w.update(_scene() * 1.7 + 0.3)["present"] is False


def test_person_close_to_camera_is_presence() -> None:
    w = PresenceWatch()
    w.update(_scene())
    d = _scene()
    d[10:70, 30:90] = 1.6                                    # 화면 가운데를 크게 가린 가까운 사람
    s = w.update(d)
    assert s["present"] is True and s["near"] > 0.2
    w.reset()
    assert w.state()["ready"] is False
