"""안내 보정: 실제 신호로 설정 계산, 부실한 동작 재검사, 원자적 적용/취소와 출력 중지."""
import math
import time
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from vision_input.auto_calibration import AutoCalibration, CalibrationError, delta
from vision_input.capture.slot import Frame
from vision_input.io.mouse import MouseSettings
from vision_input.io.touchpad import RelativeTouchpad, TouchSurface
from vision_input.hands.gestures import GestureRecognizer
from vision_input.pipeline import VisionProcessor
from vision_input.server.app import SyntheticSpec, create_app
from .handkit import make_hand
from .test_server import RectSeg, _wait_frame
from .test_pen import pen_frame, pen_mask, _out


def session(kind='hand', surface=None, overhead=False, **settings):
    if kind == 'hand':
        settings.setdefault('hand_control', 'depth')
        settings.setdefault('hand_click_style', 'pinch')  # finger 방식은 test_finger_calibration 에서 따로 검증
    return AutoCalibration(kind, None if kind == 'hand' else 1, MouseSettings(**settings), surface, overhead, 0.)


def samples(key, duration=3., pen=False, overhead=False, mirror=False, plane=False):
    out = []
    for i, t in enumerate(np.linspace(.01, duration, 60)):
        motion = np.clip((t - .6) / max(duration - 1.2, .5), 0, 1)
        down = i % 20 in range(5, 13)
        a = dict(t=float(t), x=.5, y=.6, log_scale=math.log(15) if pen else 0., frame_h=720,
                 pinch=1., middle=1.2, scroll_pose=False, scroll=3., scroll_x=.5, scroll_y=.6,
                 log_knuckle=0., touch=.2, middle_touch=.2, gap=.6,
                 h_index=.9, h_middle=.9, gap_index=.8, gap_middle=.8, raw_y=350., width=15., length=80., sharp=80.)
        if key in ('right', 'left'):
            a['x'] += .15 * motion * (1 if key == 'right' else -1) * (-1 if mirror else 1)
        if key in ('near', 'far'):
            sign = 1 if key == 'near' else -1
            a['log_scale'] += .18 * motion * sign
            a['y'] += .15 * motion * sign
        if key == 'precision':
            # 처음/끝에 잠깐 멈추고 가운데 구간에서 사각형 이동.
            p = np.clip((t / duration - .2) / .6, 0, 1)
            a['x'] += .04 * math.sin(2 * math.pi * p)
            a['y'] += .04 * (1 - math.cos(2 * math.pi * p))
            a['log_scale'] += .04 * (1 - math.cos(2 * math.pi * p))
        if key == 'lift':
            a['touch'] = -.4
        if key in ('click', 'right_click', 'gesture_click') and (not pen or key != 'click'):
            a['pinch' if key in ('click', 'gesture_click') else 'middle'] = .08 if down else 1.
        if key == 'click':
            a.update(h_middle=.2 if down else .9, gap_middle=.02 if down else .8)
        if key == 'right_click':
            a.update(h_index=.2 if down else .9, gap_index=.02 if down else .8)
        if key == 'scroll':
            a.update(scroll_pose=True, scroll=3. + .5 * motion, scroll_y=.6 + .15 * motion,
                     log_knuckle=-.18 * motion)
        if key == 'tap_touch':
            a['gap'] = .02
        if key == 'tap_click':
            a['gap'] = .02 if down else .6
        if pen:
            if key.startswith('touch_') or key.startswith('lift_'):
                width = 20. if key.endswith('near') else 10. if key.endswith('far') else 15.
                a.update(width=width, log_scale=math.log(width), raw_y=200 + 10 * width)
                if key.startswith('lift_'):
                    a['raw_y'] -= 40
                    if overhead:
                        a.update(width=width * 1.2, length=90., sharp=40.)
            if key == 'click':
                a['raw_y'] = 350. if down else 310.
                if overhead and not down:
                    a.update(width=18., length=90., sharp=40.)
            if overhead:
                # Desk View 접촉/떼기 외형은 위치와 별개로 동일하게 유지한다.
                if key.startswith('touch_'):
                    a.update(width=15., length=80., sharp=80.)
                if key.startswith('lift_'):
                    a.update(width=18., length=90., sharp=40.)
            a['y'] = a['raw_y'] / 720 if key.startswith(('touch_', 'lift_')) or key == 'click' else a['y']
        out.append(a)
    return out


