"""엔진 프로세서: 등록된 물체들을 추적하고 축 값을 만든다.

엔진 스레드에서만 호출된다 (process 와 명령 모두). 등록 분할은 무거우므로
서버가 GPU 스레드에서 먼저 돌린 뒤 결과(Registration)만 여기로 넘긴다.
"""

from __future__ import annotations

import itertools
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .capture import Frame
from .auto_calibration import AutoCalibration
from .hands.detector import CONNECTIONS as HAND_CONNECTIONS
from .hands.detector import HandFrame, HandWorker, available_backends, default_backend
from .hands.detector import available as hands_available
from .hands.drawing import HandDrawing
from .hands.gestures import GestureRecognizer, features
from .io.depth import palm_scale
from .io.mouse import MouseController, MouseSettings
from .io.touchpad import TouchSurface
from .io.sink import VirtualSink
from .io.macos import DualSink, RealOutput
from .mapping.engine import InputSnapshot, MappingEngine, ObjectSnap
from .mapping.learn import AxisLearner
from .mapping.schema import Profile
from .mapping.schema import warnings as profile_warnings
from .pen import PenTracker
from .tracking.api import Box, InitPrompt, Tracker, TrackOutput, TrackState
from .tracking.axes import AxisState
from .tracking.desk import DeskAxes, DeskCalibration, mask_foot
from .tracking.measure import mask_contour, measure_mask
from .tracking.register import Registration

log = logging.getLogger(__name__)

PALETTE = ["#4cc9f0", "#f72585", "#b5e48c", "#ffb703", "#9d4edd", "#fb8500"]
MAX_OBJECTS = 6
MOUSE_SPEED = 0.8     # 매핑 move_x/move_y = 1 일 때 초당 화면 비율
SCROLL_SPEED = 20.0   # 매핑 scroll = 1 일 때 초당 줄 수
# 물체 마우스 + 종이(책상 4점) 보정: 커서 기준점 = '부드러운 추적 포즈 + 천천히 따라가는 닿은 점 오프셋'.
# 오프셋은 매 프레임 마스크로 잰 닿은 점과의 차이를 FOOT_ALPHA 만큼 따라가되, 한 번에 반영하는 차이는 등록 크기의
# FOOT_CLIP 까지로 자른다 (Huber 식). 마스크 가장자리 떨림·손 가림으로 튄 값은 거의 반영되지 않는다.
FOOT_ALPHA = 0.1
FOOT_CLIP = 0.03
FOOT_WARMUP = 5


@dataclass
class TrackedObject:
    id: int
    name: str
    color: str
    reg: Registration
    prompt: dict[str, Any]
    axes: AxisState
    size0: float
    out: TrackOutput
    contour: list[list[float]] = field(default_factory=list)
    kind: str = "object"  # object | pen
    desk_axes: DeskAxes = field(default_factory=DeskAxes)
    foot_off: np.ndarray | None = None  # 닿은 점 - 포즈 중심 (물체 자신의 좌표: 회전을 풀고 배율로 나눔)
    foot_warm: list = field(default_factory=list)  # 처음 FOOT_WARMUP 개의 오프셋 (중앙값 시작점)


