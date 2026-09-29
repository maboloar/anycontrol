"""안내 보정: 실제 신호로 설정 계산, 부실한 동작 재검사, 원자적 적용/취소와 출력 중지."""
import math
import time
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from vision_input.auto_calibration import AutoCalibration, CalibrationError
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
    return AutoCalibration(kind, None if kind == 'hand' else 1, MouseSettings(**settings), surface, overhead, 0.)


def samples(key, duration=3., pen=False, overhead=False, mirror=False, plane=False):
    out = []
    for i, t in enumerate(np.linspace(.01, duration, 60)):
        motion = np.clip((t - .6) / max(duration - 1.2, .5), 0, 1)
        down = i % 20 in range(5, 13)
        a = dict(t=float(t), x=.5, y=.6, log_scale=math.log(15) if pen else 0., frame_h=720,
                 pinch=1., middle=1.2, scroll_pose=False, scroll=3., scroll_x=.5, scroll_y=.6,
                 log_knuckle=0., touch=.2, middle_touch=.2, gap=.6, raw_y=350., width=15., length=80., sharp=80.)
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


def populated(s, mirror=False):
    for step in s.steps:
        s.data[step.key] = samples(step.key, step.duration, s.kind == 'pen', s.overhead, mirror)
    return s


@pytest.mark.parametrize('kind,options', [('hand', {}), ('object', {'hand_clicks': True}), ('object', {'hand_clicks': False})])
def test_guided_sessions_reach_review_using_observed_motion_clicks_and_release(kind, options):
    s = session(kind, **options)
    t = 0.
    for step in s.steps:
        assert s.phase == 'ready' and s.steps[s.index].key == step.key
        s.record(step.key, t)
        for a in samples(step.key, step.duration):
            a['t'] += t
            s.observe(a, a['t'])
        t += step.duration + 1
    assert s.phase == 'review', s.error
    assert s.state()['completed'] == len(s.steps)
    patch = s.result['mouse']
    assert 1 < patch['depth_sensitivity'] < 2
    assert not patch['invert_y'] and not patch['mirror']
    assert .0005 <= patch['depth_deadzone'] < .01
    if s.needs_hands:
        assert .15 < patch['pinch_on'] < .5
        assert patch['scroll_gain'] == pytest.approx(12)
    if kind == 'object' and s.needs_hands:
        assert .03 < patch['object_tap_distance'] < .25
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
    ('click', lambda a: a.update(pinch=.9)),
    ('right_click', lambda a: a.update(pinch=a['middle'])),
    ('tap_click', lambda a: a.update(gap=.02)),
])
def test_ambiguous_direction_missing_releases_or_conflicting_fingers_require_retry(key, edit):
    s = populated(session('object'))
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
    s.buffer = samples('precision', 4.)
    s.finish(4.)
    assert s.phase == 'ready' and s.steps[s.index].key == 'left'
    assert len(s.data) == len(s.steps) - 1
    s.buffer = samples('left')
    s.finish(8.)
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
        assert skipped['step']['key'] == 'right'
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


def test_pen_mouse_with_hand_clicks_calibrates_both_pen_contact_and_hand_gestures():
    s = populated(session('pen', mode='object', object_id=1, hand_clicks=True))
    assert s.needs_hands
    assert 'gesture_click' in [step.key for step in s.steps]
    result = s.solve()
    assert 'pinch_on' in result['mouse'] and 'scroll_gain' in result['mouse']
    assert 'touch_on' in result['pen']


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
    s.index = next(i for i, step in enumerate(s.steps) if step.key == 'click')
    s.record('click', 10.)
    for a in samples('click', 6.)[:55]:
        a['t'] += 10.
        s.observe(a, a['t'])
    f = s.state()['feedback']
    assert f['cycles'] >= 2 and '놓기' in f['message']
    s.observe(None, 15.6)
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
    assert s.phase == 'ready' and s.steps[s.index].key == 'right'


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
    p.auto_calibration = session('object', hand_clicks=True)
    s = p.auto_calibration
    s.index = next(i for i, step in enumerate(s.steps) if step.key == 'right')
    assert p._auto_sample(None, 1.) is not None
    s.index = next(i for i, step in enumerate(s.steps) if step.key == 'click')
    assert p._auto_sample(None, 1.) is None
    assert '손' in s.observation_issue


def test_repeated_object_tap_failure_can_be_skipped_without_changing_tap_threshold():
    s = populated(session('object', object_tap_distance=.12))
    s.index = next(i for i, step in enumerate(s.steps) if step.key == 'tap_touch')
    s.data.pop('tap_touch')
    s.data.pop('tap_click')
    for attempt in range(2):
        s.record('tap_touch', attempt * 20.)
        s.buffer = samples('tap_lift', 2.)  # 접촉하지 않은 표본을 접촉 단계에 제출
        s.finish(attempt * 20. + 2.)
        assert s.phase == 'ready' and s.steps[s.index].key == 'tap_touch'
        assert s.state()['attempts_failed'] == attempt + 1
    s.skip('tap_touch', 43.)
    assert s.steps[s.index].key == 'tap_click'
    s.record('tap_click', 44.)
    s.buffer = samples('tap_click', 6.)
    s.finish(50.)
    assert s.phase == 'review'
    assert 'depth_sensitivity' in s.result['mouse']
    assert 'object_tap_distance' not in s.result['mouse']
    assert s.settings.object_tap_distance == .12
    assert s.state()['skipped'][0]['key'] == 'tap_touch'
    assert any('건너뛴 검사' in note for note in s.result['notes'])


@pytest.mark.parametrize('kind,options', [('hand', {}), ('hand', {'hand_control': 'touchpad'}), ('object', {}), ('pen', {})])
def test_each_skipped_step_preserves_missing_measurements_instead_of_crashing(kind, options):
    baseline = session(kind, **options)
    for step in baseline.steps:
        s = populated(session(kind, **options))
        s.data.pop(step.key)
        s.skipped[step.key] = '인식 실패'
        result = s.solve()
        assert result['notes']
        if step.key in ('tap_lift', 'tap_touch', 'tap_click'):
            assert 'object_tap_distance' not in result['mouse']
        if kind == 'pen' and step.key.startswith(('touch_', 'lift_')):
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


def test_partial_apply_keeps_unmeasured_object_tap_setting():
    p = VisionProcessor(None)
    p.hands = None
    original = MouseSettings(mode='object', object_id=1, object_tap_distance=.12)
    p.mouse.configure(original)
    s = populated(session('object', mode='object', object_id=1, object_tap_distance=.12))
    s.data.pop('tap_touch')
    s.skipped['tap_touch'] = '인식 실패'
    s.result, s.phase = s.solve(), 'review'
    p.auto_calibration = s
    response = p.apply_auto_calibration(s.id)
    assert response['calibration']['phase'] == 'complete'
    assert p.mouse.settings.object_tap_distance == original.object_tap_distance
    assert p.mouse.settings.depth_sensitivity != original.depth_sensitivity
