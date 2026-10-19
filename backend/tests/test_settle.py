"""가만히 놓인 물체: 기준점을 바닥으로 다시 찍기, 놓쳤다 다시 잡은 뒤·오래 정지 시 자동 분할 재지정, 분할 후보 2개 제한."""

import time

import numpy as np
from fastapi.testclient import TestClient

from vision_input.config import Settings
from vision_input.pipeline import VisionProcessor
from vision_input.server.app import SyntheticSpec, create_app
from vision_input.tracking.anchor import ObjectAnchor
from vision_input.tracking.api import Pose, TrackOutput, TrackState
from vision_input.tracking.register import register
from vision_input.tracking.segment import SegResult
from vision_input.tracking.settle import SettleConfig, SettleWatch


def out(cx=100.0, cy=100.0, scale=1.0, state=TrackState.TRACKING, hand=0.0):
    if not state.visible:
        return TrackOutput(state)
    return TrackOutput(state, (cx - 40, cy - 25, cx + 40, cy + 25), Pose(cx, cy, scale), None, 1.0, {"hand_frac": hand})


def run(w, frames, t0=0.0, **kw):
    t = t0
    for _ in range(frames):
        w.update(out(**kw), t)
        t += 1 / 30
    return t


def test_anchor_rebase_is_due_once_per_still_period():
    w = SettleWatch()
    t = run(w, 20)                                  # 0.67초: 아직
    assert not w.anchor_due(t)
    t = run(w, 15, t)                               # 1초 넘음
    assert w.anchor_due(t) and not w.anchor_due(t)  # 정지 구간마다 한 번
    t = run(w, 5, t, cx=140.0)                      # 움직였다가
    t = run(w, 40, t, cx=140.0)                     # 다시 가만히
    assert w.anchor_due(t)


def test_small_jitter_is_still_but_grasp_or_hand_is_not():
    w = SettleWatch()
    t = 0.0
    for i in range(40):
        w.update(out(cx=100.0 + (i % 2) * 1.5), t)  # 물체 크기(약 63px)의 2.4% 떨림
        t += 1 / 30
    assert w.still_for(t) > 1.0
    w.update(out(state=TrackState.GRASPED), t)
    assert w.still_for(t) == 0.0
    run(w, 40, t, hand=0.3)
    assert w.still_for(t + 1.3) == 0.0


def test_reseg_after_recovery_then_after_long_stillness():
    cfg = SettleConfig(reseg_long_s=5.0, cooldown_s=1.0)
    w = SettleWatch(cfg)
    t = run(w, 60)
    assert w.reseg_due(t) is None                    # 놓친 적 없고 오래 정지도 아님
    t = run(w, 15, t, state=TrackState.LOST)         # 0.5초 놓침
    t = run(w, 20, t)                                # 다시 잡고 0.67초
    assert w.reseg_due(t) is None
    t = run(w, 15, t)
    assert w.reseg_due(t) == "recovered" and w.pending
    assert w.reseg_due(t) is None                    # 끝날 때까지 다시 내지 않는다
    w.reseg_done(t, True)
    assert not w.recovered
    t = run(w, 160, t)                               # 계속 정지: 5초 → 오래 정지
    assert w.reseg_due(t) == "long_still"
    w.reseg_done(t, True)
    t = run(w, 60, t)
    assert w.reseg_due(t) is None                    # 다음은 다시 5초 뒤


def test_brief_dropout_is_not_a_recovery():
    w = SettleWatch()
    t = run(w, 30)
    t = run(w, 3, t, state=TrackState.OCCLUDED)      # 0.1초
    t = run(w, 60, t)
    assert w.reseg_due(t) is None


def test_anchor_rebase_moves_the_point_back_to_the_bottom():
    gray = np.random.default_rng(0).integers(0, 255, (240, 320)).astype(np.uint8)
    mask = np.zeros((240, 320), bool)
    mask[100:160, 100:200] = True
    a = ObjectAnchor()
    a.update(gray, mask, True, True, (320, 240))
    gen = a.generation
    assert a.rebase(mask) is False                   # 이미 바닥에 있으면 그대로
    a.p = np.array([110.0, 105.0])                   # 흔들다 위쪽 모서리로 밀려났다
    assert a.rebase(mask) is True
    st = a.update(gray, mask, True, True, (320, 240))
    assert a.generation == gen + 1                   # 세대가 이어져 커서 기준을 새로 시작한다
    assert abs(st.xy[0] - 150) < 4 and st.xy[1] > 150


