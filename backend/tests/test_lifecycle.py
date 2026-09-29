"""실제 모델 없이 지연 추론·재시작·실패·서버 종료의 경쟁 조건을 재현한다."""
import threading
from unittest.mock import Mock

import numpy as np
from fastapi.testclient import TestClient

from vision_input.hands import detector
from vision_input.capture.slot import Frame
from vision_input.pipeline import VisionProcessor
from vision_input.server.app import SyntheticSpec, create_app
from .test_server import RectSeg
from .test_source_controls import wait_until


def test_stop_during_inference_does_not_restart_or_publish_old_results(monkeypatch):
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    models = []
    class SlowDetector:
        def __init__(self):
            models.append(self)
        def detect(self, image, t):
            entered.set()
            assert release.wait(3)
            return detector.HandFrame(t, [], 1.)
        def close(self):
            closed.set()
    monkeypatch.setattr(detector, 'HandDetector', SlowDetector)
    worker = detector.HandWorker("mediapipe")
    worker.start()
    worker.offer(np.zeros((4, 4, 3), np.uint8), 1.)
    assert entered.wait(2)
    try:
        worker.stop(timeout=0)
        worker.start()
        worker.offer(np.zeros((4, 4, 3), np.uint8), 2.)
        assert worker.running and worker.latest() is None and len(models) == 1
    finally:
        release.set()
        worker.stop()
    assert closed.is_set() and worker.latest() is None
    worker.start()
    try:
        wait_until(lambda: len(models) == 2)
        assert worker.latest() is None and worker._frame is None
    finally:
        worker.stop()


def test_inference_failure_is_reported_and_restart_is_rate_limited(monkeypatch):
    model = Mock()
    model.detect.side_effect = RuntimeError('test inference failed')
    make = Mock(return_value=model)
    monkeypatch.setattr(detector, 'HandDetector', make)
    worker = detector.HandWorker("mediapipe")
    worker.start()
    worker.offer(np.zeros((4, 4, 3), np.uint8), 1.)
    wait_until(lambda: not worker.running)
    assert worker.error == 'test inference failed'
    assert worker.latest() is None
    model.close.assert_called_once()
    for _ in range(100):
        worker.start()
    assert make.call_count == 1
    worker.stop()


def test_server_closes_processor_and_releases_pressed_input():
    p = VisionProcessor(None)
    p.close = Mock(wraps=p.close)
    app = create_app(initial_source=SyntheticSpec(width=160, height=120), processor=p,
                     segmenter=RectSeg(), serve_frontend=False)
    with TestClient(app):
        app.state.engine.submit(lambda: p.sink.button('left', True)).result(2)
    p.close.assert_called_once()
    assert not p.sink.snapshot()['left']
    assert app.state.engine.submit(lambda: 1).cancelled()


def test_disabling_hand_occlusion_clears_previous_mask(monkeypatch):
    from .handkit import make_hand
    p = VisionProcessor(None)
    p.tracker = Mock()
    p.tracker.step.return_value = {}
    p.objects[1] = object()  # 이번 프레임 출력 없음: 마스크 전달 경로만 검사
    p.state = lambda: {}
    monkeypatch.setattr(p.mapping, 'update', lambda snapshot: None)
    # 나머지 입력 파이프라인 대신 자동 보정의 중립 상태 경로를 쓴다.
    p.auto_calibration = Mock(active=True)
    p.auto_calibration.observe = Mock()
    p._auto_sample = lambda hf, t: {}
    p._hands = lambda frame: detector.HandFrame(frame.t_capture, [make_hand(.5, .5, .15)])
    image = np.zeros((120, 160, 3), np.uint8)
    p.hand_occlusion = True
    p.process(Frame(1, image, 1., 1.))
    assert p.tracker.set_occluders.call_args.args[0].any()
    p.hand_occlusion = False
    p.process(Frame(2, image, 2., 2.))
    assert p.tracker.set_occluders.call_args.args[0] is None
