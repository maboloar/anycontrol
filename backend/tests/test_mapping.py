"""매핑 엔진·스키마·저장소·학습·싱크 계약·API."""

import json
import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from vision_input.io.sink import VirtualSink
from vision_input.mapping.engine import InputSnapshot, MappingEngine, ObjectSnap, shape
from vision_input.mapping.learn import AxisLearner
from vision_input.mapping.schema import Mapping, Profile, Transform, warnings
from vision_input.mapping.store import ProfileStore, slug


def M(mid, inp, out, **tr):  # noqa: N802
    return Mapping.model_validate({"id": mid, "input": inp, "output": out, "transform": tr})


def obj(name="펜", visible=True, contact=None, oid=1, **axes):
    base = dict.fromkeys(("x", "y", "depth", "angle", "stretch", "contact"), 0.0)
    base.update(axes)
    return ObjectSnap(oid, name, visible, base, contact)


# ---------------------------------------------------------------- 변환
@settings(max_examples=200, deadline=None)
@given(v=st.floats(-100, 100), lo=st.floats(-50, 0), span=st.floats(0.01, 100), dz=st.floats(0, 0.9),
       inv=st.booleans(), expo=st.floats(0, 1), kind=st.sampled_from(["bipolar", "unipolar"]))
def test_shape_stays_in_range(v, lo, span, dz, inv, expo, kind):
    tr = Transform(range=[lo, lo + span], deadzone=dz, invert=inv, curve="expo", expo=expo)
    y = shape(v, tr, kind)
    assert (-1.0 if kind == "bipolar" else 0.0) - 1e-9 <= y <= 1.0 + 1e-9


@settings(max_examples=100, deadline=None)
@given(a=st.floats(-2, 2), b=st.floats(-2, 2), dz=st.floats(0, 0.5), expo=st.floats(0, 1))
def test_shape_is_monotonic(a, b, dz, expo):
    tr = Transform(range=[-1, 1], deadzone=dz, curve="expo", expo=expo)
    lo, hi = sorted((a, b))
    assert shape(lo, tr, "bipolar") <= shape(hi, tr, "bipolar") + 1e-12


def test_shape_deadzone_is_continuous_and_centered():
    tr = Transform(range=[-45, 45], deadzone=0.1)
    assert shape(0, tr, "bipolar") == 0
    assert shape(4.4, tr, "bipolar") == 0          # 45·0.1 안쪽
    assert 0 < shape(5.0, tr, "bipolar") < 0.02    # 문턱 바로 밖에서 작게 시작 (튀지 않음)
    assert shape(45, tr, "bipolar") == pytest.approx(1)
    assert shape(-90, tr, "bipolar") == pytest.approx(-1)
    assert shape(0.1, Transform(range=[0, 0.2], deadzone=0), "unipolar") == pytest.approx(0.5)


# ---------------------------------------------------------------- 엔진
def test_axis_maps_to_stick_and_trigger_and_clips():
    p = Profile(mappings=[
        M("steer", {"source": "object", "object": "펜", "axis": "angle"}, {"target": "gamepad_axis", "axis": "left_x"},
          range=[-30, 30], deadzone=0),
        M("gas", {"source": "object", "object": "컵", "axis": "depth"}, {"target": "gamepad_axis", "axis": "rt"},
          range=[0, 0.5], deadzone=0),
    ])
    e = MappingEngine(p)
    s = e.update(InputSnapshot(0.0, [obj(angle=15), obj("컵", oid=2, depth=0.25)]))
    assert s.axes["left_x"] == pytest.approx(0.5)
    assert s.axes["rt"] == pytest.approx(0.5)
    s = e.update(InputSnapshot(0.1, [obj(angle=90), obj("컵", oid=2, depth=-1)]))
    assert s.axes["left_x"] == 1.0 and s.axes["rt"] == 0.0