class ThreeSeg:
    name = "three"

    def segment(self, frame, box=None, points=None):
        h, w = frame.shape[:2]
        ms = []
        for k in (0.1, 0.2, 0.3):
            m = np.zeros((h, w), bool)
            x0, y0, x1, y1 = (int(v) for v in box)
            dx, dy = int(k * (x1 - x0)), int(k * (y1 - y0))
            m[y0 + dy:y1 - dy, x0 + dx:x1 - dx] = True
            ms.append(m)
        return SegResult(ms, [0.9, 0.8, 0.7])


def test_only_two_candidates_and_the_index_wraps_between_them():
    frame = np.full((240, 320, 3), 128, np.uint8)
    reg = register(frame, ThreeSeg(), box=(80, 60, 240, 180))
    assert len(reg.candidates) == 2
    assert register(frame, ThreeSeg(), box=(80, 60, 240, 180), candidate=2).candidate_index == 0
    assert register(frame, ThreeSeg(), box=(80, 60, 240, 180), candidate=1).candidate_index == 1


def test_server_auto_reseg_reselects_in_the_current_frame_and_keeps_the_id():
    class RectSeg:
        name = "rect"

        def segment(self, frame, box=None, points=None):
            h, w = frame.shape[:2]
            m = np.zeros((h, w), bool)
            bw, bh = box[2] - box[0], box[3] - box[1]
            m[int(box[1] + 0.1 * bh):int(box[3] - 0.1 * bh), int(box[0] + 0.1 * bw):int(box[2] - 0.1 * bw)] = True
            return SegResult([m, m.copy()], [0.9, 0.7])

    proc = VisionProcessor(None)
    app = create_app(Settings(), SyntheticSpec(width=320, height=240, fps=60), serve_frontend=False,
                     segmenter=RectSeg(), processor=proc)
    with TestClient(app) as client:
        deadline = time.monotonic() + 3
        while True:
            r = client.post("/api/objects", json={"box": [0.3, 0.3, 0.7, 0.7]})
            if r.status_code != 409 or time.monotonic() > deadline:
                break
            time.sleep(0.05)
        oid = r.json()["id"]
        proc.auto_reseg = False                                 # 백그라운드 루프는 쉬게 하고 직접 한 번씩 부른다
        calls = []
        proc.auto_reseg_jobs = lambda: [] if calls else calls.append(1) or [(oid, {"box": [0.28, 0.28, 0.72, 0.72]}, 0, "recovered", 1.0)]
        proc.auto_reseg_still = lambda o, since: True
        done = []
        proc.auto_reseg_done = lambda o, ok: done.append((o, ok))
        router = app.state.objects_router
        assert client.portal.call(router.auto_reseg_once) == 1
        assert done == [(oid, True)]
        objs = client.get("/api/objects").json()
        assert [o["id"] for o in objs] == [oid]                # 같은 id (다시 선택과 같은 경로)
        # 다른 곳을 잡은 결과는 버린다
        calls.clear()
        proc.auto_reseg_jobs = lambda: [] if calls else calls.append(1) or [(oid, {"box": [0.0, 0.0, 0.2, 0.2]}, 0, "long_still", 1.0)]
        assert client.portal.call(router.auto_reseg_once) == 0
        assert done[-1] == (oid, False)


def test_dev_auto_reseg_settings_default_15s_and_apply_to_existing_watches():
    proc = VisionProcessor(None)
    assert SettleConfig().reseg_long_s == 15.0
    proc._settle[1] = SettleWatch()
    app = create_app(Settings(), SyntheticSpec(width=320, height=240, fps=60), serve_frontend=False, processor=proc)
    with TestClient(app) as client:
        assert client.get("/api/dev/auto-reseg").json() == {"enabled": True, "long_s": 15.0}
        assert client.put("/api/dev/auto-reseg", json={"enabled": False, "long_s": 40}).json() == {"enabled": False, "long_s": 40.0}
        assert proc.auto_reseg is False and proc._settle[1].cfg.reseg_long_s == 40.0
        assert client.put("/api/dev/auto-reseg", json={"long_s": 1}).status_code == 422
        assert proc.auto_reseg_jobs() == []                 # 꺼져 있으면 아무것도 하지 않는다