PART_DURATION = {'right': 4.5, 'left': 4.5, 'near': 4.5, 'far': 4.5, 'click': 6., 'right_click': 6.,
                 'touch_near': 2., 'touch_far': 2., 'touch_side': 2., 'lift_near': 2., 'lift_far': 2.}


def step_samples(step, pen=False, overhead=False, mirror=False):
    """안내 한 번에 얻는 관측. 합성 단계는 한 번의 연속 동작을 흉내 낸다."""
    if not step.parts:
        return samples(step.key, step.duration, pen, overhead, mirror)
    if step.split == 'extrema':
        # 중앙 → 한쪽 끝(멈춤) → 중앙 → 반대쪽 끝(멈춤)
        out = []
        for i, t in enumerate(np.linspace(.01, step.duration, 90)):
            u = t / step.duration
            m = np.interp(u, [0, .1, .3, .4, .55, .7, .85, 1], [0, 0, 1, 1, 0, -1, -1, -1])
            a = samples('rest', 1., pen, overhead, mirror)[0]
            a = dict(a, t=float(t))
            if step.key == 'lr':
                a['x'] += .15 * m * (-1 if mirror else 1)
            else:
                a['log_scale'] += .18 * m
                a['y'] += .15 * m
            out.append(a)
        return out
    out, offset = [], 0.
    for part in step.parts:
        d = PART_DURATION[part]
        for a in samples(part, d, pen, overhead, mirror):
            out.append(dict(a, t=a['t'] + offset))
        offset += d
    return out


def populated(s, mirror=False):
    for step in s.steps:
        for part in s.parts_of(step):
            s.data[part] = samples(part, PART_DURATION.get(part, step.duration), s.kind == 'pen', s.overhead, mirror)
    return s


@pytest.mark.parametrize('kind,options', [('hand', {}), ('object', {'hand_clicks': True}), ('object', {'hand_clicks': False})])
def test_guided_sessions_reach_review_using_observed_motion_clicks_and_release(kind, options):
    s = session(kind, **options)
    t = 0.
    for step in s.steps:
        assert s.phase == 'ready' and s.steps[s.index].key == step.key
        s.record(step.key, t)
        for a in step_samples(step):
            a['t'] += t
            s.observe(a, a['t'])
        t += step.duration + 1
    assert s.phase == 'review', s.error
    assert s.state()['completed'] == len(s.steps)
    patch = s.result['mouse']
    assert 1 < patch['depth_sensitivity'] < 2
    assert not patch['invert_y'] and not patch['mirror']
    assert .0005 <= patch['depth_deadzone'] < .01
    if s.needs_hands and s.finger_style:
        assert .3 <= patch['finger_press'] <= .85
        assert 'pinch_on' not in patch and 'scroll_gain' not in patch
        assert [st.key for st in s.steps if st.key in ('scroll', 'gesture_click') or st.key.startswith('tap_')] == []
        if kind == 'object':
            assert .05 <= patch['object_tap_distance'] <= .4
    elif s.needs_hands:
        assert .15 < patch['pinch_on'] < .5
        assert patch['scroll_gain'] == pytest.approx(12)
    # 적용 전까지 원래 설정은 그대로 유지된다.
    assert s.settings.depth_sensitivity == 1.5


@pytest.mark.parametrize('overhead', [False, True])
def test_pen_contact_model_uses_multiple_positions_and_independent_validation(overhead):
    surface = TouchSurface.overhead() if overhead else None
    s = populated(session('pen', surface, overhead))
    result = s.solve()
    assert result['pen']['tip_min_cutoff'] > 0
    if overhead:
        assert s.pen_contact.ready and 0 < result['pen']['desk_contact_margin'] <= .6
    else:
        assert s.pen_surface.fixed and s.pen_surface.K == pytest.approx(10)
        assert result['pen']['touch_on'] < result['pen']['touch_off']
        assert 'horizon' not in result['pen']  # 편향된 접촉 절편으로 그리기 원근을 바꾸지 않는다.