def test_object_reference_by_id():
    p = Profile(mappings=[M("a", {"source": "object", "object": "#7", "axis": "x"},
                            {"target": "gamepad_axis", "axis": "right_x"}, deadzone=0, range=[-0.1, 0.1])])
    s = MappingEngine(p).update(InputSnapshot(0.0, [obj("아무 이름", oid=7, x=0.05)]))
    assert s.axes["right_x"] == pytest.approx(0.5)


def test_lost_policies():
    def run(policy):
        p = Profile(mappings=[M("a", {"source": "object", "object": "펜", "axis": "x"},
                                {"target": "gamepad_axis", "axis": "left_x"},
                                range=[-0.1, 0.1], deadzone=0, on_lost=policy, lost_ms=200)])
        e = MappingEngine(p)
        e.update(InputSnapshot(0.0, [obj(x=0.1)]))
        return [e.update(InputSnapshot(t, [obj(visible=False, x=0.1)])).axes["left_x"] for t in (0.05, 0.15, 0.3)]

    hold, center, release = run("hold"), run("center"), run("release")
    assert hold == [1.0, 1.0, 1.0]
    assert center[0] == pytest.approx(1.0) and center[1] == pytest.approx(0.5) and center[2] == 0.0
    assert center[0] > center[1] > center[2]  # 단조 감소
    assert release == [0.0, 0.0, 0.0]


def test_button_hysteresis_and_release_on_lost():
    p = Profile(mappings=[M("jump", {"source": "object", "object": "펜", "axis": "y"},
                            {"target": "gamepad_button", "button": "a"}, range=[0, 0.1], deadzone=0, on=0.6, off=0.4,
                            on_lost="hold")])
    e = MappingEngine(p)
    seq = [0.0, 0.065, 0.05, 0.045, 0.035, 0.07]
    got = [e.update(InputSnapshot(i * 0.03, [obj(y=v)])).buttons["a"] for i, v in enumerate(seq)]
    assert got == [False, True, True, True, False, True]
    assert not e.update(InputSnapshot(1.0, [obj(visible=False)])).buttons["a"]  # 버튼은 hold 여도 놓는다


def test_same_output_sums_axes_and_ors_buttons():
    p = Profile(mappings=[
        M("a", {"source": "object", "object": "펜", "axis": "x"}, {"target": "gamepad_axis", "axis": "left_x"},
          range=[-1, 1], deadzone=0),
        M("b", {"source": "object", "object": "펜", "axis": "y"}, {"target": "gamepad_axis", "axis": "left_x"},
          range=[-1, 1], deadzone=0),
        M("k1", {"source": "visible", "object": "펜"}, {"target": "key", "key": "w"}, range=[0, 1], deadzone=0),
        M("k2", {"source": "visible", "object": "컵"}, {"target": "key", "key": "w"}, range=[0, 1], deadzone=0),
    ])
    s = MappingEngine(p).update(InputSnapshot(0.0, [obj(x=0.7, y=0.6)]))
    assert s.axes["left_x"] == 1.0  # 0.7 + 0.6 → 잘림
    assert s.keys == {"w"}
    assert any("값을 더합니다" in w for w in warnings(p))


def test_velocity_mode_and_smoothing():
    p = Profile(mappings=[M("spin", {"source": "object", "object": "펜", "axis": "angle"},
                            {"target": "mouse", "action": "scroll"}, mode="velocity", range=[-90, 90], deadzone=0)])
    e = MappingEngine(p)
    vals = [e.update(InputSnapshot(i / 30, [obj(angle=3.0 * i)])).mouse_scroll for i in range(30)]
    assert vals[0] == 0.0
    assert vals[-1] == pytest.approx(1.0, abs=0.05)  # 초당 90° 회전 → 끝까지
    p2 = Profile(mappings=[M("s", {"source": "object", "object": "펜", "axis": "x"},
                             {"target": "gamepad_axis", "axis": "left_x"}, range=[-1, 1], deadzone=0, smoothing_ms=100)])
    e2 = MappingEngine(p2)
    e2.update(InputSnapshot(0.0, [obj(x=0.0)]))
    v = e2.update(InputSnapshot(0.1, [obj(x=1.0)])).axes["left_x"]
    assert 0.55 < v < 0.7  # 1 - e^-1


