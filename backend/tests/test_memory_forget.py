"""물체 기억 선택 삭제: 등록 모습은 남기고 고른 AI 앵커·재획득만 지운다 (Tier 1 조건 프레임 포함)."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from vision_input.tracking import memory_view
from vision_input.tracking.tier1 import ObjectMemory, StreamingTAM
from vision_input.tracking.vi_tracker import ViTracker


def _snap(kind: str, t: float) -> memory_view.Snapshot:
    return memory_view.Snapshot(kind, t, np.zeros((4, 4, 3), np.uint8), np.ones((4, 4), bool))


def test_tier1_forget_drops_matching_anchor_only() -> None:
    tam = StreamingTAM.__new__(StreamingTAM)
    mem = ObjectMemory(cond={0: {}, 5: {}, 9: {}}, non_cond={10: {}}, anchor_scales=[0.0, 0.4, -0.4],
                       cond_t={5: 1.0, 9: 2.0})
    tam.mem = {1: mem}
    assert tam.forget(1, [1.0]) == 1
    assert sorted(mem.cond) == [0, 9] and mem.anchor_scales == [0.0, -0.4] and not mem.non_cond
    assert tam.forget(1, [7.0]) == 0 and tam.forget(2, [2.0]) == 0


def test_tracker_forget_keeps_registration() -> None:
    tr = SimpleNamespace(memory_views=[_snap("registration", 0.5), _snap("anchor", 1.0), _snap("reacquired", 2.0)])
    tracker = ViTracker.__new__(ViTracker)
    tracker.tracks = {3: tr}
    tracker.tam = None
    n = tracker.forget_memory(3, [("registration", 0.5), ("anchor", 1.0005), ("reacquired", 9.0)])
    assert n == 1
    assert [s.kind for s in tr.memory_views] == ["registration", "reacquired"]


def test_thumbnail_uses_registration_view() -> None:
    tracker = ViTracker.__new__(ViTracker)
    tracker.tracks = {1: SimpleNamespace(memory_views=[_snap("anchor", 1.0)]), 2: SimpleNamespace(memory_views=[_snap("registration", 0.0)])}
    assert tracker.thumbnail(1) is None
    assert tracker.thumbnail(2).startswith("data:image/jpeg;base64,")