def test_mirrored_camera_and_absolute_mode_are_measured_without_switching_modes():
    s = populated(session(mirror=True), mirror=True)
    assert s.solve()['mouse']['mirror']
    s = populated(session(hand_control='air'))
    p = s.solve()['mouse']
    assert 'hand_region' in p and p['invert_y']
    assert 'depth_sensitivity' not in p
    s = populated(session('pen', pen_relative=False, coordinate_mode='image'))
    assert 'object_region' in s.solve()['mouse']


def test_touchpad_infers_surface_and_calibrates_touch_release_and_scroll():
    s = populated(session(hand_control='touchpad'))
    p = s.solve()['mouse']
    assert s.inferred_surface.mode == 'line'
    assert p['touch_height'] == pytest.approx(-.1)
    assert p['touch_depth_blend'] == 1
    assert p['touch_deadzone'] >= .001
    assert p['scroll_gain'] > 1
    for key in ('left', 'right', 'near', 'far'):
        point = np.array([s.data[key][-1]['x'], s.data[key][-1]['y']])
        assert s.inferred_surface.contains(point, 0.)


def test_desk_view_hand_contact_threshold_matches_runtime_depth_comparison():
    s = populated(session(surface=TouchSurface.overhead(), overhead=True, hand_control='touchpad'))
    for a in s.data['touch']:
        a['touch'] = .25  # raised = 0
    for a in s.data['lift']:
        a['touch'] = -.35  # raised = .6
    p = s.solve()['mouse']
    assert p['touch_height'] == pytest.approx(.05)
    hand = make_hand(.5, .6, .15)
    scale = np.linalg.norm(hand.points[5] - hand.points[17])
    assert RelativeTouchpad._finger(s.surface, hand.points, 8, 6, scale, p['touch_height'], .02, hand.depth)
    hand.depth[6] = .6 * scale
    assert not RelativeTouchpad._finger(s.surface, hand.points, 8, 6, scale, p['touch_height'], .02, hand.depth)


@pytest.mark.parametrize('key,edit', [
    ('left', lambda a: a.update(x=.5 + abs(a['x'] - .5))),
    ('far', lambda a: a.update(log_scale=abs(a['log_scale']), y=.6)),
])
def test_ambiguous_direction_missing_releases_or_conflicting_fingers_require_retry(key, edit):
    s = populated(session('object'))
    assert not s.finger_style   # 물체 마우스는 손 클릭이 없다 (이동만 보정)
    for a in s.data[key]:
        edit(a)
    with pytest.raises(CalibrationError) as exc:
        s.solve()
    assert exc.value.step == key


@pytest.mark.parametrize('key,edit', [
    ('click', lambda a: a.update(pinch=.9)),
    ('right_click', lambda a: a.update(pinch=a['middle'])),
])
def test_pinch_style_conflicting_fingers_require_retry(key, edit):
    s = populated(session('hand'))
    for a in s.data[key]:
        edit(a)
    with pytest.raises(CalibrationError) as exc:
        s.solve()
    assert exc.value.step == key


@pytest.mark.parametrize('overhead', [False, True])
def test_pen_cannot_apply_indistinguishable_contact_and_lift(overhead):
    s = populated(session('pen', TouchSurface.overhead() if overhead else None, overhead))
    s.data['lift_near'] = s.data['touch_near']
    s.data['lift_far'] = s.data['touch_far']
    with pytest.raises(CalibrationError) as exc:
        s.solve()
    assert exc.value.step == 'lift_near'


def test_missing_stale_nonfinite_samples_retry_and_inactivity_cancels():
    s = session('object', hand_clicks=False)
    s.record('rest', 5.)
    for t in np.linspace(5, 7, 60):
        s.observe({'t': 4.9, 'x': .5, 'y': .5, 'log_scale': 0.}, t)
    assert s.phase == 'recording' and s.state()['feedback']['level'] == 'waiting'
    s.observe(None, 15.)
    assert s.phase == 'ready' and '관측이 부족' in s.error
    s.record('rest', 20.)
    for t in np.linspace(20, 30, 60):
        s.observe({'t': 20.1, 'x': float('nan'), 'y': .5, 'log_scale': 0.}, t)
    assert not s.data and s.phase == 'ready'
    s.observe(None, 160.)
    assert s.phase == 'cancelled' and '기존 설정' in s.error