def test_hand_and_pen_inputs():
    p = Profile(mappings=[
        M("fire", {"source": "hand", "gesture": "pinch"}, {"target": "mouse", "action": "left"}, range=[0, 1], deadzone=0),
        M("ink", {"source": "pen", "object": "펜"}, {"target": "key", "key": "space"}, range=[0, 1], deadzone=0),
    ])
    e = MappingEngine(p)
    assert e.needs_hands
    s = e.update(InputSnapshot(0.0, [obj(contact=True)], {"pinch": True, "pinch_middle": False}))
    assert s.mouse_buttons["left"] and s.keys == {"space"}
    s = e.update(InputSnapshot(0.1, [obj(contact=False)], None))
    assert not s.mouse_buttons["left"] and not s.keys


# ---------------------------------------------------------------- 스키마
def test_schema_validation():
    with pytest.raises(ValidationError):
        Profile.model_validate({"mappings": [{"id": "a", "input": {"source": "object", "object": "x", "axis": "bogus"},
                                              "output": {"target": "key", "key": "w"}}]})
    with pytest.raises(ValidationError):
        M("a", {"source": "hand"}, {"target": "key", "key": "rm -rf"})
    with pytest.raises(ValidationError):
        Transform(range=[1, 0])
    with pytest.raises(ValidationError):
        Transform(on=0.3, off=0.5)
    m = M("a", {"source": "hand"}, {"target": "key", "key": "ArrowLeft"})
    assert m.output.key == "arrowleft"
    with pytest.raises(ValidationError):
        Profile(mappings=[m, m])  # id 중복
    schema = Profile.model_json_schema()
    assert "mappings" in schema["properties"] and "$defs" in schema
    p = Profile(name="레이싱", mappings=[m])
    assert Profile.model_validate_json(p.model_dump_json()) == p


def test_warnings_for_missing_object_and_centered_button_range():
    p = Profile(mappings=[M("j", {"source": "object", "object": "없는물체", "axis": "y"},
                            {"target": "gamepad_button", "button": "a"})])
    ws = warnings(p, ["펜"])
    assert any("없는물체" in w for w in ws) and any("중립" in w for w in ws)


# ---------------------------------------------------------------- 저장소
def test_store_roundtrip_and_path_safety(tmp_path):
    s = ProfileStore(tmp_path / "profiles")
    assert s.list() == []
    p = Profile(name="레이싱 1", mappings=[M("a", {"source": "hand"}, {"target": "key", "key": "w"})])
    s.save(p)
    assert [x["name"] for x in s.list()] == ["레이싱 1"]
    assert s.load("레이싱 1") == p
    assert slug("../../etc/passwd") == "etcpasswd"
    with pytest.raises(ValueError):
        slug("../..")
    s.save(Profile(name="../evil"))
    assert all(f.parent == tmp_path / "profiles" for f in (tmp_path / "profiles").iterdir())
    (tmp_path / "profiles" / "broken.json").write_text("{not json")
    assert len(s.list()) == 2  # 깨진 파일은 건너뜀
    s.delete("레이싱 1")
    with pytest.raises(KeyError):
        s.load("레이싱 1")


# ---------------------------------------------------------------- 학습
def test_learner_picks_moved_axis_with_range():
    lr = AxisLearner(1)
    for i in range(60):
        lr.add({"x": 0.002 * (i % 3), "y": 0.0, "depth": 0.01, "angle": 30.0 * (i / 59), "stretch": 0.0, "contact": None})
    sug = lr.suggest()
    assert sug[0].axis == "angle"
    assert sug[0].range[1] == pytest.approx(28.5, abs=1.0)
    assert sug[0].range_positive[0] == 0.0 and not sug[0].invert_for_positive
    lr2 = AxisLearner(1)
    for i in range(30):
        lr2.add({"y": -0.1 * i / 29})
    s2 = lr2.suggest()[0]
    assert s2.axis == "y" and s2.invert_for_positive and s2.range_positive[1] == 0.0


