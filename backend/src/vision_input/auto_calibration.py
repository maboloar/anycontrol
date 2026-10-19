"""안내에 따라 수집한 관측만으로 입력 설정을 계산한다. 적용 전에는 원래 설정을 바꾸지 않는다."""
from __future__ import annotations

from dataclasses import dataclass
import math
import uuid

import numpy as np

from .io.touchpad import TouchSurface
from .pen import SurfaceModel
from .pen_contact import OverheadContact


FINGER_PRESS = .6     # 든 높이 대비 이 비율 아래면 내려간 것 (보정 중 실시간 확인용 기본값)
MIN_RAISED = .35      # 든 손가락의 손바닥 축 높이(손 크기 대비) 최소


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    instruction: str
    duration: float = 3.
    # 한 번의 측정에서 여러 검사 데이터를 얻는 합성 단계: 안내 한 번에 parts 의 키들로 나눠 저장한다.
    parts: tuple = ()
    split: str = ''       # extrema: 처음 한 쪽 끝, 다음 반대쪽 끝 / timed: 시간 균등 / same: 같은 표본을 모두에


class CalibrationError(ValueError):
    def __init__(self, message: str, step: str):
        super().__init__(message)
        self.step = step


def values(samples, key):
    return np.array([s[key] for s in samples], float)