def test_retry_redirects_only_failed_measurement_and_reuses_other_completed_steps():
    s = populated(session())
    for a in s.data['left']:
        a['x'] = .5 + abs(a['x'] - .5)
    s.index = len(s.steps) - 1
    s.buffer = step_samples(s.steps[-1])
    s.finish(12.)
    assert s.phase == 'ready' and s.steps[s.index].key == 'lr'  # 실패한 부분이 속한 단계만 다시
    assert s.state()['completed'] == len(s.steps) - 1
    s.buffer = step_samples(s.steps[s.index])
    s.finish(21.)
    assert s.phase == 'review' and s.result


def test_pipeline_calibration_suppresses_outputs_and_does_not_modify_pen_model_or_draw():
    from vision_input.pen import PenTracker
    p = VisionProcessor(None)
    p.hands = None
    image, mask = pen_frame(), pen_mask()
    pen = PenTracker((700, 500), (600, 200))
    p.pens[1] = pen
    out = _out(mask, None)
    p.objects[1] = Mock(id=1, kind='pen', out=out)
    p.frame_size = (1280, 720)
    p.latest = Frame(1, image, 0, 0)
    before = p.mouse.settings.model_dump()
    p.start_auto_calibration('pen', 1)
    p.sink.button('left', True)
    p.sink.key('w', True)
    pen.surface.add(15, 500)
    model_samples = list(pen.surface.samples)
    # 등록 정보가 없는 모의 물체의 state만 생략하고 실제 출력 중지 분기를 검사한다.
    p.state = lambda: {}
    p.process(Frame(2, image, time.monotonic(), time.monotonic()))
    assert not p.sink.snapshot()['left'] and not p.sink.controller_snapshot()['keys']
    assert list(pen.surface.samples) == model_samples
    assert pen.suspended and not pen.contact and not pen.cur
    p.cancel_auto_calibration()
    assert not pen.suspended and p.mouse.settings.model_dump() == before


def test_atomic_apply_releases_buttons_and_keeps_unrelated_manual_settings():
    p = VisionProcessor(None)
    p.hands = None
    original = MouseSettings(mode='object', object_id=1, hand_clicks=False, touch_margin=.08)
    p.mouse.configure(original)
    s = populated(session('object', hand_clicks=False))
    s.result, s.phase = s.solve(), 'review'
    p.auto_calibration = s
    p.sink.button('left', True)
    response = p.apply_auto_calibration(s.id)
    assert response['calibration']['phase'] == 'complete'
    assert p.mouse.settings.touch_margin == .08
    assert p.mouse.settings.depth_sensitivity != original.depth_sensitivity
    assert not p.sink.snapshot()['left']
    with pytest.raises(ValueError):
        p.apply_auto_calibration(s.id)


def test_auto_calibration_api_guards_sessions_live_source_apply_and_manual_changes():
    p = VisionProcessor(None)
    p.hands = None  # 카메라·손 모델 없이 실제 HTTP/엔진 순서 검증
    app = create_app(initial_source=SyntheticSpec(width=320, height=240, fps=30),
                     processor=p, segmenter=RectSeg(), serve_frontend=False)
    with TestClient(app) as c:
        oid = _wait_frame(c).json()['id']
        assert c.get('/api/auto-calibration').json() is None
        assert c.post('/api/auto-calibration/start', json={'kind': 'hand'}).status_code == 409
        assert c.put('/api/mouse', json={'mode': 'object', 'object_id': oid, 'hand_clicks': False}).status_code == 200
        before = c.get('/api/mouse').json()['settings']
        state = c.post('/api/auto-calibration/start', json={'kind': 'object', 'object_id': oid}).json()
        assert state['phase'] == 'ready'
        assert c.post('/api/auto-calibration/start', json={'kind': 'object', 'object_id': oid}).status_code == 409
        body = {'session_id': state['id']}
        assert c.post('/api/auto-calibration/apply', json=body).status_code == 409
        assert c.post('/api/auto-calibration/record', json={**body, 'step_key': 'wrong'}).status_code == 409
        assert c.post('/api/auto-calibration/cancel', json={'session_id': '0' * 32}).status_code == 409
        assert c.put('/api/mouse', json={'depth_gain': 2}).status_code == 409
        assert c.post('/api/auto-calibration/record', json={**body, 'step_key': 'rest'}).json()['phase'] == 'recording'
        assert c.post('/api/auto-calibration/skip', json={**body, 'step_key': 'wrong'}).status_code == 409
        skipped = c.post('/api/auto-calibration/skip', json={**body, 'step_key': 'rest'}).json()
        assert skipped['phase'] == 'ready' and skipped['skipped'][0]['key'] == 'rest'
        assert skipped['step']['key'] == 'lr'
        assert c.post('/api/auto-calibration/cancel', json=body).json()['phase'] == 'cancelled'
        assert c.get('/api/mouse').json()['settings'] == before
        c.post('/api/auto-calibration/start', json={'kind': 'object', 'object_id': oid})
        c.put('/api/source/playback', json={'paused': True})
        assert c.get('/api/auto-calibration').json()['phase'] == 'cancelled'
        assert c.post('/api/auto-calibration/start', json={'kind': 'object', 'object_id': oid}).status_code == 409
        c.put('/api/source/playback', json={'paused': False})
        c.post('/api/auto-calibration/start', json={'kind': 'object', 'object_id': oid})
        c.post('/api/stop')
        assert c.get('/api/auto-calibration').json()['phase'] == 'cancelled'