# ---------------------------------------------------------------- 싱크 계약
def test_sink_release_all_contract():
    s = VirtualSink()
    s.button("left", True)
    s.set_keys({"w", "space"})
    s.gamepad({"left_x": 0.7, "rt": 2.0}, {"a": True})
    assert s.pad_axes["rt"] == 1.0  # 잘림
    s.release_all()
    assert not any(s.buttons.values()) and not s.keys
    assert all(v == 0 for v in s.pad_axes.values()) and not any(s.pad_buttons.values())
    ev = s.controller_snapshot()["key_events"]
    assert {e["key"] for e in ev if e["type"] == "up"} == {"w", "space"}
    s.set_keys(set())
    assert s.controller_snapshot()["key_events"] == []  # 같은 상태는 이벤트 없음


# ---------------------------------------------------------------- API
@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from vision_input.config import Settings
    from vision_input.pipeline import VisionProcessor
    from vision_input.server.app import SyntheticSpec, create_app

    from .test_mouse import FakeHands
    from .test_server import RectSeg

    proc = VisionProcessor(None, hand_worker=FakeHands())
    app = create_app(Settings(), SyntheticSpec(width=320, height=240, fps=60), serve_frontend=False,
                     segmenter=RectSeg(), processor=proc, profile_store=ProfileStore(tmp_path / "p"))
    with TestClient(app) as c:
        yield c, proc


def _add_object(c):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        r = c.post("/api/objects", json={"box": [0.3, 0.3, 0.6, 0.6]})
        if r.status_code != 409:
            return r
        time.sleep(0.05)
    return r


def test_mapping_api_mode_and_state(client):
    c, proc = client
    info = c.get("/api/mapping").json()
    assert info["mode"] == "observe" and info["profile"]["mappings"] == []
    assert "properties" in c.get("/api/mapping/schema").json()
    o = _add_object(c).json()
    prof = {"name": "테스트", "mappings": [
        {"id": "v", "input": {"source": "visible", "object": o["name"]}, "output": {"target": "gamepad_button", "button": "a"},
         "transform": {"range": [0, 1], "deadzone": 0}}]}
    r = c.put("/api/mapping", json=prof)
    assert r.status_code == 200 and r.json()["warnings"] == []
    assert c.put("/api/mapping", json={"mappings": [{"id": "x"}]}).status_code == 422

    def controller():
        with c.websocket_connect("/ws") as ws:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                m = ws.receive()
                if m.get("text"):
                    d = json.loads(m["text"])
                    if d["type"] == "state" and "mapping" in d["data"]:
                        return d["data"]
        pytest.fail("no state")

    d = controller()
    assert d["controller"]["mode"] == "observe" and d["controller"]["buttons"]["a"] is False  # 보기만
    assert d["mapping"]["computed"]["buttons"]["a"] is True
    assert c.put("/api/mapping/mode", json={"mode": "send"}).json()["mode"] == "send"
    d = controller()
    assert d["controller"]["buttons"]["a"] is True
    c.post("/api/stop")
    assert c.get("/api/mapping").json()["mode"] == "observe"  # 긴급 정지는 출력도 끈다
    assert not proc.sink.pad_buttons["a"]


def test_learn_and_profiles_api(client):
    c, _ = client
    assert c.post("/api/mapping/learn/stop").status_code == 409
    assert c.post("/api/mapping/learn/start", json={"object_id": 99}).status_code == 404
    o = _add_object(c).json()
    assert c.post("/api/mapping/learn/start", json={"object_id": o["id"]}).status_code == 204
    time.sleep(0.3)
    r = c.post("/api/mapping/learn/stop").json()
    assert r["object_id"] == o["id"] and r["frames"] > 0
    assert c.get("/api/profiles").json() == []
    p = {"mappings": [{"id": "a", "input": {"source": "hand"}, "output": {"target": "key", "key": "w"}}]}
    assert c.put("/api/profiles/레이싱", json=p).json()["name"] == "레이싱"
    assert [x["name"] for x in c.get("/api/profiles").json()] == ["레이싱"]
    assert c.get("/api/profiles/레이싱").json()["mappings"][0]["id"] == "a"
    assert c.get("/api/profiles/없음").status_code == 404
    assert c.delete("/api/profiles/레이싱").status_code == 204
    assert c.delete("/api/profiles/레이싱").status_code == 404


