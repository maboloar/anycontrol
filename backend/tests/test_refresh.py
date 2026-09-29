from concurrent.futures import Future
import math

import numpy as np
import pytest

from vision_input.tracking.api import InitPrompt
from vision_input.tracking.refresh import RefreshAnchor, choose_mask
from vision_input.tracking.tier0 import _lab_index
from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker
from vision_input.tracking import gpu, segment


def scene():
    image = np.full((120, 180, 3), 180, np.uint8)
    image[40:80, 60:110] = (30, 70, 210)
    mask = np.zeros((120, 180), bool)
    mask[40:80, 60:110] = True
    return image, mask


def tracker():
    image, mask = scene()
    tr = ViTracker(TrackerConfig(tier1="off", smooth=False))
    tr.add(image, 1, InitPrompt(mask=mask))
    tr.configure_refresh(True, .5)
    return tr, image, mask


def anchor(tr, mask, forbidden=None):
    obj = tr.tracks[1]
    return RefreshAnchor(mask, np.zeros_like(mask) if forbidden is None else forbidden,
                         obj.anchor_mask, obj.anchor_color, obj.p_in0)


def test_segmentation_accepts_original_shape_but_rejects_background_spill_and_other_object():
    tr, image, mask = tracker()
    idx = _lab_index(image)
    assert choose_mask([mask], [.9], anchor(tr, mask), idx) is not None
    spilled = mask.copy()
    spilled[10:100, 40:140] = True
    assert choose_mask([spilled], [.99], anchor(tr, spilled), idx) is None
    forbidden = mask.copy()
    assert choose_mask([mask], [.99], anchor(tr, mask, forbidden), idx) is None
    other = np.zeros_like(mask)
    other[40:80, 120:170] = True
    assert choose_mask([other], [.99], anchor(tr, mask), idx) is None


def test_same_color_neighbor_join_is_rejected_by_registered_shape():
    tr, image, mask = tracker()
    image[40:80, 110:170] = (30, 70, 210)
    joined = np.zeros_like(mask)
    joined[40:80, 60:170] = True
    assert choose_mask([joined], [.99], anchor(tr, joined), _lab_index(image)) is None


class ExactSegmenter:
    name = "exact-test"
    def __init__(self, mask):
        self.mask = mask
    def segment(self, image, box=None, points=None):
        return segment.SegResult([self.mask], [.95])


def test_periodic_segmentation_has_one_inflight_job_and_gently_corrects_small_drift(monkeypatch):
    tr, image, mask = tracker()
    small, _, idx = tr._prep(image)
    obj = tr.tracks[1]
    # 물체가 정지했는데 누적 오차로 크기만 약 5% 커진 상황.
    obj.kf.x[2] = math.log(1.05)
    pending = Future()
    submitted = []
    def submit(fn, *args):
        submitted.append((fn, args))
        return pending
    monkeypatch.setattr(gpu, "submit", submit)
    monkeypatch.setattr(segment, "default_segmenter", lambda: ExactSegmenter(mask))
    tr._refresh_submit(small, idx, 0)
    tr._refresh_submit(small, idx, 1)
    assert len(submitted) == 1
    fn, args = submitted[0]
    pending.set_result(fn(*args))
    tr._refresh_collect(.1)
    assert 0 <= obj.kf.x[2] < math.log(1.05)
    assert tr.refresh_stats["applied"] == 1 and not obj.teleported
    tr._refresh_submit(small, idx, 1.9)
    assert len(submitted) == 1
    tr._refresh_submit(small, idx, 2.1)
    assert len(submitted) == 2


def test_budget_slows_refresh_for_expensive_jobs_and_disabled_mode_does_no_work():
    tr, image, mask = tracker()
    tr.refresh_ms = 800
    assert tr.refresh_effective_hz == pytest.approx(.1875)
    tr.configure_refresh(False, .5)
    small, _, idx = tr._prep(image)
    tr._refresh_submit(small, idx, 100)
    assert tr.refresh_job is None