def test_pen_mouse_calibrates_pen_contact_without_hand_gestures():
    s = populated(session('pen', mode='object', object_id=1, hand_clicks=True))
    assert not s.needs_hands
    assert 'gesture_click' not in [step.key for step in s.steps]
    result = s.solve()
    assert 'pinch_on' not in result['mouse'] and 'finger_press' not in result['mouse']
    assert 'touch_on' in result['pen']


def test_finger_style_calibration_measures_press_ratio_and_touch_distance():
    h = populated(session('hand', hand_click_style='finger'))
    r = h.solve()['mouse']
    assert 'finger_press' in r and 'object_tap_distance' not in r  # 맨손은 물체가 없다


def test_pen_model_and_slider_values_change_only_after_apply():
    from vision_input.pen import PenTracker
    p = VisionProcessor(None)
    p.hands = None
    p.pens[1] = PenTracker((700, 500), (600, 200))
    pen = p.pens[1]
    old_surface, old_on = pen.surface, pen.cfg.touch_on
    s = populated(session('pen'))
    s.result, s.phase = s.solve(), 'review'
    p.auto_calibration = s
    assert pen.surface is old_surface and pen.cfg.touch_on == old_on
    response = p.apply_auto_calibration(s.id)
    assert pen.surface is s.pen_surface and pen.surface.fixed
    assert pen.cfg.touch_on == s.result['pen']['touch_on']
    assert response['pen']['settings']['touch_on'] == pen.cfg.touch_on
    assert pen.cfg.edge_span == .4  # 보정에 무관한 수동 슬라이더 보존


@pytest.mark.parametrize('finger', ['touch', 'middle_touch'])
def test_touchpad_scroll_checks_actual_contact_of_both_fingers(finger):
    s = populated(session(hand_control='touchpad'))
    for a in s.data['scroll']:
        a[finger] = -.4
    with pytest.raises(CalibrationError) as exc:
        s.solve()
    assert exc.value.step == 'scroll'


def test_touchpad_existing_line_geometry_is_preserved_and_observed_range_is_learned():
    original = TouchSurface.line([[.1, .6], [.9, .6]])
    s = populated(session(surface=original, hand_control='touchpad'))
    s.solve()
    assert np.array_equal(s.inferred_surface.points, original.points)
    assert original.contact_bounds is None  # 적용 전 기존 보정은 변경되지 않는다.
    for key in ('near', 'far'):
        a = s.data[key][-1]
        assert s.inferred_surface.contains(np.array([a['x'], a['y']]), 0.)


def test_live_feedback_detects_motion_click_release_and_missing_target():
    s = session()
    s.observe(None, .1)
    assert s.state()['feedback']['level'] == 'waiting'
    s.observe(samples('rest')[0], .2)
    assert s.state()['feedback']['level'] == 'good'
    s.data['rest'] = samples('rest')
    s.index = next(i for i, step in enumerate(s.steps) if step.key == 'clicks')
    s.record('clicks', 10.)
    for a in step_samples(s.steps[s.index])[:115]:
        a['t'] += 10.
        s.observe(a, a['t'])
    f = s.state()['feedback']
    assert f['cycles'] >= 2 and '왼쪽' in f['message'] and '오른쪽' in f['message']
    s.observe(None, 25.6)
    assert s.state()['feedback']['level'] == 'waiting'