def test_concurrent_profile_saves_use_independent_atomic_files(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from vision_input.mapping.store import ProfileStore
    from vision_input.mapping.schema import Profile
    store = ProfileStore(tmp_path)
    gate = Barrier(8)
    def save(i):
        gate.wait()
        store.save(Profile(name='shared', description=str(i)))
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(save, range(8)))
    assert store.load('shared').description in {str(i) for i in range(8)}
    assert len(list(tmp_path.iterdir())) == 1


def test_transform_range_rejects_non_finite_bounds():
    import pytest
    from vision_input.mapping.schema import Transform
    for bounds in [[-float('inf'), 1], [-1, float('inf')], [float('nan'), 1]]:
        with pytest.raises(ValueError):
            Transform(range=bounds)


@pytest.mark.parametrize("source", ["object", "visible", "touch", "pen"])
def test_rename_preserves_bound_mapping_and_runtime_state(client, source):
    c, proc = client
    o = _add_object(c).json()
    inp = {"source": source, "object": o["name"]}
    if source == "object":
        inp["axis"] = "x"
    p = {"name": "rename", "mappings": [{"id": "keep", "input": inp,
         "output": {"target": "key", "key": "space"}}]}
    applied = c.put("/api/mapping", json=p).json()["profile"]
    assert applied["mappings"][0]["input"]["object"] == f'#{o["id"]}'
    # Also migrate an already-active legacy profile without resetting its runtime.
    proc.mapping.profile = Profile.model_validate(p)
    runs = proc.mapping.runs
    assert c.patch(f'/api/objects/{o["id"]}', json={"name": "new name"}).status_code == 200
    assert proc.mapping.runs is runs
    current = c.get("/api/mapping").json()["profile"]
    assert current == applied
    saved = c.put("/api/profiles/rename", json=current).json()
    assert saved["mappings"][0]["input"]["object"] == "new name"
    reapplied = c.put("/api/mapping", json=saved).json()["profile"]
    assert reapplied["mappings"][0]["input"]["object"] == f'#{o["id"]}'


def test_reset_settings_clears_current_experience_preserves_source_and_profiles(client):
    c, proc = client
    o = _add_object(c).json()
    source = c.get("/api/source").json()
    profile = {"name": "keep", "mappings": [{"id": "a", "input": {"source": "visible", "object": o["name"]}, "output": {"target": "key", "key": "space"}}]}
    assert c.put("/api/profiles/keep", json=profile).status_code == 200
    c.put("/api/mapping", json=profile)
    c.put("/api/tracking", json={"input_mirror": False, "ema": False, "hand_input_enabled": False})
    c.put("/api/touch/settings", json={"object_sensitivity": .9})
    result = c.post("/api/settings/reset")
    assert result.status_code == 200, result.text
    assert proc.objects == {} and proc.output_mode == "observe"
    assert proc.mapping.profile.mappings == []
    assert proc.input_mirror and proc.ema and proc.hand_input_enabled
    assert proc.object_touch.sensitivity == .7
    assert result.json()["mouse"]["settings"]["hand_control"] == "air"
    assert result.json()["mouse"]["settings"]["hand_click_style"] == "pinch"
    assert c.get("/api/source").json()["spec"] == source["spec"]
    assert c.get("/api/profiles/keep").status_code == 200


def test_disabling_hand_input_releases_buttons_and_gesture_state(client):
    c, proc = client
    proc.sink.button("left", True)
    result = c.put("/api/tracking", json={"hand_input_enabled": False})
    assert result.status_code == 200
    assert result.json()["hand_input_enabled"] is False
    assert not proc.map_gestures.left.down


