"""Desk View 설정 창. Cocoa 메인 런루프를 가진 별도 프로세스에서 실행한다."""
from __future__ import annotations

import subprocess
import sys


def present_desk_view() -> None:
    if sys.platform != 'darwin':
        raise RuntimeError('Desk View 설정 창은 macOS에서 사용할 수 있습니다')
    try:
        result = subprocess.run([sys.executable, '-m', 'vision_input.capture.desk_setup'],
                                capture_output=True, text=True, timeout=12)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Desk View 설정 창 실행 시간이 초과되었습니다. 메뉴 막대의 비디오 메뉴에서 여세요.') from exc
    if result.returncode:
        raise RuntimeError(result.stdout.strip() or 'Desk View 설정 창을 열 수 없습니다')


def main() -> int:
    import AVFoundation as AVF
    import time
    from Foundation import NSDate, NSRunLoop
    if not hasattr(AVF, 'AVCaptureDeskViewApplication'):
        print('이 macOS 버전은 Desk View 설정 API를 지원하지 않습니다')
        return 1
    app = AVF.AVCaptureDeskViewApplication.alloc().init()
    config = AVF.AVCaptureDeskViewApplicationLaunchConfiguration.alloc().init()
    config.setRequiresSetUpModeCompletion_(False)
    done, error = False, None

    def completed(err):
        nonlocal done, error
        done, error = True, err
    app.presentWithLaunchConfiguration_completionHandler_(config, completed)
    deadline = time.monotonic() + 10
    while not done and time.monotonic() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(.05))
    if not done or error:
        print(str(error) if error else 'Desk View 설정 창 실행 시간이 초과되었습니다')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