def test_missing_observations_extend_measurement_without_failing_early():
    s = session('object', hand_clicks=False)
    s.record('rest', 0.)
    for t in np.linspace(0., 2., 50):
        s.observe(None, t)
    assert s.phase == 'recording' and not s.error and s.progress == 0
    for a in samples('rest', 2.):
        a['t'] += 2.
        s.observe(a, a['t'])
    assert s.phase == 'ready' and s.steps[s.index].key == 'lr'


def test_stale_observations_do_not_count_as_measurement_or_ready_feedback():
    s = session('object', hand_clicks=False)
    s.record('rest', 0.)
    s.observe({'t': 0., 'x': .5, 'y': .5, 'log_scale': 0.}, 0.)
    s.observe({'t': .1, 'x': .5, 'y': .5, 'log_scale': 0.}, .1)
    valid_time = s.valid_time
    s.observe({'t': .2, 'x': .5, 'y': .5, 'log_scale': 0.}, 1.)
    assert s.state()['feedback']['level'] == 'waiting'
    assert s.valid_time == valid_time
    s.observe({'t': 1.1, 'x': .5, 'y': .5, 'log_scale': 0.}, 1.1)
    assert s.valid_time == valid_time  # 인식이 돌아오기 전의 공백은 수집 시간에서 제외한다.


def test_depth_steps_validate_actual_input_signal_instead_of_unrelated_image_y():
    s = session('object', hand_clicks=False)
    a = samples('near')
    for sample in a:
        sample['log_scale'] = 0.
    with pytest.raises(CalibrationError):
        s._validate('near', a)  # y alone moves, but default depth input would not.


def test_object_motion_does_not_require_hands_but_gesture_steps_do():
    from types import SimpleNamespace
    from vision_input.tracking.api import TrackState
    p = VisionProcessor(None)
    p.hands = None
    p.frame_size = (1280, 720)
    p.objects[1] = SimpleNamespace(id=1, out=SimpleNamespace(state=TrackState.TRACKING,
        confidence=.9, debug={}, box=(400, 300, 600, 500), pose=SimpleNamespace(cx=500, cy=400, scale=1.)))
    p.auto_calibration = session('object', hand_clicks=True)   # 예전 설정이 켜져 와도 손 단계가 없다
    s = p.auto_calibration
    assert 'clicks' not in [step.key for step in s.steps]
    s.index = next(i for i, step in enumerate(s.steps) if step.key == 'lr')
    assert p._auto_sample(None, 1.) is not None


@pytest.mark.parametrize('kind,options', [('hand', {}), ('hand', {'hand_control': 'touchpad'}), ('object', {}), ('pen', {})])
def test_each_skipped_step_preserves_missing_measurements_instead_of_crashing(kind, options):
    baseline = session(kind, **options)
    for step in baseline.steps:
        s = populated(session(kind, **options))
        for part in s.parts_of(step):
            s.data.pop(part)
        s.skipped[step.key] = '인식 실패'
        result = s.solve()
        assert result['notes']
        if kind == 'object' and step.key == 'clicks':
            assert 'object_tap_distance' not in result['mouse'] and 'finger_press' not in result['mouse']
        if kind == 'pen' and step.key in ('touch', 'lift'):
            assert s.pen_surface is None and s.pen_contact is None
            assert 'touch_on' not in result['pen']


def test_all_steps_can_be_skipped_and_a_skipped_step_can_be_retested():
    s = session(hand_control='touchpad')
    for step in s.steps:
        s.skip(step.key, 0.)
    assert s.phase == 'review' and s.result['mouse'] == {}
    assert len(s.skipped) == len(s.steps)
    s.back(1.)
    assert s.phase == 'ready' and s.steps[s.index].key not in s.skipped
    s.record(s.steps[s.index].key, 2.)
    assert s.phase == 'recording'
    with pytest.raises(ValueError):
        s.skip('rest', 3.)  # stale browser action must not skip a different step