def test_hand_xy_are_continuous_values_and_release_when_hand_is_lost():
    p = Profile(mappings=[M("hx", {"source": "hand", "gesture": "x"}, {"target": "control", "name": "fruit.x1", "kind": "bipolar"}, range=[-.3, .3], deadzone=0, on_lost="release")])
    e = MappingEngine(p)
    assert e.update(InputSnapshot(0, hand={"x": .15})).axes['left_x'] == pytest.approx(.5)
    assert e.update(InputSnapshot(.03, hand={"x": -.15})).axes['left_x'] == pytest.approx(-.5)
    assert e.update(InputSnapshot(.06, hand=None)).axes['left_x'] == 0


def test_hand_jack_switch_keeps_mouse_drawing_and_touch_services_independent(client):
    from vision_input.hands.detector import HandFrame
    from vision_input.io.mouse import MouseSettings
    c, proc = client
    proc.mouse.configure(MouseSettings(mode="hand"))
    proc.hand_drawing.set_enabled(True)
    touch = proc.object_touch
    c.put('/api/tracking', json={'hand_input_enabled': False})
    assert proc.mouse.settings.mode == 'hand' and proc.hand_drawing.enabled
    assert proc.object_touch is touch
    o = _add_object(c).json()
    c.put('/api/mapping', json={'name': 'touch', 'mappings': [{'id': 't', 'input': {'source': 'touch', 'object': '#' + str(o['id'])}, 'output': {'target': 'key', 'key': 'space'}}]})
    hf = HandFrame(1, [])
    seen = []
    touch.update = lambda frame, hands, t, objs: (seen.append(hands) or {})
    proc._update_touch(hf, 1.05)
    assert seen == [hf]


def test_hand_worker_still_runs_for_mouse_or_touch_with_hand_jack_disabled():
    import numpy as np
    from vision_input.pipeline import VisionProcessor
    from vision_input.capture import Frame
    from vision_input.hands.detector import HandFrame
    from vision_input.io.mouse import MouseSettings
    class Worker:
        running = False
        def start(self): self.running = True
        def offer(self, image, t): self.t = t
        def latest(self): return HandFrame(self.t, [])
        def stop(self): self.running = False
    p = VisionProcessor(None)
    p.hands = Worker(); p.hand_occlusion = False; p.set_hand_input(False)
    frame = Frame(0, np.zeros((10, 10, 3), np.uint8), 1., 1.)
    p.mouse.configure(MouseSettings(mode='hand'))
    assert p._hands(frame) is not None
    p.mouse.configure(MouseSettings(mode='off'))
    p.mapping.set_profile(Profile(mappings=[M('t', {'source': 'touch', 'object': '#1'}, {'target': 'key', 'key': 'space'})]))
    assert p._hands(frame) is not None
    p.mapping.set_profile(Profile(mappings=[M('h', {'source': 'hand', 'gesture': 'pinch'}, {'target': 'key', 'key': 'space'})]))
    assert p._hands(frame) is None and not p.hands.running


def test_hand_xy_snapshot_uses_video_palm_position_and_input_mirroring():
    import numpy as np
    from vision_input.pipeline import VisionProcessor
    from vision_input.hands.detector import Hand, HandFrame
    p = VisionProcessor(None)
    p.mapping.set_profile(Profile(mappings=[M('x', {'source': 'hand', 'gesture': 'x'}, {'target': 'gamepad_axis', 'axis': 'left_x'})]))
    hand = Hand(np.tile(np.array([.7, .3]), (21, 1)), np.zeros(21), 'Right', .9)
    hf = HandFrame(1., [hand])
    p.input_mirror = False
    assert p._snapshot(1.03, hf).hand['x'] == pytest.approx(.2)
    assert p._snapshot(1.03, hf).hand['y'] == pytest.approx(-.2)
    p.input_mirror = True
    assert p._snapshot(1.03, hf).hand['x'] == pytest.approx(-.2)
    p.set_hand_input(False)
    assert p._snapshot(1.03, hf).hand is None


