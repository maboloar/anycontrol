"""테스트용 합성 손 랜드마크 (MediaPipe 21점 배치를 흉내 낸다).

손바닥이 카메라를 향하고 손가락이 위(-y)로 뻗은 자세. size = 손목→가운뎃손가락 뿌리 거리.
pinch: 엄지 끝-검지 끝 거리 (손 크기 대비). pinch_middle: 엄지 끝-중지 끝 거리.
scroll_pose: 검지·중지만 펴고 약지·새끼 접음.
"""

import numpy as np

from vision_input.hands.detector import Hand


def make_hand(cx: float, cy: float, size: float, pinch: float = 1.0, pinch_middle: float = 1.2,
              scroll_pose: bool = False) -> Hand:
    s = size
    P = np.zeros((21, 2), np.float64)
    wrist = np.array([cx, cy + 0.9 * s])
    P[0] = wrist
    mcp_x = [-0.35, -0.12, 0.12, 0.33]  # 검지, 중지, 약지, 새끼 뿌리
    for f, dx in enumerate(mcp_x):
        base = 5 + 4 * f
        mcp = wrist + np.array([dx * s, -1.0 * s])
        P[base] = mcp
        extended = True
        if scroll_pose and f >= 2:
            extended = False
        if extended:
            P[base + 1] = mcp + [0, -0.45 * s]    # PIP
            P[base + 2] = mcp + [0, -0.75 * s]    # DIP
            P[base + 3] = mcp + [0, -1.0 * s]     # TIP
        else:  # 접음: 끝이 손바닥 쪽으로 돌아온다
            P[base + 1] = mcp + [0, -0.35 * s]
            P[base + 2] = mcp + [0, -0.15 * s]
            P[base + 3] = mcp + [0, 0.05 * s]
    # 엄지: 검지 끝으로부터 pinch·s 만큼 떨어진 곳에 끝을 둔다 (중지 조건이 우선이면 그쪽으로)
    idx_tip = P[8]
    mid_tip = P[12]
    if pinch_middle < pinch:  # 중지 쪽(검지 반대편)에서 댄다
        thumb_tip = mid_tip + np.array([pinch_middle * s, 0.0])
    else:
        thumb_tip = idx_tip + np.array([-pinch * s, 0.0])
    P[1] = wrist + [-0.3 * s, -0.2 * s]
    P[2] = wrist + [-0.5 * s, -0.45 * s]
    P[3] = (P[2] + thumb_tip) / 2
    P[4] = thumb_tip
    return Hand(P.astype(np.float32), np.zeros(21, np.float32), "Right", 0.95)