def test_partial_apply_keeps_unmeasured_touch_distance_setting():
    p = VisionProcessor(None)
    p.hands = None
    original = MouseSettings(mode='object', object_id=1, object_tap_distance=.12)
    p.mouse.configure(original)
    s = populated(session('object', mode='object', object_id=1, object_tap_distance=.12))
    s.result, s.phase = s.solve(), 'review'
    p.auto_calibration = s
    response = p.apply_auto_calibration(s.id)
    assert response['calibration']['phase'] == 'complete'
    assert p.mouse.settings.object_tap_distance == original.object_tap_distance
    assert p.mouse.settings.depth_sensitivity != original.depth_sensitivity


def test_wizard_has_fewer_steps_than_before():
    # 이전: 맨손·물체 8단계(펜 13단계). 이제 같은 동작을 한 번에 측정한다.
    assert [st.key for st in session('object').steps] == ['rest', 'lr', 'nf']
    assert [st.key for st in session('object', hand_clicks=False).steps] == ['rest', 'lr', 'nf']
    assert [st.key for st in session('pen').steps] == ['rest', 'touch', 'lift', 'lr', 'nf', 'click']
    assert len(session('hand').steps) <= 5 and 'precision' not in [st.key for st in session('hand').steps]


def test_one_sided_or_too_small_motion_is_rejected_with_the_part_that_failed():
    s = session('object')
    one_sided = step_samples(s.steps[1])
    for a in one_sided:
        a['x'] = .5 + abs(a['x'] - .5)  # 왼쪽으로 가지 않음
    s.index = 1
    s.buffer = one_sided
    s.finish(9.)
    assert s.phase == 'ready' and s.steps[s.index].key == 'lr' and s.error
    assert 'right' not in s.data and 'left' not in s.data  # 실패하면 일부만 저장하지 않는다


@pytest.mark.parametrize('mirror', [False, True])
def test_merged_motion_steps_split_into_right_left_near_far_and_detect_mirror(mirror):
    s = session('object', hand_clicks=False)
    for step in s.steps:
        s.index = s.steps.index(step)
        s.buffer = step_samples(step, mirror=mirror)
        s.finish(100.)
        assert s.phase in ('ready', 'review'), s.error
    assert s.phase == 'review'
    assert {'right', 'left', 'near', 'far'} <= set(s.data)
    assert s.result['mouse']['mirror'] is mirror


def test_quick_movement_calibration_keeps_click_settings_and_needs_no_hand_for_objects():
    s = AutoCalibration('object', 1, MouseSettings(hand_clicks=True, pinch_on=.37), None, False, 0., movement_only=True)
    assert [step.key for step in s.steps] == ['rest', 'lr', 'nf']
    assert not s.needs_hands and not s.step_needs_hands
    t = 0.
    for step in s.steps:
        s.record(step.key, t)
        for sample in step_samples(step):
            sample['t'] += t
            s.observe(sample, sample['t'])
        t += step.duration + 1
    assert s.phase == 'review', s.error
    assert 'pinch_on' not in s.result['mouse'] and 'finger_press' not in s.result['mouse']


def test_round_trip_can_reverse_without_crossing_original_start_or_a_center():
    s = session('object', hand_clicks=False)
    step = next(st for st in s.steps if st.key == 'lr')
    rows = samples('rest', duration=step.duration)
    for i, a in enumerate(rows):
        phase = i / (len(rows) - 1)
        # Start at .65, visit .85, end at .72: reverse without ever reaching the start again.
        a['x'] = .65 + .2 * min(phase / .45, 1) if phase <= .55 else .85 - .13 * min((phase - .55) / .35, 1)
    parts = s._validate_step(step, rows)
    assert delta(parts['right'], 'x') > .025 and delta(parts['left'], 'x') < -.025
    assert min(a['x'] for a in parts['left']) > rows[0]['x']


def test_quick_hand_calibration_still_requests_hand_worker_without_gesture_steps():
    s = AutoCalibration('hand', None, MouseSettings(mode='off'), None, False, 0., movement_only=True)
    assert s.needs_hands and s.step_needs_hands
    assert [step.key for step in s.steps] == ['rest', 'lr', 'nf']