def test_pause_invalidates_pending_correction(monkeypatch):
    tr, image, mask = tracker()
    pending = Future()
    monkeypatch.setattr(gpu, "submit", lambda *args: pending)
    monkeypatch.setattr(segment, "default_segmenter", lambda: ExactSegmenter(mask))
    small, _, idx = tr._prep(image)
    tr._refresh_submit(small, idx, 0)
    tr.resume(5)
    pending.set_result(({1: (mask, .95)}, 100., "exact-test"))
    tr._refresh_collect(5)
    assert tr.refresh_stats["applied"] == 0 and tr.refresh_job is None


def test_fragmented_mask_selects_overlap_component_and_ignores_background_label():
    tr, image, mask = tracker()
    fragmented = mask.copy()
    fragmented[::3, ::3] = True
    # prior 바깥의 점들은 서로 분리되어 있고 금지 영역 비율 검사를 통과한다.
    result = choose_mask([fragmented], [.9], anchor(tr, mask), _lab_index(image))
    assert result is not None
    assert (result[0] & mask).sum() == mask.sum()
    assert result[0].sum() < mask.sum() * 1.1
    assert choose_mask([np.zeros_like(mask)], [.9], anchor(tr, mask), _lab_index(image)) is None


def collect_mask(tr, mask, confidence=.95):
    from vision_input.tracking.vi_tracker import _T1Job
    f = Future()
    f.set_result(({1: (mask, confidence)}, 40., 'test'))
    tr.refresh_job = _T1Job(0., {1: tr.tracks[1].kf.pose}, np.zeros_like(mask, dtype=np.int32), future=f, generation=tr._generation)
    tr._refresh_collect(.1)


def test_partial_refresh_does_not_shrink_or_rewrite_remembered_object():
    tr, _, mask = tracker()
    obj = tr.tracks[1]
    original = obj.template.copy()
    pose = obj.kf.pose
    partial = mask.copy(); partial[40:57] = False
    collect_mask(tr, partial)
    assert tr.refresh_stats['rejected'] == 1
    assert obj.kf.pose == pose
    assert np.array_equal(obj.template, original)


def test_normal_tracking_rejects_large_jump_but_searching_can_recover():
    from vision_input.tracking.api import TrackState
    tr, _, mask = tracker()
    moved = np.roll(mask, 24, axis=1)
    pose = tr.tracks[1].kf.pose
    collect_mask(tr, moved)
    assert tr.tracks[1].kf.pose == pose
    assert tr.refresh_stats['rejected'] == 1
    tr.tracks[1].state = TrackState.SEARCHING
    collect_mask(tr, moved)
    assert tr.tracks[1].state == TrackState.TRACKING
    assert tr.tracks[1].kf.pose[0] > pose[0] + 20


def test_resegment_never_mutates_tam_before_result_is_accepted():
    from vision_input.tracking.refresh import resegment
    tr, image, mask = tracker()
    class NoMemoryWrites:
        def add(self, *args):
            pytest.fail('unvalidated memory write')
        def set_time(self, *args):
            pytest.fail('unvalidated memory write')
    result, _, _ = resegment(ExactSegmenter(mask), image, _lab_index(image), {1: anchor(tr, mask)}, NoMemoryWrites())
    assert result[1] is not None


def test_rejected_kalman_measurement_does_not_replace_mask_or_report_applied(monkeypatch):
    tr, _, mask = tracker()
    obj = tr.tracks[1]
    previous = obj.mask.copy()
    monkeypatch.setattr(obj.kf, 'update', lambda *_: False)
    collect_mask(tr, np.roll(mask, 2, axis=1))
    assert tr.refresh_stats['applied'] == 0 and tr.refresh_stats['rejected'] == 1
    assert np.array_equal(obj.mask, previous)
