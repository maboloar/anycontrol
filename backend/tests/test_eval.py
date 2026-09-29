"""평가 하네스: 합성 정답의 정합성과 지표 계산."""

import numpy as np
import pytest

from vision_input.eval.harness import run_synth
from vision_input.eval.metrics import SequenceScore
from vision_input.eval.synth import CONDITIONS, OBJECT_KINDS, SynthSequence, SynthSpec, build_suite
from vision_input.eval.trackers import CSRTTracker, StaticTracker
from vision_input.tracking import Pose, TrackOutput, TrackState, box_iou


def _spec(obj="textured", cond=("grasp",), seed=1, frames=40):
    return SynthSpec(f"t/{obj}-{'-'.join(cond)}", obj, cond, seed, frames, 30.0, (320, 180))


def test_suite_covers_matrix_and_splits_do_not_share_seeds():
    tune, ev = build_suite("tune"), build_suite("eval")
    assert len(tune) == len(OBJECT_KINDS) * len(CONDITIONS)
    assert {s.seed for s in tune}.isdisjoint({s.seed for s in ev})


def test_same_seed_is_deterministic():
    a, b = SynthSequence(_spec()), SynthSequence(_spec())
    fa, ga = a.render(17)
    fb, gb = b.render(17)
    assert np.array_equal(fa, fb) and ga.target == gb.target


@pytest.mark.parametrize("obj", OBJECT_KINDS)
def test_visible_mask_matches_rendered_object(obj):
    """정답 visible 박스 영역은 배경과 실제로 달라야 한다 (정답이 영상과 어긋나지 않음)."""
    seq = SynthSequence(_spec(obj, ("pull",)))
    img, gt = seq.render(0)
    assert gt.target["visible_frac"] > 0.9 and gt.hand_frac == 0.0
    diff = np.abs(img.astype(int) - (seq.bg * 255).astype(int)).sum(2)
    inside = diff[gt.visible_mask].mean()
    assert inside > 8, f"{obj}: object barely differs from background ({inside:.1f})"


def test_grasp_occludes_and_full_occlusion_hides():
    g = SynthSequence(_spec("dark", ("grasp",), frames=60))
    fracs = [g.render(i)[1].hand_frac for i in range(0, 60, 5)]
    assert max(fracs) > 0.3 and fracs[0] == 0.0
    f = SynthSequence(_spec("dark", ("full_occlusion",), frames=60))
    vis = [f.render(i)[1].target["visible_frac"] for i in range(60)]
    assert min(vis) < 0.05 and vis[0] > 0.9


def test_exit_leaves_frame_and_returns():
    s = SynthSequence(_spec("textured", ("exit",), frames=90))
    inview = [s.render(i)[1].target["in_view"] for i in range(90)]
    assert inview[0] and inview[-1] and not all(inview)


def test_pull_changes_scale_a_lot():
    s = SynthSequence(_spec("dark", ("pull",), frames=90))
    scales = [s.render(i)[1].target["scale"] for i in range(90)]
    assert max(scales) > 2.0 and scales[0] == pytest.approx(1.0)


def test_twin_distractor_present():
    s = SynthSequence(_spec("textured", ("twin",)))
    assert s.render(5)[1].distractors


# ---------------------------------------------------------------- metrics
def _gt(cx, vis=1.0, box=None):
    box = box or (cx - 10, 40, cx + 10, 60)
    return {"cx": cx, "cy": 50, "scale": 1.0, "visible_frac": vis, "visible_box": box if vis > 0 else None,
            "amodal_box": box, "in_view": True}


def test_perfect_tracker_scores_one():
    sc = SequenceScore("x")
    for i in range(20):
        g = _gt(100 + i)
        out = TrackOutput(TrackState.TRACKING, g["visible_box"], Pose(g["cx"], 50, 1.0))
        sc.add(g, [], 0.0, out, 1.0, 20)
    s = sc.summary()
    assert s["success"] == 1.0 and s["robust"] == 1.0 and s["center_err"] == 0.0 and s["scale_err"] == 0.0


def test_false_positive_during_occlusion_and_recovery():
    sc = SequenceScore("x")
    for i in range(30):
        vis = 0.0 if 10 <= i < 20 else 1.0
        g = _gt(100, vis)
        if i < 10:
            out = TrackOutput(TrackState.TRACKING, g["amodal_box"], Pose(100, 50))
        elif i < 20:  # 가림 중 엉뚱한 곳을 "보인다" 고 함
            out = TrackOutput(TrackState.TRACKING, (300, 300, 320, 320), Pose(310, 310))
        elif i < 23:  # 복구에 3프레임
            out = TrackOutput(TrackState.SEARCHING)
        else:
            out = TrackOutput(TrackState.TRACKING, g["amodal_box"], Pose(100, 50))
        sc.add(g, [], 0.0, out, 1.0, 20)
    s = sc.summary()
    assert s["fp_rate"] == 1.0
    assert s["recovery_frames"] == 3.0
    assert s["success"] == pytest.approx(17 / 20)


def test_hijack_detected():
    sc = SequenceScore("x")
    g = _gt(100)
    d = [{"box": (200, 40, 220, 60)}]
    sc.add(g, d, 0.0, TrackOutput(TrackState.TRACKING, (200, 40, 220, 60), Pose(210, 50)), 1.0, 20)
    assert sc.summary()["hijacks"] == 1


def test_box_iou():
    assert box_iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert box_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert box_iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)


# ---------------------------------------------------------------- 하네스 end-to-end
def test_static_baseline_fails_on_motion_but_csrt_tracks_simple_case():
    spec = _spec("textured", ("rotate",), seed=3, frames=45)
    static = run_synth(StaticTracker, spec)
    csrt = run_synth(CSRTTracker, spec)
    assert csrt["success"] is not None and static["success"] is not None
    assert csrt["success"] >= static["success"]
    assert csrt["ms_p95"] >= 0


def test_realtime_pace_skips_frames_for_slow_tracker():
    class Slow(StaticTracker):
        def step(self, frame, t):
            import time
            time.sleep(0.07)  # 2프레임 넘게 걸림
            return super().step(frame, t)

    spec = _spec("textured", ("pull",), frames=30)
    r = run_synth(Slow, spec, pace="realtime")
    assert r["frames"] == 29  # 모든 프레임은 채점하되, 건너뛴 프레임은 ms=0
