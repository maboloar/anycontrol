"""영상 정지 중 등록을 유지하고 재생을 이어 가는 소스 계약."""

import cv2
import numpy as np
import pytest

from vision_input.capture.sources import VideoFileSource


def test_paused_video_repeats_first_frame_then_resumes(tmp_path):
    path = tmp_path / "pause.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    if not writer.isOpened():
        pytest.skip("test video codec unavailable")
    for level in (20, 100, 180):
        writer.write(np.full((48, 64, 3), level, np.uint8))
    writer.release()
    src = VideoFileSource(path, loop=True, paused=True)
    src.start()
    try:
        first = src.slot.wait_newer(-1, timeout=2)
        assert first is not None
        repeat = src.slot.wait_newer(first.seq, timeout=2)
        assert repeat is not None and np.array_equal(first.image, repeat.image)
        assert src.info()["paused"]
        src.paused = False
        seq = repeat.seq
        for _ in range(5):
            frame = src.slot.wait_newer(seq, timeout=2)
            assert frame is not None
            seq = frame.seq
            if frame.image.mean() > first.image.mean() + 40:
                break
        else:
            pytest.fail("video did not resume")
    finally:
        src.stop()


def test_empty_looping_video_stops_instead_of_busy_spinning(monkeypatch):
    from unittest.mock import Mock
    capture = Mock()
    capture.isOpened.return_value = True
    capture.get.return_value = 30.
    capture.read.return_value = (False, None)
    capture.set.return_value = True
    monkeypatch.setattr(cv2, 'VideoCapture', lambda _: capture)
    src = VideoFileSource('empty.mp4', loop=True)
    src._run()
    assert src.status == 'error' and src.error
    assert capture.read.call_count == 2
    capture.release.assert_called_once()