class VisionProcessor:
    def __init__(self, tracker_factory: Callable[[], Tracker] | None = None,
                 hand_worker: HandWorker | None = None, real: RealOutput | None = None) -> None:
        self.tracker_factory = tracker_factory
        self.tracker: Tracker | None = tracker_factory() if tracker_factory else None
        self.objects: dict[int, TrackedObject] = {}
        self._ids = itertools.count(1)
        self.generation = 0  # 비동기 등록 결과가 다른 소스에 들어가지 않게 한다.
        self.latest: Frame | None = None
        self.frame_size: tuple[int, int] | None = None
        self.real = real if real is not None else RealOutput()
        self.sink = DualSink(VirtualSink(), self.real)
        self.input_mirror = True
        self.mouse = MouseController(self.sink)
        self.mouse.input_mirror = self.input_mirror
        self.hands = hand_worker if hand_worker is not None else (HandWorker(default_backend()) if hands_available() else None)
        self.pens: dict[int, PenTracker] = {}
        self.hand_drawing = HandDrawing()
        self.hand_drawing.mirror = self.input_mirror
        # 매핑: observe = 값만 계산해 보여 줌, send = 가상 컨트롤러로 내보냄
        self.mapping = MappingEngine()
        self.output_mode = "observe"
        self.map_gestures = GestureRecognizer()
        self.learner: AxisLearner | None = None
        self._t_prev: float | None = None
        self.desk: DeskCalibration | None = None
        self.hand_occlusion = False  # 손 인식 가림 처리 (켜면 손 추적이 항상 돈다: CPU 약 30ms/프레임, 별도 스레드)
        self.desk_view = False
        self._paused = False
        self.auto_calibration: AutoCalibration | None = None

    def set_view_mode(self, desk_view: bool) -> None:
        self.desk_view = desk_view
        self.mouse.desk_view = desk_view
        self.mouse.set_surface(TouchSurface.overhead() if desk_view else None)

    # ---------------------------------------------------------------- Processor
    def reset(self) -> None:
        """소스가 바뀌면 추적 상태를 모두 비운다 (다른 장면이므로)."""
        self.cancel_auto_calibration('소스가 바뀌어 보정을 종료했습니다.')
        self.real.off("source")
        self.generation += 1
        self.objects.clear()
        self.pens.clear()
        self.hand_drawing.reset()
        if self.hands is not None and self.hands.running:
            self.hands.stop()  # 이전 소스의 손 관측을 새 그림에 사용하지 않는다.
        refresh_enabled = getattr(self.tracker, "refresh_enabled", None)
        refresh_hz = getattr(getattr(self.tracker, "cfg", None), "refresh_hz", .5)
        close = getattr(self.tracker, "close", None)
        if close is not None:
            close()
        self.tracker = self.tracker_factory() if self.tracker_factory else None
        if refresh_enabled is not None and hasattr(self.tracker, "configure_refresh"):
            self.tracker.configure_refresh(refresh_enabled, refresh_hz)
        self.latest = None
        self.frame_size = None
        self._t_prev = None
        self._paused = False
        self.learner = None
        self.desk = None  # 다른 장면·카메라면 보정도 무효
        self.desk_view = False
        self.mouse.desk_view = False
        self.mouse.set_surface(None)
        if self.mouse.settings.mode == "object":
            self.mouse.configure(self.mouse.settings.model_copy(update={"mode": "off", "object_id": None}))
        self.mapping.reset()
        self.sink.release_all()

    def close(self) -> None:
        """엔진 스레드에서 종료한다. 모델 워커와 눌린 입력을 남기지 않는다."""
        self.emergency_stop()
        self.real.close()
        if self.hands is not None:
            self.hands.stop()
        close = getattr(self.tracker, "close", None)
        if close is not None:
            close()

    def enable_real(self) -> None:
        if not self.real.info(time.monotonic())["trusted"]:
            raise PermissionError("손쉬운 사용 권한이 필요합니다")
        if self._paused or self.latest is None or time.monotonic() - self.latest.t_capture > .5:
            raise ValueError("영상을 켜고 재생한 뒤 실제 출력을 켜세요.")
        if self.auto_calibration and self.auto_calibration.active:
            raise ValueError("자동 보정을 마친 뒤 실제 출력을 켜세요.")
        self.real.request_on(time.monotonic())
        self.real.start_monitor()

    def set_input_mirror(self, enabled: bool) -> None:
        if enabled == self.input_mirror:
            return
        self.cancel_auto_calibration('입력 방향이 바뀌어 보정을 종료했습니다.')
        self._reset_auto_input()
        self.input_mirror = enabled
        self.mouse.input_mirror = enabled
        self.hand_drawing.mirror = enabled
        for pen in self.pens.values():
            pen.mirror = enabled

    def process(self, frame: Frame) -> dict[str, Any] | None:
        self.real.last_frame = time.monotonic()
        if self.real.stopped_by == "escape":
            self.emergency_stop()
            self.real.stopped_by = "escape_handled"
        if self._paused:
            resume = getattr(self.tracker, "resume", None)
            if resume is not None:
                resume(frame.t_capture)
            self._paused = False
            self._t_prev = None
        self.latest = frame
        self.frame_size = frame.size
        hf = self._hands(frame)  # 직전까지 처리된 손 (별도 스레드, 최대 수십 ms 늦음)
        if self.tracker is not None and self.objects:
            setter = getattr(self.tracker, "set_occluders", None)
            if setter is not None:
                setter(hand_mask(hf, frame.size) if self.hand_occlusion and hf is not None and 0 <= frame.t_capture - hf.t < 0.15 else None)
            outs = self.tracker.step(frame.image, frame.t_capture)
            for oid, out in outs.items():
                obj = self.objects.get(oid)
                if obj is not None:
                    self._apply(obj, out)
        for oid, pen in self.pens.items():
            pen.suspended = bool(self.auto_calibration and self.auto_calibration.active)
            obj = self.objects.get(oid)
            if obj is not None:
                pen.mirror = self.input_mirror
                pen.update(frame.image, obj.out, frame.t_capture, self.desk, overhead=self.desk_view)
        t = frame.t_capture
        if self.auto_calibration is not None and self.auto_calibration.active:
            self.auto_calibration.observe(self._auto_sample(hf, t), t)
            self.sink.release_all()
            return {**self.state(), "mouse": {"mode": self.mouse.settings.mode, "cursor_active": False, **self.sink.snapshot()},
                    "controller": {"mode": "observe", **self.sink.controller_snapshot()},
                    "pens": {oid: p.state() for oid, p in self.pens.items()},
                    "hand_drawing": self.hand_drawing.state()}
        self.hand_drawing.update(hf, t, self.mouse.settings.pinch_on)
        dt = 1 / 30 if self._t_prev is None else min(0.2, max(1e-3, t - self._t_prev))
        self._t_prev = t
        ctl = self.mapping.update(self._snapshot(t, hf))
        send = self.output_mode == "send"
        if self.learner is not None:
            obj = self.objects.get(self.learner.object_id)
            if obj is not None and obj.out.state.visible:
                self.learner.add(self._axes(obj))
        center, visible = self._mouse_object()
        mouse_obj = self.objects.get(self.mouse.settings.object_id or -1)
        if mouse_obj is not None and mouse_obj.out.debug.get("reanchored"):
            self.mouse.depth_cursor.reset()
            self.mouse.pen_last = None
        mouse_box = None
        if visible and mouse_obj is not None and mouse_obj.out.box is not None:
            w, h = self.frame_size or (1, 1)
            x0, y0, x1, y1 = mouse_obj.out.box
            mouse_box = (x0 / w, y0 / h, x1 / w, y1 / h)
        mouse_foot = None
        if visible and mouse_obj is not None and mouse_obj.kind != "pen":
            foot = self._foot_px(mouse_obj)
            if foot is not None:
                w, h = self.frame_size or (1, 1)
                mouse_foot = (foot[0] / w, foot[1] / h)
        pen = self.pens.get(self.mouse.settings.object_id or -1)
        pen_scale = pen.width if pen is not None and np.isfinite(pen.width) else (
            self.objects[self.mouse.settings.object_id].out.pose.scale
            if self.mouse.settings.object_id in self.objects and
            self.objects[self.mouse.settings.object_id].out.pose is not None else 1.0)
        self.mouse.update(t, hf, center, visible, bool(pen and pen.contact and not pen.uncertain),
                          ctl.mouse_buttons if send else None,
                          obj_is_pen=pen is not None, obj_scale=float(pen_scale), obj_box=mouse_box,
                          obj_foot=mouse_foot)
        if send:
            self.sink.gamepad(ctl.axes, ctl.buttons)
            self.sink.set_keys(ctl.keys)
            mx, my = ctl.mouse_move
            if mx or my:
                self.sink.move_by(mx * MOUSE_SPEED * dt, my * MOUSE_SPEED * dt)
            if ctl.mouse_scroll:
                self.sink.scroll(ctl.mouse_scroll * SCROLL_SPEED * dt)
        st = self.state()
        st["mouse"] = {**self.mouse.status, **self.sink.snapshot()}
        st["controller"] = {"mode": self.output_mode, **self.sink.controller_snapshot()}
        st["hand_drawing"] = {**self.hand_drawing.state(),
                              "error": None if self.hands is None else self.hands.error}
        if self.mapping.profile.mappings:
            st["mapping"] = {"live": self.mapping.live_json(), "computed": ctl.to_json()}
        if hf is not None and self.hands is not None and self.hands.running:
            st["hands"] = [{"points": np.round(h.points, 4).tolist(), "handedness": h.handedness,
                            "score": round(h.score, 3)} for h in hf.hands]
        if self.pens:
            st["pens"] = {oid: p.state() for oid, p in self.pens.items()}
        return st

    # ---------------------------------------------------------------- 매핑
    def _axes(self, obj: TrackedObject) -> dict[str, float | None]:
        values = {**obj.axes.values(), **obj.axes.desk_values()}
        if self.input_mirror:
            for key in ("x", "angle", "desk_x", "desk_yaw"):
                if values.get(key) is not None:
                    values[key] = -values[key]
        return values

    # ---------------------------------------------------------------- 책상 보정
    def set_calibration(self, pts_norm: list[list[float]], width_m: float, depth_m: float) -> dict[str, Any]:
        self.cancel_auto_calibration('책상 보정이 바뀌었습니다. 새 구도에서 자동 보정을 다시 시작하세요.')
        if self.frame_size is None:
            raise ValueError("아직 카메라 프레임이 없습니다")
        w, h = self.frame_size
        pts = np.array([[p[0] * w, p[1] * h] for p in pts_norm])
        surface = TouchSurface.quad(pts_norm)
        desk = DeskCalibration.from_points(pts, (w, h), width_m, depth_m)
        self.desk = desk
        self.mouse.set_surface(surface)
        for pen in self.pens.values():
            pen.lift()
            pen.clear()
        for o in self.objects.values():
            o.axes.clear_desk()
            o.desk_axes = DeskAxes()
        return self.calibration_info()

    def clear_calibration(self) -> None:
        self.cancel_auto_calibration('책상 보정이 해제되어 자동 보정을 종료했습니다.')
        self.desk = None
        self.mouse.set_surface(TouchSurface.overhead() if self.desk_view else None)
        for pen in self.pens.values():
            pen.lift()
            pen.clear()
        for o in self.objects.values():
            o.axes.clear_desk()

    def set_touchpad_line(self, points: list[list[float]]) -> dict[str, Any]:
        self.cancel_auto_calibration('책상 기준선이 바뀌었습니다. 새 구도에서 자동 보정을 다시 시작하세요.')
        if self.frame_size is None:
            raise ValueError("아직 카메라 프레임이 없습니다")
        surface = TouchSurface.line(points)
        self.desk = None
        for o in self.objects.values():
            o.axes.clear_desk()
        self.mouse.set_surface(surface)
        for pen in self.pens.values():
            pen.lift()
            pen.clear()
        return self.calibration_info()

    def calibration_info(self) -> dict[str, Any]:
        surface = self.mouse.touch_surface
        return {"calibrated": surface is not None,
                "mode": None if surface is None else surface.mode,
                "line": surface.points.tolist() if surface is not None and surface.mode == "line" else None,
                **(self.desk.info() if self.desk else {})}

    def _snapshot(self, t: float, hf: HandFrame | None) -> InputSnapshot:
        objs = [ObjectSnap(o.id, o.name, o.out.state.visible, self._axes(o),
                           (self.pens[o.id].contact and not self.pens[o.id].uncertain) if o.id in self.pens else None) for o in self.objects.values()]
        hand = None
        if self.mapping.needs_hands and hf is not None and t - hf.t < 0.3:
            best = max(hf.hands, key=lambda h: h.score, default=None)
            g = self.map_gestures.update(best, t)
            hand = {"pinch": g.left, "pinch_middle": g.right} if best is not None else None
        return InputSnapshot(t, objs, hand)

    def set_profile(self, p: Profile) -> dict[str, Any]:
        self.sink.release_all()  # 바뀐 매핑에 없는 키가 눌린 채로 남지 않게
        self.mapping.set_profile(p)
        if self.hands is None and self.mapping.needs_hands:
            log.warning("profile uses hand gestures but hand model is unavailable")
        return self.mapping_info()

    def set_output_mode(self, mode: str) -> dict[str, Any]:
        if mode not in ("observe", "send"):
            raise ValueError("mode must be observe or send")
        if mode != self.output_mode:
            self.sink.release_all()  # 전환할 때 눌린 채로 남지 않게
            self.mapping.reset()
        self.output_mode = mode
        return self.mapping_info()

    def mapping_info(self) -> dict[str, Any]:
        names = [o.name for o in self.objects.values()]
        return {"profile": self.mapping.profile.model_dump(mode="json"), "mode": self.output_mode,
                "warnings": profile_warnings(self.mapping.profile, names),
                "hands_available": self.hands is not None}

    def learn_start(self, oid: int) -> None:
        if oid not in self.objects:
            raise KeyError(oid)
        self.learner = AxisLearner(oid)

    def learn_stop(self) -> dict[str, Any]:
        lr, self.learner = self.learner, None
        if lr is None:
            raise LookupError("learning not started")
        sug = lr.suggest()
        return {"object_id": lr.object_id, "frames": lr.frames,
                "suggestions": [s.__dict__ for s in sug]}

    def _hands(self, frame: Frame) -> HandFrame | None:
        if self.hands is None:
            return None
        if (self.mouse.settings.needs_hands or self.mapping.needs_hands or self.hand_drawing.enabled
                or (self.hand_occlusion and self.objects) or (self.auto_calibration and self.auto_calibration.active and self.auto_calibration.needs_hands)):
            self.hands.start()
            self.hands.offer(frame.image, frame.t_capture)
            return self.hands.latest()
        if self.hands.running:
            self.hands.stop()
        return None

    def _mouse_object(self) -> tuple[tuple[float, float] | None, bool]:
        s = self.mouse.settings
        if s.mode != "object" or s.object_id is None:
            return None, False
        obj = self.objects.get(s.object_id)
        w, h = self.frame_size or (1, 1)
        if obj is None:
            return None, False
        pen = self.pens.get(obj.id)
        if pen is not None:  # 펜촉을 놓쳤을 때 몸통 중심으로 커서가 바뀌지 않게 한다
            if pen.tip is None or pen.uncertain:
                return None, False
            return (pen.tip[0] / w, pen.tip[1] / h), obj.out.state.visible
        if obj.out.pose is None:
            return None, False
        return (obj.out.pose.cx / w, obj.out.pose.cy / h), obj.out.state.visible

    def set_mouse(self, settings: MouseSettings) -> dict[str, Any]:
        if self.auto_calibration and self.auto_calibration.active:
            raise ValueError("자동 보정을 마치거나 취소한 뒤 수동 설정을 변경하세요.")
        if settings.mode == "object" and settings.object_id not in self.objects:
            raise ValueError("물체 마우스로 쓸 물체를 먼저 등록하고 선택하세요.")
        if settings.needs_hands and self.hands is None:
            raise ValueError("손 인식 엔진이 없어 이 모드를 쓸 수 없습니다 (Apple Vision 또는 MediaPipe).")
        self.mouse.configure(settings)
        return self.mouse_info()

    def set_hand_backend(self, backend: str) -> None:
        """손 인식 엔진 전환 (vision | mediapipe). 이전 엔진의 누름·제스처 상태가 남지 않게 입력을 놓는다."""
        if self.hands is None:
            raise ValueError("손 인식 엔진이 없습니다 (Apple Vision: pyobjc-framework-Vision, MediaPipe: models/hand_landmarker.task).")
        if backend == self.hands.backend:
            return
        self.hands.set_backend(backend)
        self.sink.release_all()
        self.mouse.gestures.reset()

    def hand_backend_info(self) -> dict[str, Any]:
        return {"hand_backend": None if self.hands is None else self.hands.backend,
                "hand_backends": available_backends()}

    def mouse_info(self) -> dict[str, Any]:
        return {"settings": self.mouse.settings.model_dump(), "status": self.mouse.status, **self.hand_backend_info(),
                "hands_available": self.hands is not None,
                "hands_running": bool(self.hands and self.hands.running),
                "hands_error": None if self.hands is None else self.hands.error}

    def set_hand_drawing(self, enabled: bool) -> dict[str, Any]:
        if enabled and self.hands is None:
            raise ValueError("손 인식 모델이 없어 맨손 그리기를 켤 수 없습니다 (mediapipe, models/hand_landmarker.task).")
        self.hand_drawing.set_enabled(enabled)
        return self.hand_drawing_info()

    def hand_drawing_info(self) -> dict[str, Any]:
        return {"enabled": self.hand_drawing.enabled, "hands_available": self.hands is not None,
                "hands_error": None if self.hands is None else self.hands.error}

    def emergency_stop(self) -> None:
        """마우스 끄기 + 매핑 출력 끄기(observe) + 눌린 것 모두 놓기 + 펜 떼기."""
        self.cancel_auto_calibration('긴급 정지로 자동 보정을 종료했습니다.')
        self.real.off("stop")
        self.mouse.emergency_stop()
        self.hand_drawing.set_enabled(False)
        self.output_mode = "observe"
        self.mapping.reset()
        self.sink.release_all()
        for p in self.pens.values():
            p.manual_contact = None
            p.manual_until = None
            p.lift()

    # ---------------------------------------------------------------- 명령
    def snapshot(self) -> Frame | None:
        return self.latest

    def add(self, frame: Frame, reg: Registration, prompt: dict[str, Any], name: str | None = None,
            pen_line: tuple[tuple[float, float], tuple[float, float]] | None = None) -> TrackedObject:
        if len(self.objects) >= MAX_OBJECTS:
            raise ValueError(f"물체는 최대 {MAX_OBJECTS}개까지 등록할 수 있습니다.")
        oid = next(self._ids)
        w, h = frame.size
        out = TrackOutput(TrackState.TRACKING, reg.measure.box, None, reg.mask, reg.score)
        if self.tracker is not None:
            out = self.tracker.add(frame.image, oid, InitPrompt(box=reg.measure.box, mask=reg.mask,
                                                                kind="pen" if pen_line is not None else "object"))
        obj = TrackedObject(oid, name or f"물체 {oid}", PALETTE[(oid - 1) % len(PALETTE)], reg, prompt,
                            AxisState((w, h)), reg.measure.size, out)
        self._apply(obj, out, force_mask=reg.mask)
        obj.axes.set_neutral()
        self.objects[oid] = obj
        if pen_line is not None:
            self.pens[oid] = PenTracker(pen_line[0], pen_line[1])
            self.pens[oid].overhead = self.desk_view
            obj.kind = "pen"
        return obj

    def reselect(self, oid: int, frame: Frame, reg: Registration, prompt: dict[str, Any],
                 pen_line: tuple[tuple[float, float], tuple[float, float]] | None = None) -> TrackedObject:
        """같은 물체를 현재 프레임에서 다시 분할한 결과로 모양을 다시 기억한다.
        id·이름·색·매핑(이름 기준)·마우스 연결은 그대로. 축 중립은 새 등록 기준으로 옮겨 값이 튀지 않게 한다.
        없는 id 는 KeyError, 빈 마스크는 ValueError 이고 둘 다 아무것도 바꾸지 않는다."""
        obj = self.objects[oid]
        if reg.mask is None or not reg.mask.any():
            raise ValueError("분할 결과가 비어 있습니다. 물체를 다시 지정하세요.")
        if self.auto_calibration and self.auto_calibration.active and self.auto_calibration.object_id == oid:
            self.cancel_auto_calibration('보정 중인 물체를 다시 선택했습니다. 자동 보정을 다시 시작하세요.')
        kind = "pen" if obj.kind == "pen" else "object"
        out = TrackOutput(TrackState.TRACKING, reg.measure.box, None, reg.mask, reg.score)
        if self.tracker is not None:
            reselect = getattr(self.tracker, "reselect", None)
            p = InitPrompt(box=reg.measure.box, mask=reg.mask, kind=kind)
            if reselect is not None:
                out = reselect(frame.image, oid, p)
            else:  # 다시 선택을 모르는 트래커: 같은 id 로 지우고 다시 등록
                self.tracker.remove(oid)
                out = self.tracker.add(frame.image, oid, p)
        before = obj.axes.last
        obj.reg, obj.prompt, obj.size0 = reg, prompt, reg.measure.size
        obj.foot_off, obj.foot_warm = None, []  # 새 모양 기준으로 닿은 점을 다시 잰다
        self._apply(obj, out, force_mask=reg.mask)
        obj.axes.rebase(before, obj.axes.last)
        pen = self.pens.get(oid)
        if pen is not None and pen_line is not None:
            pen.redefine(pen_line[0], pen_line[1])  # 펜촉 방향만 새로 (그림·접촉 보정·설정은 유지)
        if self.mouse.settings.object_id == oid:
            self.mouse.depth_cursor.reset()  # 새 기준점에서 상대 이동을 다시 시작 (커서 점프 방지)
            self.mouse.pen_last = None
        return obj

    def remove(self, oid: int) -> None:
        if self.auto_calibration and self.auto_calibration.active and self.auto_calibration.object_id == oid:
            self.cancel_auto_calibration('보정 중인 물체가 삭제되었습니다.')
        if self.objects.pop(oid, None) is None:
            raise KeyError(oid)
        self.pens.pop(oid, None)
        if self.tracker is not None:
            self.tracker.remove(oid)
        if self.mouse.settings.mode == "object" and self.mouse.settings.object_id == oid:
            self.mouse.configure(self.mouse.settings.model_copy(update={"mode": "off", "object_id": None}))

    def set_neutral(self, oid: int) -> None:
        self.objects[oid].axes.set_neutral()

    def rename(self, oid: int, name: str) -> None:
        self.objects[oid].name = name[:40]

    # ---------------------------------------------------------------- 내부
    def _apply(self, obj: TrackedObject, out: TrackOutput, force_mask: np.ndarray | None = None) -> None:
        obj.out = out
        mask = force_mask if force_mask is not None else out.mask
        meas = measure_mask(mask) if mask is not None and out.state.visible else None
        # 트래커가 있으면 보이는 출력에는 항상 pose 가 있어야 한다 (출처 혼용 방지). 없으면 이번 프레임은 건너뛴다.
        if out.state.visible and (self.tracker is None or out.pose is not None):
            obj.axes.sample(out.pose if self.tracker is not None else None, meas, obj.size0)
        if mask is not None and out.state.visible and self.desk is not None:
            d = obj.desk_axes.measure(self.desk, mask)
            if d is not None:
                obj.axes.sample_desk((d.x, d.z, d.yaw))
        surface = self.mouse.touch_surface
        if mask is not None and out.state.visible and surface is not None and surface.mode == "quad":
            self._update_foot(obj, out, mask)
        if mask is not None and out.state.visible:
            obj.contour = mask_contour(mask, 80)
        elif not out.state.visible:
            obj.contour = []

    @staticmethod
    def _update_foot(obj: TrackedObject, out: TrackOutput, mask: np.ndarray) -> None:
        """마스크로 잰 닿은 점으로 오프셋을 천천히 갱신. 손에 쥔 동안(GRASPED)은 아래가 가려질 수 있어 멈춘다."""
        pose = out.pose
        if pose is None or (out.state == TrackState.GRASPED and obj.foot_off is not None):
            return
        f = mask_foot(mask)
        if f is None:
            return
        a = np.radians(pose.angle)
        c, s = np.cos(a), np.sin(a)
        dx, dy = f[0] - pose.cx, f[1] - pose.cy
        off = np.array([c * dx + s * dy, -s * dx + c * dy]) / max(pose.scale, 1e-6)  # R(-각도)·d / 배율
        if len(obj.foot_warm) < FOOT_WARMUP:
            # 처음 몇 번은 중앙값으로 시작점을 잡는다 (첫 마스크 하나가 튀어도 오래 끌려가지 않게)
            obj.foot_warm.append(off)
            obj.foot_off = np.median(np.array(obj.foot_warm), axis=0)
            return
        d = off - obj.foot_off
        n = float(np.linalg.norm(d))
        lim = FOOT_CLIP * max(obj.size0, 1.0)
        if n > lim:
            d *= lim / n
        obj.foot_off = obj.foot_off + FOOT_ALPHA * d

    @staticmethod
    def _foot_px(obj: TrackedObject) -> tuple[float, float] | None:
        """지금 포즈 기준 닿은 점 (px) = 포즈 중심 + R(각도)·배율·오프셋. 커서의 움직임은 부드러운 포즈에서 온다."""
        pose = obj.out.pose
        if pose is None or obj.foot_off is None:
            return None
        a = np.radians(pose.angle)
        c, s = np.cos(a), np.sin(a)
        ox, oy = obj.foot_off * pose.scale
        return float(pose.cx + c * ox - s * oy), float(pose.cy + s * ox + c * oy)

    def object_info(self, obj: TrackedObject) -> dict[str, Any]:
        w, h = self.frame_size or (1, 1)
        out = obj.out
        box = _norm_box(out.box, w, h)
        return {
            "id": obj.id,
            "kind": obj.kind,
            "name": obj.name,
            "color": obj.color,
            "state": out.state.value,
            "confidence": round(float(out.confidence), 3),
            "box": box,
            "contour": [[round(x / w, 4), round(y / h, 4)] for x, y in obj.contour],
            "axes": self._axes(obj),
            "texture": obj.reg.texture,
            "contrast": obj.reg.contrast,
            "warnings": obj.reg.warnings,
            "candidates": len(obj.reg.candidates),
            "candidate_index": obj.reg.candidate_index,
            "debug": {k: v for k, v in out.debug.items() if isinstance(v, (int, float, str, bool))},
        }

    def set_paused(self, paused: bool) -> None:
        if not paused or self._paused:
            return
        self.real.off("paused")
        self._paused = True
        self.cancel_auto_calibration('영상이 정지되어 자동 보정을 종료했습니다. 재생한 뒤 다시 시작하세요.')
        self.sink.release_all()
        self.mapping.reset()
        self.mouse.gestures.reset()
        self.mouse.touchpad.reset()
        self.mouse.depth_cursor.reset()
        self.mouse.pen_last = None
        self.mouse.last_palm = None
        self.hand_drawing.suspend()
        for pen in self.pens.values():
            pen.manual_contact = pen.manual_until = None
            pen.lift()
        if self.hands is not None and self.hands.running:
            self.hands.stop()

    def process_frozen(self, frame: Frame) -> dict[str, Any]:
        self.latest, self.frame_size = frame, frame.size
        self.set_paused(True)
        return {**self.state(), "paused": True,
                "mouse": {"mode": self.mouse.settings.mode, "gesture": "none", "cursor_active": False,
                          **self.sink.snapshot()},
                "controller": {"mode": self.output_mode, **self.sink.controller_snapshot()},
                "pens": {oid: p.state() for oid, p in self.pens.items()},
                "hand_drawing": self.hand_drawing.state()}

    def state(self) -> dict[str, Any]:
        return {"input_mirror": self.input_mirror, "real": self.real.info(time.monotonic()), "size": self.frame_size, "objects": [self.object_info(o) for o in self.objects.values()],
                "calibration": self.calibration_info(),
                "auto_calibration": None if self.auto_calibration is None else self.auto_calibration.state()}

    def start_auto_calibration(self, kind: str, object_id: int | None = None) -> dict[str, Any]:
        if self.auto_calibration and self.auto_calibration.active:
            raise ValueError('이미 자동 보정 중입니다. 현재 보정을 마치거나 취소하세요.')
        if self.latest is None or self._paused or self.latest.frozen:
            raise ValueError('카메라/영상을 켜고 재생한 뒤 자동 보정을 시작하세요.')
        if kind not in ('hand', 'object', 'pen'):
            raise ValueError('올바른 보정 대상을 선택하세요.')
        obj = self.objects.get(object_id or -1)
        if kind != 'hand' and (obj is None or not obj.out.state.visible or (kind == 'pen') != (obj.kind == 'pen')):
            raise ValueError('보정할 펜/물체를 먼저 등록하고 화면에 보이도록 하세요.')
        settings = self.mouse.settings
        if kind == 'pen' and settings.mode != 'off' and (settings.mode != 'object' or settings.object_id != object_id):
            raise ValueError('펜을 마우스 대상으로 선택하거나 마우스를 끈 뒤 펜 보정을 시작하세요.')
        if (kind == 'hand' or kind == 'object' and settings.hand_clicks or
                kind == 'pen' and settings.mode == 'object' and settings.hand_clicks) and self.hands is None:
            raise ValueError('손 인식 모델이 필요합니다. 물체 이동만 보정하려면 손 클릭을 끄세요.')
        self.real.off("calibration")
        self.auto_calibration = AutoCalibration(kind, object_id, settings, self.mouse.touch_surface, self.desk_view, time.monotonic())
        self._reset_auto_input()
        return self.auto_calibration.state()

    def auto_session(self, session_id: str) -> AutoCalibration:
        session = self.auto_calibration
        if session is None or session.id != session_id or not session.active:
            raise ValueError('자동 보정이 종료되었거나 바뀌었습니다. 현재 상태를 확인하세요.')
        return session

    def _reset_auto_input(self) -> None:
        self.sink.release_all()
        self.mapping.reset()
        self.map_gestures.reset()
        self.mouse._new_cursor()
        self.mouse.gestures.reset()
        self.mouse.object_tap.reset()
        self.mouse.touchpad.reset()
        self.mouse.depth_cursor.reset()
        self.mouse.pen_last = self.mouse.last_palm = None
        self._t_prev = None
        self.hand_drawing.suspend()
        for pen in self.pens.values():
            pen.lift()
            pen.manual_contact = pen.manual_until = None

    def cancel_auto_calibration(self, reason: str | None = None) -> None:
        if self.auto_calibration is not None and self.auto_calibration.active:
            self.auto_calibration.cancel(reason)
            self._reset_auto_input()
        for pen in self.pens.values():
            pen.suspended = False

    def apply_auto_calibration(self, session_id: str) -> dict[str, Any]:
        session = self.auto_session(session_id)
        if session.phase != 'review' or session.result is None:
            raise ValueError('모든 검사를 완료해야 설정을 적용할 수 있습니다.')
        settings = self.mouse.settings.model_copy(update=session.result['mouse'])
        if session.kind == 'hand':
            settings.mode = 'hand'
        elif settings.mode == 'object' and settings.object_id != session.object_id:
            raise ValueError('마우스 대상이 바뀌었습니다. 대상에 맞게 보정을 다시 시작하세요.')
        settings = MouseSettings.model_validate(settings.model_dump())
        if session.kind == 'pen':
            pen = self.pens.get(session.object_id)
            if pen is None:
                raise ValueError('보정한 펜이 삭제되었습니다.')
            from .tracking.smooth import OneEuro
            for key, value in session.result['pen'].items():
                setattr(pen.cfg, key, value)
            if session.pen_surface is not None:
                pen.surface = session.pen_surface
                pen.touch_samples = [(s['width'], s['raw_y']) for k in ('touch_near', 'touch_far', 'touch_side') for s in session.data[k]]
            if session.pen_contact is not None:
                pen.overhead_contact = session.pen_contact
            pen.fx, pen.fy = OneEuro(pen.cfg.tip_min_cutoff, pen.cfg.tip_beta), OneEuro(pen.cfg.tip_min_cutoff, pen.cfg.tip_beta)
        if session.inferred_surface is not None:
            self.mouse.set_surface(session.inferred_surface)
        self.mouse.configure(settings)
        session.phase = 'complete'
        self._reset_auto_input()
        for pen in self.pens.values():
            pen.suspended = False
        return {'calibration': session.state(), 'mouse': self.mouse_info(),
                'pen': None if session.kind != 'pen' else self.pens[session.object_id].state(consume=False)}

    def _auto_sample(self, hf: HandFrame | None, t: float) -> dict[str, Any] | None:
        session = self.auto_calibration
        session.observation_issue = None
        def missing(message):
            session.observation_issue = message
            return None
        sample = {'t': t, 'frame_h': (self.frame_size or (1, 1))[1]}
        obj = self.objects.get(session.object_id or -1)
        box = None
        w, h = self.frame_size or (1, 1)
        if session.kind != 'hand':
            if obj is None or not obj.out.state.visible or obj.out.confidence < .55 or obj.out.debug.get('reanchored'):
                return missing('물체 추적이 불안정합니다. 등록한 대상을 가리지 말고 화면 안에 유지하세요.')
            if obj.out.box is not None:
                box = np.array(obj.out.box).reshape(2, 2) / [w, h]
            if session.kind == 'pen':
                pen = self.pens.get(obj.id)
                if pen is None or pen.uncertain or pen.tip is None or not math.isfinite(pen.width) or 'raw_y' not in pen.debug:
                    return missing('펜촉이 잘 보이지 않습니다. 펜 전체와 끝이 보이도록 구도와 조명을 조정하세요.')
                sample.update(x=pen.debug['raw_x'] / w, y=pen.debug['raw_y'] / h, raw_y=pen.debug['raw_y'],
                              width=pen.width, length=pen.debug.get('len', 1), sharp=pen.debug.get('sharp', 0), log_scale=math.log(max(pen.width, .1)))
            elif obj.out.pose is not None:
                point = np.array([obj.out.pose.cx / w, obj.out.pose.cy / h])
                if box is not None and session.surface is not None and session.surface.mode == 'quad':
                    point = np.array([box[:, 0].mean(), box[1, 1]])
                sample.update(x=float(point[0]), y=float(point[1]), log_scale=math.log(max(obj.out.pose.scale, .01)))
            else:
                return None
        if session.step_needs_hands:
            if hf is None or not 0 <= t - hf.t < .2 or not hf.hands:
                return missing('손을 인식하지 못했습니다. 손바닥과 손가락 전체를 카메라에 보여 주세요.')
            hand = self.mouse._pick_hand([a for a in hf.hands if a.score >= .5], None if obj is None or obj.out.pose is None else (obj.out.pose.cx / w, obj.out.pose.cy / h))
            if hand is None:
                return missing('손을 안정적으로 찾지 못했습니다. 손바닥 방향과 밝기를 조정하세요.')
            f = features(hand, self.mouse.gestures.cfg)
            sample['t'] = hf.t  # 워커 관측을 재사용한 프레임은 중복 학습하지 않는다.
            p = hand.points
            knuckle = max(float(np.linalg.norm(p[5] - p[17])), 1e-4)
            if session.kind == 'hand':
                tip = session.settings.hand_control == 'touchpad'
                point = p[8] if tip else f.palm
                sample.update(t=hf.t, x=float(point[0]), y=float(point[1]), log_scale=math.log(knuckle if tip else palm_scale(hand)))
            touch = .25 - float(hand.depth[6] - hand.depth[8]) / knuckle if self.desk_view else float(p[8, 1] - p[6, 1]) / knuckle
            middle_touch = .25 - float(hand.depth[10] - hand.depth[12]) / knuckle if self.desk_view else float(p[12, 1] - p[10, 1]) / knuckle
            e = f.extended
            sample.update(pinch=f.pinch_index, middle=f.pinch_middle, touch=touch, middle_touch=middle_touch,
                          scroll_pose=e['index'] and e['middle'] and not e['ring'] and not e['pinky'],
                          scroll=float(f.palm[1]) / f.size, scroll_x=float((p[8, 0] + p[12, 0]) / 2),
                          scroll_y=float((p[8, 1] + p[12, 1]) / 2), log_knuckle=math.log(knuckle))
            if session.kind == 'object' and session.settings.object_tap:
                if box is None:
                    return None
                candidates = []
                for hd in hf.hands:
                    size = float(np.linalg.norm(hd.points[5] - hd.points[17]))
                    palm = hd.points[[0, 5, 9, 13, 17]].mean(0)
                    gap = float(np.linalg.norm(palm - np.clip(palm, box[0], box[1])))
                    if hd.score >= .5 and size > .015 and gap <= 1.5 * size:
                        candidates.append((float(np.linalg.norm(palm - box.mean(0))) / size, hd, size))
                if not candidates:
                    if session.steps[session.index].key.startswith('tap_'):
                        return missing('물체를 쥔 손과 검지 끝을 찾지 못했습니다. 구도를 바꿔 재검사하거나 이 검사를 건너뛰세요.')
                    sample['gap'] = 1.
                else:
                    _, hd, size = min(candidates, key=lambda a: a[0])
                    sample['gap'] = float(np.linalg.norm(hd.points[8] - np.clip(hd.points[8], box[0], box[1]))) / size
        return sample


def hand_mask(hf: HandFrame, size: tuple[int, int]) -> np.ndarray | None:
    """손 랜드마크 → 손 영역 (볼록 껍질 + 손가락 굵기만큼 여유). 손이 없으면 None."""
    if not hf.hands:
        return None
    w, h = size
    m = np.zeros((h, w), np.uint8)
    for hd in hf.hands:
        p = (hd.points * [w, h]).astype(np.int32)
        cv2.fillConvexPoly(m, cv2.convexHull(p), 1)
        pad = max(3, int(0.12 * np.linalg.norm(p[0] - p[9])))  # 손목→중지 뿌리 길이 기준
        for a, b in HAND_CONNECTIONS:
            cv2.line(m, tuple(p[a]), tuple(p[b]), 1, pad)
    return m.astype(bool)


def _norm_box(b: Box | None, w: int, h: int) -> list[float] | None:
    if b is None:
        return None
    return [round(b[0] / w, 4), round(b[1] / h, 4), round(b[2] / w, 4), round(b[3] / h, 4)]
