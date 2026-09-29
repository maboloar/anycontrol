"""AVFoundation 장치 발견. 목록과 캡처에서 같은 장치 ID/순서를 사용한다."""
from __future__ import annotations

import logging
import sys
from typing import Any

log = logging.getLogger(__name__)


def discover_devices() -> list[Any]:
    if sys.platform != 'darwin':
        return []
    import AVFoundation as AVF
    from Foundation import NSBundle

    names = ['AVCaptureDeviceTypeBuiltInWideAngleCamera', 'AVCaptureDeviceTypeExternal',
             'AVCaptureDeviceTypeDeskViewCamera']
    # macOS 14의 새로운 유형은 opt-in된 앱 런처에서만 요청한다.
    if NSBundle.mainBundle().objectForInfoDictionaryKey_('NSCameraUseContinuityCameraDeviceType'):
        names.append('AVCaptureDeviceTypeContinuityCamera')
    types = [getattr(AVF, n) for n in names if hasattr(AVF, n)]
    session = AVF.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_(
        types, AVF.AVMediaTypeVideo, AVF.AVCaptureDevicePositionUnspecified)
    return list(session.devices() or [])


def list_cameras() -> list[dict[str, Any]]:
    try:
        devices = discover_devices()
        if not devices:
            return []
        import CoreMedia as CM
    except ImportError:
        log.warning('pyobjc AVFoundation not installed; camera names unavailable')
        return []
    parents = {}
    companions = {}
    for d in devices:
        companion = d.companionDeskViewCamera() if hasattr(d, 'companionDeskViewCamera') else None
        if companion is not None:
            companions[str(d.uniqueID())] = str(companion.uniqueID())
            parents[str(companion.uniqueID())] = str(d.uniqueID())
    out = []
    for i, d in enumerate(devices):
        dtype, uid = str(d.deviceType()), str(d.uniqueID())
        desk = 'DeskView' in dtype
        continuity = bool(d.isContinuityCamera()) if hasattr(d, 'isContinuityCamera') else 'Continuity' in dtype
        best = {}
        try:
            for f in d.formats():
                dim = CM.CMVideoFormatDescriptionGetDimensions(f.formatDescription())
                fps = max((r.maxFrameRate() for r in f.videoSupportedFrameRateRanges()), default=0)
                key = (int(dim.width), int(dim.height))
                best[key] = max(best.get(key, 0), float(fps))
        except Exception:
            log.debug('format query failed', exc_info=True)
        out.append({'index': i, 'name': str(d.localizedName()), 'unique_id': uid,
                    'model': str(d.modelID() or ''), 'device_type': dtype,
                    'is_continuity': continuity, 'is_desk_view': desk,
                    'companion_id': companions.get(uid), 'parent_id': parents.get(uid),
                    'formats': [{'width': w, 'height': h, 'max_fps': fps}
                                for (w, h), fps in sorted(best.items())]})
    return out


def select_camera(cameras: list[dict[str, Any]], index: int = -1,
                  device_id: str | None = None, desk_view: bool = False) -> dict[str, Any]:
    if device_id:
        selected = next((c for c in cameras if c['unique_id'] == device_id), None)
    elif index >= 0:
        selected = next((c for c in cameras if c['index'] == index), None)
    else:
        normal = [c for c in cameras if not c.get('is_desk_view')]
        selected = next((c for c in normal if c['is_continuity']), normal[0] if normal else None)
        if desk_view and (selected is None or not selected.get('companion_id')):
            selected = next((c for c in cameras if c.get('is_desk_view')), None)
    if selected is None:
        raise ValueError('카메라가 연결되어 있지 않습니다. 장치 목록을 새로고침하세요.')
    if desk_view and not selected.get('is_desk_view'):
        selected = next((c for c in cameras if c['unique_id'] == selected.get('companion_id')), None)
        if selected is None:
            raise ValueError('선택한 카메라의 Desk View가 없습니다. 지원되는 iPhone을 연결하세요.')
    elif not desk_view and selected.get('is_desk_view'):
        selected = next((c for c in cameras if c['unique_id'] == selected.get('parent_id')), None)
        if selected is None:
            raise ValueError('Desk View와 연결된 일반 카메라를 찾을 수 없습니다.')
    return selected