def test_deleting_an_object_removes_its_connections_and_rejects_a_late_old_save(client):
    c, proc = client
    a = _add_object(c).json(); b = _add_object(c).json()
    profile = {'name': 'delete', 'mappings': [
        {'id': 'a', 'input': {'source': 'touch', 'object': a['name']}, 'output': {'target': 'key', 'key': 'space'}},
        {'id': 'b', 'input': {'source': 'object', 'object': b['name'], 'axis': 'x'}, 'output': {'target': 'control', 'name': 'dj.cross', 'kind': 'bipolar'}},
        {'id': 'h', 'input': {'source': 'hand', 'gesture': 'pinch'}, 'output': {'target': 'key', 'key': 'enter'}}]}
    old = c.put('/api/mapping', json=profile).json()['profile']
    c.put('/api/profiles/keep-delete', json=old)
    assert c.delete('/api/objects/' + str(a['id'])).status_code == 204
    assert [m['id'] for m in c.get('/api/mapping').json()['profile']['mappings']] == ['b', 'h']
    assert [m['id'] for m in c.put('/api/mapping', json=old).json()['profile']['mappings']] == ['b', 'h']
    assert len(c.get('/api/profiles/keep-delete').json()['mappings']) == 3


def test_camera_scene_reset_removes_old_object_cables_but_keeps_hand_mapping(client):
    c, proc = client
    a = _add_object(c).json()
    c.put('/api/mapping', json={'name': 'scene', 'mappings': [
        {'id': 'o', 'input': {'source': 'visible', 'object': a['name']}, 'output': {'target': 'key', 'key': 'space'}},
        {'id': 'h', 'input': {'source': 'hand', 'gesture': 'pinch'}, 'output': {'target': 'key', 'key': 'enter'}}]})
    proc.reset()
    assert [m.id for m in proc.mapping.profile.mappings] == ['h']


@pytest.mark.parametrize("name,axis", [
    ("race.steer1", "left_x"), ("race.steer2", "right_x"), ("race.gas", "rt"), ("race.brake", "lt"),
    ("pong.left", "left_y"), ("pong.right", "right_y"),
    ("fruit.x1", "left_x"), ("fruit.y1", "left_y"), ("fruit.x2", "right_x"), ("fruit.y2", "right_y"),
    ("hockey.x1", "left_x"), ("hockey.y1", "left_y"), ("hockey.x2", "right_x"), ("hockey.y2", "right_y"),
    ("survival.x", "left_x"), ("survival.y", "left_y"),
])
def test_old_game_profiles_drive_standard_virtual_pad(name, axis):
    kind = "unipolar" if axis in ("lt", "rt") else "bipolar"
    p = Profile(mappings=[M("game", {"source": "object", "object": "#1", "axis": "x"},
                           {"target": "control", "name": name, "kind": kind},
                           range=[0, 1] if kind == "unipolar" else [-1, 1], deadzone=0, on_lost="release")])
    e = MappingEngine(p)
    assert e.profile.mappings[0].output.target == "gamepad_axis"
    assert e.update(InputSnapshot(0, [ObjectSnap(1, "A", True, {"x": .5})])).axes[axis] == pytest.approx(.5)
    assert e.update(InputSnapshot(.03, [])).axes[axis] == 0
    assert p.mappings[0].output.target == "control"  # saved template is not mutated


def test_game_profile_migration_keeps_last_axis_owner_and_dj_controls():
    p = Profile(mappings=[
        M("race", {"source": "object", "object": "A", "axis": "x"}, {"target": "control", "name": "race.steer1", "kind": "bipolar"}),
        M("fruit", {"source": "object", "object": "B", "axis": "x"}, {"target": "control", "name": "fruit.x1", "kind": "bipolar"}),
        M("dj", {"source": "object", "object": "A", "axis": "x"}, {"target": "control", "name": "dj.cross", "kind": "bipolar"}),
    ])
    e = MappingEngine(p)
    assert [m.id for m in e.profile.mappings] == ["fruit", "dj"]
    assert e.profile.mappings[-1].output.name == "dj.cross"