def delta(samples, key):
    a = values(samples, key)
    n = max(2, len(a) // 5)
    return float(np.median(a[-n:]) - np.median(a[:n]))


def noise(samples, key):
    a = values(samples, key)
    return float(1.4826 * np.median(np.abs(a - np.median(a))))


def clip(value, lo, hi):
    return round(float(np.clip(value, lo, hi)), 4)


def cycles(a, on, off):
    down = False
    presses = releases = run = 0
    for value in a:
        matches = value < on if not down else value > off
        run = run + 1 if matches else 0
        if run >= 2:
            down = not down
            presses += int(down)
            releases += int(not down)
            run = 0
    return min(presses, releases)


class AutoCalibration:
    def __init__(self, kind, object_id, settings, surface, overhead, t, movement_only=False):
        self.id = uuid.uuid4().hex
        self.kind, self.object_id = kind, object_id
        self.movement_only = bool(movement_only and kind != "pen")
        self.settings = settings.model_copy(deep=True)
        self.surface, self.overhead = surface, overhead
        self.needs_hands = kind == 'hand' or kind == 'object' and settings.hand_clicks and not settings.object_hybrid
        # 검지·중지를 든 채 내려서 누르는 방식 (물체 마우스는 항상, 맨손은 클릭 방식이 finger 이고 터치패드가 아닐 때)
        self.needs_hands = kind == 'hand' or self.needs_hands and not self.movement_only
        self.finger_style = not self.movement_only and (kind == 'object' and settings.hand_clicks and not settings.object_hybrid or
                             kind == 'hand' and settings.hand_click_style == 'finger' and settings.hand_control != 'touchpad')
        self.phase = 'ready'
        self.index = 0
        self.started = self.last_action = t
        self.buffer = []
        self.data = {}
        self.skipped = {}
        self.failures = {}
        self.error = None
        self.result = None
        self.pen_surface = self.pen_contact = self.inferred_surface = None
        self.last_sample = None
        self.progress = 0.
        self.observation_issue = None
        self.preview = None
        self.last_observed_at = None
        self.valid_time = 0.
        self.steps = self._steps()

    @property
    def active(self):
        return self.phase in ('ready', 'recording', 'review')

    @property
    def step_needs_hands(self):
        key = self.steps[self.index].key
        return self.kind == 'hand' or self.needs_hands and key in (
            'rest', 'gesture_click', 'right_click', 'scroll', 'clicks')

    @property
    def absolute(self):
        return (self.kind == 'hand' and self.settings.hand_control == 'air' or
                self.kind == 'object' and self.settings.coordinate_mode == 'image' or
                self.kind == 'pen' and not self.settings.pen_relative and self.settings.coordinate_mode == 'image')

    def _steps(self):
        """안내 단계. 같은 동작을 한 번에 측정할 수 있는 검사는 합쳐 단계를 줄였다 (좌우, 앞뒤, 두 클릭, 펜 접촉/떼기)."""
        subject = '펜촉' if self.kind == 'pen' else '검지' if self.settings.hand_control == 'touchpad' and self.kind == 'hand' else '손바닥' if self.kind == 'hand' else '물체'
        object_subject = subject + ('를' if subject in ('물체', '검지') else '을')
        rest_hint = (' 물체를 엄지·새끼손가락으로 잡고 검지·중지·약지는 든 채로 두세요.' if self.kind == 'object' else
                     ' 검지·중지·약지를 든 채로 두세요.') if self.finger_style else ' 손가락은 집지 말고 편하게 펴세요.'
        if self.kind == 'object' and self.settings.object_hybrid:
            rest_hint = ' 물체를 평소처럼 잡고 유지하세요.'
        steps = [Step('rest', '가만히 두기', f'{object_subject} 잘 보이는 편한 위치에 두고 잠깐 멈추세요. 화면 중앙에 맞출 필요는 없어요.' + rest_hint, 1.5)]
        if self.kind == 'pen':
            steps += [Step('touch', '책상에 대기', '펜을 평소 기울기로 책상에 대고 가까운 곳 → 먼 곳 → 중간 곳 순서로 옮기세요. 각 위치에서 2초씩 멈추세요.', 8., parts=('touch_near', 'touch_far', 'touch_side'), split='timed'),
                      Step('lift', '펜 들기', '같은 기울기로 펜촉을 2–3cm 들고 가까운 곳 → 먼 곳 순서로 각각 2초씩 멈추세요.', 6., parts=('lift_near', 'lift_far'), split='timed')]
        elif self.kind == 'hand' and self.settings.hand_control == 'touchpad' and not self.movement_only:
            steps += [Step('touch', '검지 대기', '책상에 검지를 가볍게 대고 유지하세요.', 2.),
                      Step('lift', '검지 떼기', '같은 위치에서 검지를 책상에서 들어 유지하세요.', 2.)]
        suffix = ' 펜촉은 책상에 대고 움직이세요.' if self.kind == 'pen' else ' 검지는 책상에 대고 움직이세요.' if self.kind == 'hand' and self.settings.hand_control == 'touchpad' else ''
        steps.append(Step('lr', '좌우로 움직이기', f'지금 위치에서 {object_subject} 오른쪽으로 천천히 움직여 잠깐 멈춘 뒤, 그 자리에서 왼쪽으로 움직여 멈추세요. 중앙으로 원위치시키지 않아도 됩니다.' + suffix, 7., parts=('right', 'left'), split='extrema'))
        if self.kind == 'hand' and self.settings.hand_control == 'air':
            steps.append(Step('nf', '영상에서 위아래로 움직이기', '지금 위치에서 손을 영상 위쪽으로 움직여 잠깐 멈춘 뒤, 그 자리에서 아래쪽으로 움직여 멈추세요. 카메라와의 거리를 유지하고 중앙으로 돌아오지 않아도 됩니다.', 7., parts=('near', 'far'), split='extrema'))
        else:
            steps.append(Step('nf', '앞뒤로 움직이기', f'현재 위치에서 {object_subject} 카메라 쪽으로 천천히 움직여 잠깐 멈춘 뒤, 그 자리에서 카메라 반대쪽으로 움직여 멈추세요. 기울기는 유지하고 중앙으로 돌아오지 않아도 됩니다.' + suffix, 7., parts=('near', 'far'), split='extrema'))
        if self.kind == 'pen':
            steps.append(Step('click', '펜 눌러 보기', '중간 거리에서 펜촉을 책상에 댔다 떼세요. 천천히 3번 반복하세요.', 6.))
        if self.needs_hands and not self.movement_only:
            contact = ' 검지는 책상에 둔 채 하세요.' if self.kind == 'hand' and self.settings.hand_control == 'touchpad' else ''
            if self.finger_style:
                where = '물체에 닿을 때까지' if self.kind == 'object' else '아래로'
                steps.append(Step('clicks', '클릭해 보기', f'먼저 중지를 {where} 내렸다 올리기를 3번, 이어서 검지를 {where} 내렸다 올리기를 3번 하세요. 다른 손가락은 든 채로 두세요.', 12., parts=('click', 'right_click'), split='same'))
            else:
                steps.append(Step('clicks', '클릭해 보기', '먼저 엄지와 검지 끝을 맞댔다 떼기를 3번, 이어서 엄지와 중지 끝을 맞댔다 떼기를 3번 하세요 (오른쪽 클릭 때는 검지를 떨어뜨리세요).' + contact, 12., parts=('click', 'right_click'), split='same'))
                steps.append(Step('scroll', '스크롤 해 보기', '검지·중지만 펴고 엄지·약지·새끼를 접으세요. 측정 시작 후 잠깐 기다렸다가 아래로 스크롤할 동작으로 움직여 유지하세요.' + (' 두 손가락을 책상에 대세요.' if self.settings.hand_control == 'touchpad' and self.kind == 'hand' else '')))
        return steps

    # ------------------------------------------------------------------ 합성 단계 (한 번 측정 → 여러 데이터)
    @staticmethod
    def parts_of(step):
        return step.parts or (step.key,)

    def step_of(self, key):
        """키(단계 키 또는 합성 단계의 부분 키)가 속한 단계의 위치."""
        return next(i for i, st in enumerate(self.steps) if st.key == key or key in st.parts)

    def _done(self, step):
        return all(p in self.data for p in self.parts_of(step))

    def _move_signal(self, key, sample):
        return sample['x'] if key == 'lr' else self._signal(sample)[1]

    def _split(self, step, samples):
        key = step.key
        if step.split == 'same':
            return {p: list(samples) for p in step.parts}
        if step.split == 'timed':
            n, t0, t1 = len(step.parts), samples[0]['t'], samples[-1]['t']
            width = (t1 - t0) / n
            out = {}
            for i, part in enumerate(step.parts):
                lo, hi = t0 + i * width + .25 * width, t0 + (i + 1) * width - .05 * width  # 다음 위치로 옮기는 시작 구간 제외
                seg = [a for a in samples if lo <= a['t'] <= hi]
                if len(seg) < 5:
                    raise CalibrationError('관측이 부족합니다. 각 위치에서 멈춰 있는 동안 대상이 계속 보이게 하세요.', part)
                out[part] = seg
            return out
        sig = np.array([self._move_signal(key, a) for a in samples], float)
        if len(sig) >= 5:  # 한 프레임 튐 제거 (3점 중앙값)
            sig = np.array([np.median(sig[max(0, i - 1):i + 2]) for i in range(len(sig))])
        n = max(2, len(sig) // 8)
        dev = sig - float(np.median(sig[:n]))
        # Find the first intentional stroke, then its turn. The return stroke gets
        # its own starting point; neither stroke must cross a global center.
        moving = np.flatnonzero(np.abs(dev) >= .025)
        if not len(moving):
            raise CalibrationError('움직임이 작습니다. 지금 위치에서 한쪽으로 움직인 뒤 반대 방향으로 움직여 주세요.', step.parts[0])
        direction = 1 if dev[moving[0]] > 0 else -1
        turn = int(np.argmax(direction * dev))
        first, second = samples[:turn + 1], samples[turn:]
        if len(first) < 5 or len(second) < 5 or direction * (sig[turn] - float(np.median(sig[-n:]))) < .025:
            raise CalibrationError('한쪽으로 움직인 다음, 그 자리에서 반대 방향으로 움직여 잠깐 멈추세요.', step.parts[1])
        return {step.parts[0]: first, step.parts[1]: second}

    def _validate_step(self, step, samples):
        """단계 하나의 관측을 나눠 부분 검사를 모두 통과해야 저장한다. 실패하면 아무것도 저장하지 않는다."""
        parts = self._split(step, samples)
        saved = dict(self.data)
        try:
            for part in step.parts:
                self._validate(part, parts[part])
                self.data[part] = parts[part]
        except CalibrationError:
            self.data = saved
            raise
        return parts

    def state(self):
        step = self.steps[self.index]
        return {'id': self.id, 'kind': self.kind, 'object_id': self.object_id, 'phase': self.phase,
                'index': self.index, 'total': len(self.steps), 'completed': sum(self._done(st) for st in self.steps),
                'step': {'key': step.key, 'title': step.title, 'instruction': step.instruction, 'duration': step.duration},
                'progress': round(self.progress, 3), 'samples': len(self.buffer), 'error': self.error,
                'result': self.result, 'feedback': self.feedback(),
                'skipped': [{'key': k, 'title': next(s.title for s in self.steps if s.key == k), 'reason': reason} for k, reason in self.skipped.items()],
                'attempts_failed': self.failures.get(step.key, 0)}

    def record(self, step_key, t):
        if self.phase != 'ready' or step_key != self.steps[self.index].key:
            raise ValueError('단계가 바뀌었습니다. 현재 안내를 확인하세요.')
        self.buffer, self.error = [], None
        self.phase, self.started, self.last_action = 'recording', t, t
        self.progress = 0.
        self.valid_time = 0.
        self.last_sample = None
        self.preview = None

    def back(self, t):
        if self.phase not in ('ready', 'review') or self.index == 0:
            raise ValueError('이전 단계로 이동할 수 없습니다.')
        self.index -= 1
        for part in self.parts_of(self.steps[self.index]):
            self.data.pop(part, None)
        self.skipped.pop(self.steps[self.index].key, None)
        self.phase, self.error, self.result, self.progress = 'ready', None, None, 0.
        self.last_action = t

    def cancel(self, reason=None):
        self.phase, self.error = 'cancelled', reason
        self.buffer.clear()

    def observe(self, sample, t):
        if not self.active:
            return
        self.last_observed_at = t
        valid = (sample is not None and all(np.isfinite(v).all() for v in sample.values())
                 and 0 <= t - sample['t'] <= .25)
        self.preview = sample if valid else None
        if t - self.last_action > 120:
            self.cancel('오랫동안 진행하지 않아 보정을 종료했습니다. 기존 설정은 유지됩니다.')
            return
        if self.phase != 'recording':
            return
        duration = self.steps[self.index].duration
        if not valid:
            self.last_sample = None
        if valid and sample['t'] != self.last_sample and sample['t'] >= self.started:
            if self.last_sample is not None:
                self.valid_time += min(.2, max(0., sample['t'] - self.last_sample))
            self.last_sample = sample['t']
            self.buffer.append(sample)
        self.progress = min(1., self.valid_time / duration)
        # 인식이 잠깐 끊기면 측정 시간을 연장한다. 최대 8초 후에는 원인을 안내한다.
        if (t - self.started >= duration and self.valid_time >= duration * .8) or t - self.started >= duration + 8:
            self.finish(t)

    def feedback(self):
        key = self.steps[self.index].key
        if self.phase in ('review', 'complete'):
            return {'level': 'good', 'message': '검사를 마쳤습니다. 건너뛴 항목과 계산한 설정을 확인하세요.' if self.skipped else '모든 검사를 마쳤습니다. 계산한 설정을 확인하세요.', 'cycles': None}
        if self.phase == 'cancelled':
            return None
        if self.preview is None or (self.last_observed_at is not None and
                                    self.last_observed_at - self.preview['t'] > .25):
            return {'level': 'waiting', 'message': self.observation_issue or '대상을 인식하지 못했습니다. 손/물체 전체가 보이도록 자세를 조정하세요. 인식이 돌아오면 측정을 이어갑니다.', 'cycles': None}
        if self.phase == 'ready':
            return {'level': 'good', 'message': '대상이 보입니다. 안내 자세를 준비한 뒤 측정 시작을 누르세요.', 'cycles': None}
        data = self.buffer
        if len(data) < 4 or self.valid_time < .45:
            return {'level': 'waiting', 'message': '시작 위치를 읽고 있습니다. 잠깐 유지하세요.', 'cycles': None}
        step = self.steps[self.index]
        if step.parts:
            return self._composite_feedback(step, data)
        try:
            self._validate(key, data)
            level, message = 'good', ('동작을 확인했습니다. 안내의 끝 자세를 유지하세요.' if key in ('right', 'left', 'near', 'far', 'scroll') else '대상을 인식하며 관측을 수집하고 있습니다. 안내 자세를 유지하세요.')
        except CalibrationError as exc:
            level, message = 'warn', str(exc)
        count = None
        if key in ('click', 'right_click') and self.finger_style:
            ratio = self._finger_ratio(data, key)
            count = cycles(ratio, FINGER_PRESS, FINGER_PRESS + .15)
            held = ratio[-1] < FINGER_PRESS + .15
            level = 'good' if count >= 2 and not held else 'warn'
            message = f'내렸다 올리기 {count}/2회 이상 확인 · ' + ('손가락을 다시 완전히 올리세요.' if held else '더 아래로 내렸다 올리세요.' if count < 2 else '좋습니다. 손가락을 든 채로 유지하세요.')
        elif key in ('click', 'gesture_click', 'right_click') and self.needs_hands and not (self.kind == 'pen' and key == 'click'):
            field = 'middle' if key == 'right_click' else 'pinch'
            on = self._gesture_threshold(data, field)
            count = cycles(values(data, field), on, on * 1.5)
            held = data[-1][field] < on
            level = 'good' if count >= 2 and not held else 'warn'
            message = f'클릭 후 놓기 {count}/2회 이상 확인 · ' + ('손가락을 완전히 떼세요.' if held else '다시 맞댔다 떼세요.' if count < 2 else '좋습니다. 손가락을 편 상태로 유지하세요.')
        if key == 'rest' and level == 'good':
            message = '떨림이 안정적입니다. 움직이지 말고 유지하세요.'
        if self.kind == 'pen' and key.startswith(('touch_', 'lift_')):
            message = '펜촉 외형을 수집하고 있습니다. 기울기를 유지하세요. 접촉 여부는 닿음/떼기 표본을 비교해 확인합니다.'
        return {'level': level, 'message': message, 'cycles': count}

    def _composite_feedback(self, step, data):
        if step.split == 'same' and step.key == 'clicks':
            counts = {}
            for part in step.parts:
                if self.finger_style:
                    ratio = self._finger_ratio(data, part)
                    counts[part] = cycles(ratio, FINGER_PRESS, FINGER_PRESS + .15)
                else:
                    field = 'middle' if part == 'right_click' else 'pinch'
                    on = self._gesture_threshold(data, field)
                    counts[part] = cycles(values(data, field), on, on * 1.5)
            ok = all(c >= 2 for c in counts.values())
            message = f'왼쪽 {counts["click"]}번 · 오른쪽 {counts["right_click"]}번 확인 (각 2번 이상 필요) · ' + ('좋습니다. 손을 편하게 두세요.' if ok else '천천히 반복하세요.')
            return {'level': 'good' if ok else 'warn', 'message': message, 'cycles': min(counts.values())}
        try:
            self._split(step, data)
        except CalibrationError as exc:
            return {'level': 'warn', 'message': str(exc), 'cycles': None}
        return {'level': 'good', 'message': '동작을 확인했습니다. 안내가 끝날 때까지 마지막 자세를 유지하세요.', 'cycles': None}

    def _finger_ratio(self, samples, key):
        """클릭 손가락의 '든 높이 대비 비율'. 든 높이는 떨림 확인(rest) 단계에서 잰다."""
        field = 'h_middle' if key == 'click' else 'h_index'
        rest = values(self.data['rest'], field) if 'rest' in self.data else values(samples, field)
        ref = max(float(np.median(rest)), 1e-3)
        return values(samples, field) / ref

    def _gesture_threshold(self, samples, field):
        rest = self.data.get('rest', samples)
        opened = float(np.quantile(values(rest, field), .1))
        closed = float(np.quantile(values(samples, field), .1))
        return clip((closed + opened / 1.5) * .5, .15, .5)

    def _advance(self):
        missing = next((i for i, step in enumerate(self.steps)
                        if not self._done(step) and step.key not in self.skipped), None)
        if missing is not None:
            self.index, self.phase, self.progress = missing, 'ready', 0.
        else:
            self.result = self.solve()
            self.phase = 'review'

    def _failed(self, exc):
        self.index = self.step_of(exc.step)
        step = self.steps[self.index]
        for part in self.parts_of(step):
            self.data.pop(part, None)
        self.failures[step.key] = self.failures.get(step.key, 0) + 1
        self.error, self.phase, self.progress = str(exc), 'ready', 0.
        self.result = None

    def skip(self, step_key, t):
        if self.phase not in ('ready', 'recording') or step_key != self.steps[self.index].key:
            raise ValueError('단계가 바뀌었습니다. 현재 안내를 확인하세요.')
        self.skipped[step_key] = self.error or '사용자가 검사를 건너뛰었습니다.'
        for part in self.parts_of(self.steps[self.index]):
            self.data.pop(part, None)
        self.buffer, self.preview, self.last_sample = [], None, None
        self.error, self.result, self.last_action = None, None, t
        self.progress, self.valid_time = 0., 0.
        try:
            self._advance()
        except CalibrationError as exc:
            self._failed(exc)

    def finish(self, t):
        key = self.steps[self.index].key
        self.last_action = t
        try:
            if len(self.buffer) < 8 or self.buffer[-1]['t'] - self.buffer[0]['t'] < .8:
                raise CalibrationError('관측이 부족합니다. 카메라에 손/물체 전체가 보이도록 한 뒤 다시 측정하세요.', key)
            if self.steps[self.index].parts:
                self._validate_step(self.steps[self.index], list(self.buffer))
            else:
                self._validate(key, self.buffer)
                self.data[key] = list(self.buffer)
            self.skipped.pop(key, None)
            self.error = None
            self._advance()
        except CalibrationError as exc:
            self._failed(exc)
        self.buffer = []

    def _validate(self, key, samples):
        if key == 'rest' and (noise(samples, 'x') > .018 or noise(samples, 'y') > .025):
            raise CalibrationError('정지 중 움직임이 큽니다. 자세를 고정하고 다시 측정하세요.', key)
        if key in ('right', 'left') and abs(delta(samples, 'x')) < .025:
            raise CalibrationError('좌우 이동이 너무 작습니다. 시작 후 기다렸다가 더 크게 움직이세요.', key)
        if key in ('near', 'far'):
            signal = [self._signal(a)[1] for a in samples]
            n = max(2, len(signal) // 5)
            movement = float(np.median(signal[-n:]) - np.median(signal[:n]))
            if abs(movement) < .025:
                raise CalibrationError('앞뒤 입력 변화가 작습니다. 같은 기울기를 유지하며 카메라 쪽/반대쪽으로 더 움직이세요.', key)
            if key == 'far' and 'near' in self.data:
                near = self.data['near']
                ns = [self._signal(a)[1] for a in near]
                nn = max(2, len(ns) // 5)
                if movement * (np.median(ns[-nn:]) - np.median(ns[:nn])) >= 0:
                    raise CalibrationError('가까워지기와 같은 방향입니다. 카메라에서 멀어지는 방향으로 움직이세요.', key)
        if key == 'left' and 'right' in self.data and delta(samples, 'x') * delta(self.data['right'], 'x') >= 0:
            raise CalibrationError('오른쪽 검사와 같은 방향입니다. 반대 방향으로 움직이세요.', key)
        if key in ('click', 'right_click') and self.finger_style:
            if 'rest' in self.data and np.median(values(self.data['rest'], 'h_middle' if key == 'click' else 'h_index')) < MIN_RAISED:
                raise CalibrationError('손가락이 충분히 들려 있지 않습니다. 검지·중지를 곧게 들고 떨림 확인부터 다시 하세요.', 'rest')
            if cycles(self._finger_ratio(samples, key), FINGER_PRESS, FINGER_PRESS + .15) < 2:
                raise CalibrationError('손가락을 충분히 내렸다 완전히 올리는 동작이 2회 이상 필요합니다. 천천히 3번 반복하세요.', key)
        elif key in ('click', 'gesture_click', 'right_click') and self.needs_hands and not (self.kind == 'pen' and key == 'click'):
            field = 'middle' if key == 'right_click' else 'pinch'
            on = self._gesture_threshold(samples, field)
            if cycles(values(samples, field), on, on * 1.5) < 2:
                raise CalibrationError('클릭 후 완전히 놓기까지 2회 이상 필요합니다. 천천히 맞댔다 떼세요.', key)
        if key == 'lift' and 'touch' in self.data and np.quantile(values(self.data['touch'], 'touch'), .1) - np.quantile(values(samples, 'touch'), .9) < .08:
            raise CalibrationError('접촉 때와 자세가 비슷합니다. 검지를 더 들어 올려 유지하세요.', key)
        if key == 'scroll':
            pose = [s for s in samples if s['scroll_pose']]
            if len(pose) < 8 or (not (self.kind == 'hand' and self.settings.hand_control == 'touchpad') and abs(delta(pose, 'scroll')) < .04):
                raise CalibrationError('두 손가락 스크롤 자세와 이동이 필요합니다. 안내 자세로 다시 측정하세요.', key)

    def _signal(self, sample, surface=None):
        s = self.settings
        surface = surface or self.surface
        point = np.array([sample['x'], sample['y']])
        if self.absolute:
            return point
        plane = surface is not None and surface.mode in ('quad', 'deskview')
        if plane and self.kind != 'pen' and surface.mode == 'quad':
            plane = np.ptp(surface.points[:, 1]) > .08 * np.ptp(surface.points[:, 0])
        uv = surface.map(point) if surface is not None and (plane or self.kind == 'hand' and s.hand_control == 'touchpad' or self.kind == 'pen' and s.pen_relative) else point
        return np.array([uv[0], -uv[1] if plane else -sample['log_scale']])

    def solve(self):
        d, s = self.data, self.settings
        patch, pen_patch, notes = {}, {}, []
        inferred = None
        self.pen_surface = self.pen_contact = self.inferred_surface = None
        if self.kind == 'hand' and s.hand_control == 'touchpad' and all(k in d for k in ('touch', 'lift')):
            a, b = values(d['touch'], 'touch'), values(d['lift'], 'touch')
            touch, lift = np.quantile(a, .1), np.quantile(b, .9)
            if touch - lift < .08:
                raise CalibrationError('검지 접촉과 떼기가 구분되지 않습니다. 들어 올리는 높이/카메라 각도를 바꾸고 다시 측정하세요.', 'lift')
            height = float((touch + lift) * .5) * (-1 if self.overhead else 1)
            if not -1 <= height <= 1:
                raise CalibrationError('접촉 자세가 허용 범위를 벗어납니다. 손가락 자세를 조정하세요.', 'touch')
            patch['touch_height'] = round(height, 4)
            contact_level = float((touch + lift) * .5)
            for key in ('right', 'left', 'near', 'far', 'click', 'right_click', 'scroll'):
                if key in d and np.mean(values(d[key], 'touch') >= contact_level) < .8:
                    raise CalibrationError('검지를 책상에 댄 상태가 충분히 확인되지 않았습니다. 접촉을 유지하고 다시 측정하세요.', key)
            if 'scroll' in d and np.mean(values(d['scroll'], 'middle_touch') >= contact_level) < .8:
                raise CalibrationError('스크롤에는 검지와 중지를 모두 책상에 대야 합니다. 두 손가락을 대고 다시 측정하세요.', 'scroll')
            if self.surface is None and all(k in d for k in ('right', 'left')):
                x = np.concatenate([values(d[k], 'x') for k in ('right', 'left')])
                lo, hi = np.quantile(x, [.03, .97])
                y = float(np.median(values(d['touch'], 'y')))
                inferred = TouchSurface.line([[max(0., lo - .05), y], [min(1., hi + .05), y]])
                self.inferred_surface = inferred
                notes.append('검지 접촉 위치와 좌우 움직임으로 책상 기준선을 생성했습니다.')
            elif self.surface is not None and self.surface.mode == 'line':
                inferred = TouchSurface.line(self.surface.points.tolist())
                self.inferred_surface = inferred
            if inferred is not None and any(k in d for k in ('right', 'left', 'near', 'far')):
                moved = sum((d[k] for k in ('right', 'left', 'near', 'far') if k in d), [])
                points = np.array([[a['x'], a['y']] for a in moved])
                inferred.contact_bounds = np.clip(np.quantile(points, [.01, .99], axis=0) + [[-.035, -.035], [.035, .035]], 0, 1)
                notes.append('실제로 접촉하며 이동한 범위를 책상 허용 영역으로 반영했습니다.')
        surface = inferred or self.surface
        plane = surface is not None and surface.mode in ('quad', 'deskview')
        movement_ready = all(k in d for k in ('rest', 'right', 'left', 'near', 'far'))
        if movement_ready:
            signals = {key: np.array([self._signal(a, surface) for a in d[key]]) for key in ('rest', 'right', 'left', 'near', 'far')}
            def travel(key, axis):
                a = signals[key][:, axis]
                n = max(2, len(a) // 5)
                return float(np.median(a[-n:]) - np.median(a[:n]))
            right, left, near, far = travel('right', 0), travel('left', 0), travel('near', 1), travel('far', 1)
            if right * left >= 0:
                raise CalibrationError('좌우 두 검사에서 같은 방향이 관측됐습니다. 왼쪽 안내대로 다시 움직이세요.', 'left')
            if abs(near) < .025 or abs(far) < .025 or near * far >= 0:
                raise CalibrationError('반대 방향 움직임이 부족합니다. 현재 위치에서 반대쪽으로 조금 더 움직여 주세요.', 'far')
            patch['mirror'], patch['invert_y'] = right < 0, near > 0
            amplitude = float(np.median([abs(right), abs(left)]))
            y_amplitude = float(np.median([abs(near), abs(far)]))
            jitter = max(noise(d['rest'], 'x'), noise(d['rest'], 'log_scale'))
            patch['smoothing'] = clip(3 / (1 + 150 * jitter), .3, 4)
            sensitivity = clip(.25 / amplitude, .2, 6)
            plane = surface is not None and surface.mode in ('quad', 'deskview')
            if self.kind == 'pen':
                pen_patch.update(tip_min_cutoff=clip(3.5 / (1 + jitter * 120), .3, 8), tip_beta=clip(1 + amplitude * 5, .5, 3))
            if self.kind == 'pen' and s.pen_relative:
                patch.update(pen_sensitivity=sensitivity, pen_depth_blend=0. if plane else 1.,
                             pen_depth_gain=clip(.25 / (sensitivity * y_amplitude), .2, 5), pen_deadzone=clip(jitter * 2.5, .0005, .02))
            elif self.kind == 'hand' and s.hand_control == 'touchpad':
                patch.update(touch_sensitivity=sensitivity, touch_depth_blend=0. if plane else 1.,
                             touch_deadzone=clip(jitter * 2.5, .001, .025),
                             touch_depth_gain=clip(.25 / (sensitivity * y_amplitude), .2, 5))
            elif not self.absolute:
                patch.update(depth_sensitivity=sensitivity, depth_gain=clip(.25 / (sensitivity * y_amplitude), .2, 5),
                             depth_deadzone=clip(jitter * 2.5, .0005, .02))
            else:
                x = np.concatenate([values(d[k], 'x') for k in ('left', 'right')])
                y = np.concatenate([values(d[k], 'y') for k in ('near', 'far')])
                x0, x1 = np.quantile(x, [.03, .97]); y0, y1 = np.quantile(y, [.03, .97])
                if x1 - x0 < .1 or y1 - y0 < .1:
                    raise CalibrationError('움직인 범위가 좁습니다. 위아래로 조금 더 넓게 움직여 주세요.', 'far')
                patch['hand_region' if self.kind == 'hand' else 'object_region'] = [clip(x0 - .02, 0, .9), clip(y0 - .02, 0, .9), clip(x1 + .02, .1, 1), clip(y1 + .02, .1, 1)]
        else:
            notes.append('이동 검사 일부를 건너뛰어 이동 방향·감도·범위 설정은 기존 값을 유지합니다.')
        click_key = 'gesture_click' if self.kind == 'pen' else 'click'
        if self.finger_style and all(k in d for k in ('rest', 'click', 'right_click')):
            lows, gaps = [], []
            for step, other, name in (('click', 'h_index', 'h_middle'), ('right_click', 'h_middle', 'h_index')):
                ref = {k: max(float(np.median(values(d['rest'], k))), 1e-3) for k in ('h_index', 'h_middle')}
                if ref[name] < MIN_RAISED:
                    raise CalibrationError('손가락이 충분히 들려 있지 않습니다. 검지·중지를 곧게 들고 다시 측정하세요.', 'rest')
                ratio = values(d[step], name) / ref[name]
                low = ratio < FINGER_PRESS
                if low.sum() < 4:
                    raise CalibrationError('손가락이 충분히 내려가지 않았습니다. 더 아래까지 내렸다 올리세요.', step)
                if cycles(ratio, FINGER_PRESS, FINGER_PRESS + .15) < 2:
                    raise CalibrationError('내렸다 올리는 동작 2회 이상을 관측해야 합니다. 천천히 3번 반복하세요.', step)
                lows.append(float(np.quantile(ratio[low], .8)))
                # 클릭 손가락만 내려가야 한다 (다른 손가락도 같이 내려가면 두 버튼을 구분할 수 없다)
                partner = values(d[step], other)[low] / ref[other]
                if np.mean(partner > ratio[low] + .15) < .6:
                    raise CalibrationError('클릭하지 않는 손가락도 같이 내려갔습니다. 한 손가락만 내리세요.', step)
                if self.kind == 'object':
                    gap = values(d[step], 'gap' + name[1:])[low]
                    if float(np.median(gap)) > .6:
                        raise CalibrationError('손가락 끝이 물체에 닿는 것을 확인하지 못했습니다. 물체 위까지 내려 다시 측정하세요.', step)
                    gaps.append(float(np.quantile(gap, .9)))
            down = max(lows)
            press = clip(down + (1 - down) * .45, .3, .85)
            if down >= press - .05:
                raise CalibrationError('내린 높이와 든 높이의 차이가 작습니다. 더 크게 내렸다 올리세요.', 'click')
            patch['finger_press'] = press
            if gaps:
                patch['object_tap_distance'] = clip(max(gaps) + .08, .05, .4)
        elif self.needs_hands and not self.finger_style and all(k in d for k in ('rest', click_key, 'right_click')):
            open_min = min(float(np.quantile(values(d['rest'], key), .1)) for key in ('pinch', 'middle'))
            closed = []
            for step, field in [(click_key, 'pinch'), ('right_click', 'middle')]:
                a = values(d[step], field)
                low = a[a < open_min * .65]
                if len(low) < 4:
                    raise CalibrationError('집기와 놓기를 구분할 수 없습니다. 손가락 끝을 맞댔다 완전히 펴세요.', step)
                closed.append(float(np.quantile(low, .8)))
            on = clip((max(closed) + open_min / 1.5) * .5, .15, .5)
            if max(closed) >= on or open_min <= on * 1.5:
                raise CalibrationError('집기와 놓기의 거리 차이가 작습니다. 손을 더 펴고 다시 측정하세요.', click_key)
            for step, field in [(click_key, 'pinch'), ('right_click', 'middle')]:
                if cycles(values(d[step], field), on, on * 1.5) < 2:
                    raise CalibrationError('클릭 후 놓기까지 2회 이상 관측해야 합니다. 천천히 3번 반복하세요.', step)
            right_samples = [a for a in d['right_click'] if a['middle'] < on]
            if np.mean([a['pinch'] > 1.3 * a['middle'] for a in right_samples]) < .8:
                raise CalibrationError('오른쪽 클릭 때 검지도 붙어 있습니다. 검지를 중지에서 떨어뜨리세요.', 'right_click')
            patch['pinch_on'] = on
        if self.needs_hands and not self.finger_style and 'scroll' in d:
            scroll = [a for a in d['scroll'] if a['scroll_pose']]
            if self.kind == 'hand' and s.hand_control == 'touchpad':
                signal = [-float(surface.map(np.array([a['scroll_x'], a['scroll_y']]))[1]) if plane else
                          -a['log_knuckle'] * patch.get('touch_depth_gain', s.touch_depth_gain) for a in scroll]
                n = max(2, len(signal) // 5)
                motion = float(np.median(signal[-n:]) - np.median(signal[:n]))
            else:
                motion = delta(scroll, 'scroll')
            if abs(motion) < .04:
                raise CalibrationError('스크롤 입력의 이동 차이가 부족합니다. 안내 자세로 더 크게 움직이세요.', 'scroll')
            patch.update(scroll_gain=clip(6 / abs(motion), 1, 100), invert_scroll=motion < 0)
        pen_keys = ('touch_near', 'touch_far', 'touch_side', 'lift_near', 'lift_far', 'click')
        if self.kind == 'pen' and all(k in d for k in pen_keys):
            self._solve_pen(pen_patch)
            if not self.overhead:
                notes.append('접촉 높이와 그리기 원근은 별개입니다. 원근은 기존 소실선/책상 4점 보정을 유지합니다.')
        self.settings.__class__.model_validate({**s.model_dump(), **patch})
        if self.skipped:
            titles = [step.title for step in self.steps if step.key in self.skipped]
            notes.append('건너뛴 검사: ' + ', '.join(titles))
            notes.append('필요한 검사가 빠진 설정은 자동으로 변경하지 않습니다. 기존 설정과 수동 슬라이더를 유지합니다.')
        else:
            notes.append('이동·정지·작은 이동 후 복귀 및 안내된 클릭 검사를 완료했습니다.')
        summary = []
        if 'mirror' in patch:
            summary += [f'방향: 좌우 {"반전" if patch["mirror"] else "유지"} · 상하 {"반전" if patch["invert_y"] else "유지"}',
                        f'이동 감도 {sensitivity:.2f} · 부드러움 {patch["smoothing"]:.2f}']
        if 'pinch_on' in patch:
            summary.append(f'집기 문턱 {patch["pinch_on"]:.2f}')
        if 'scroll_gain' in patch:
            summary.append(f'스크롤 감도 {patch["scroll_gain"]:.1f}')
        if 'finger_press' in patch:
            summary.append(f'클릭 판정: 든 높이의 {patch["finger_press"]:.2f} 이하로 내리면 누름')
        if 'object_tap_distance' in patch:
            summary.append(f'물체 접촉 거리 {patch["object_tap_distance"]:.2f}')
        if 'touch_on' in pen_patch:
            summary.append(f'펜 접촉 {pen_patch["touch_on"]:.2f} · 떼기 {pen_patch["touch_off"]:.2f}')
        if not summary:
            summary.append('자동으로 변경할 설정이 없습니다. 기존 설정을 유지합니다.')
        return {'mouse': patch, 'pen': pen_patch, 'notes': notes,
                'metrics': {'jitter': round(jitter, 5), 'x_motion': round(amplitude, 4), 'y_motion': round(y_amplitude, 4)} if movement_ready else {},
                'summary': summary}

    def _solve_pen(self, patch):
        d = self.data
        touch = sum((d[key] for key in ('touch_near', 'touch_far', 'touch_side')), [])
        lift = d['lift_near'] + d['lift_far']
        if self.overhead:
            model = OverheadContact()
            def pair(a):
                return np.array([a['x'], a['y']]), OverheadContact.feature(a['width'], a['length'], a['sharp'])
            model.touch.extend(pair(a) for a in touch[::2])
            model.lift.extend(pair(a) for a in lift[::2])
            if not model.ready:
                raise CalibrationError('Desk View에서 닿음과 떼기의 외형 차이가 작습니다. 펜을 더 높이 들거나 구도를 바꾸세요.', 'lift_near')
            def scores(samples):
                out = []
                for a in samples:
                    model.recent.clear(); model.recent.append(pair(a))
                    value = model.classify()
                    if value is None:
                        raise CalibrationError('외형 변화가 커 접촉 판단이 불안정합니다. 같은 기울기로 다시 측정하세요.', 'lift_near')
                    out.append(value)
                return np.array(out)
            a, b = scores(touch[1::2]), scores(lift[1::2])
            low, high = float(np.quantile(a, .1)), float(np.quantile(b, .9))
            margin = clip(low * .5, .02, .6)
            if low < .1 or high > -.05 or np.mean(a > margin) < .9 or np.mean(b < -.05) < .9:
                raise CalibrationError('닿음·떼기의 검사 샘플이 겹칩니다. 높이를 충분히 나누어 다시 측정하세요.', 'lift_near')
            patch['desk_contact_margin'] = margin
            self.pen_contact = model
            click = scores(d['click'])
            if cycles(-click, -margin, .05) < 2:
                raise CalibrationError('펜을 댔다 떼는 클릭 2회 이상이 필요합니다. 천천히 3번 반복하세요.', 'click')
        else:
            model = SurfaceModel()
            centers = [(float(np.median(values(d[k], 'width'))), float(np.median(values(d[k], 'raw_y')))) for k in ('touch_near', 'touch_far', 'touch_side')]
            widths = np.array([a[0] for a in centers])
            if np.ptp(widths) < .15 * np.median(widths) or not model.calibrate(centers):
                raise CalibrationError('가까운 곳과 먼 곳의 거리 차이가 부족하거나 책상 기울기를 구분할 수 없습니다.', 'touch_far')
            def heights(samples):
                return np.array([model.height(a['width'], a['raw_y']) / max(a['width'], 2) for a in samples])
            a, b = heights(touch), heights(lift)
            high, low = float(np.quantile(a, .95)), float(np.quantile(b, .1))
            if low - high < .2 or high > .8:
                raise CalibrationError('펜 닿음·떼기의 높이 차이가 불명확합니다. 같은 기울기에서 더 충분히 들어 올리세요.', 'lift_near')
            on = clip(high + .25 * (low - high), .1, 3)
            off = clip(max(on * 1.3, high + .65 * (low - high)), .15, 4)
            if on <= high or off >= low:
                raise CalibrationError('접촉 문턱을 안전하게 나눌 수 없습니다. 펜을 더 높이 들어 측정하세요.', 'lift_near')
            patch.update(touch_on=on, touch_off=off)
            # 굵기 측정 편향이 들어간 접촉 모델의 절편은 광학적 소실선이 아니다.
            # 기존 소실선/4점 책상 투영을 유지하고 접촉 판정만 보정한다.
            self.pen_surface = model
            if cycles(heights(d['click']), on, off) < 2:
                raise CalibrationError('펜을 댔다 떼는 클릭 2회 이상이 필요합니다. 천천히 3번 반복하세요.', 'click')
