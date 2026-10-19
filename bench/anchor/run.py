"""물체 커서 기준점(anchor) 벤치: 실제 영상에서 '분할 영역 중심'과 '바닥 기준점(광학 흐름)'의 떨림을 비교한다.
    PYTHONPATH=backend/src:third_party/EfficientTAM backend/.venv/bin/python bench/anchor/run.py [--video samples/test.mov] [--png out.png]
정답 좌표가 없어서 '떨림'(프레임 간 2차 차분의 RMS, 1280 폭 기준 px)과 '이동 거리'를 본다. 같은 물체의 움직임이라
부드럽지만 실제로 따라가는 쪽이 낮다. 기준점이 물체 아래-가운데에 머무는지는 --png 로 그림을 저장해 눈으로 확인한다.
(손 마스크가 없으면 hand_frac=0 이라 trust 가 항상 켜진다. --no-trust 는 마스크 보정 없이 흐름만 쓴 경우.)
"""
from __future__ import annotations
import argparse
import dataclasses
import sys
from pathlib import Path
import cv2
import numpy as np
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bench" / "still"))
import scenarios  # noqa: E402


def jitter(xy: np.ndarray) -> float:
    d2 = np.diff(xy, 2, axis=0)
    return float(np.sqrt((d2 ** 2).sum(1).mean()))


def hf(xy: np.ndarray, win: int = 9) -> float:
    """고주파 떨림: 가운데 이동평균(창 win)을 뺀 잔차의 RMS (px). 실제 움직임은 부드럽다고 보고 그 위의 떨림만 잰다."""
    k = np.ones(win) / win
    sm = np.stack([np.convolve(np.pad(xy[:, i], (win // 2, win // 2), mode="edge"), k, mode="valid") for i in range(2)], 1)
    return float(np.sqrt(((xy - sm) ** 2).sum(1).mean()))


def main() -> int:
    from vision_input.tracking.anchor import AnchorConfig, ObjectAnchor, bottom_center
    from vision_input.tracking.api import InitPrompt
    from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="samples/test.mov")
    ap.add_argument("--frames", type=int, default=347)
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--no-trust", action="store_true")
    ap.add_argument("--png", default=None)
    a = ap.parse_args()
    frames = scenarios.read_frames(a.video, 0, a.frames, step=a.step)
    H, W = frames[0].shape[:2]
    tr = ViTracker(dataclasses.replace(TrackerConfig(), tier1="off"))
    anchor = ObjectAnchor()
    k = anchor.cfg.work_width / W
    from vision_input.io.mouse import MouseController, MouseSettings
    from vision_input.io.sink import VirtualSink
    sinks, mouses = [VirtualSink(), VirtualSink()], []
    for sk in sinks:
        mc = MouseController(sk)
        mc.configure(MouseSettings(mode="object", object_id=1, hand_clicks=False, coordinate_mode="depth", depth_source="size"))
        mouses.append(mc)
    cur_pose, cur_anchor = [], []
    pose, raw, anc, states, shots, ps, asc = [], [], [], [], [], [], []
    for i, img in enumerate(frames):
        t = i / (60.0 / a.step)
        out = tr.add(img, 1, InitPrompt(box=scenarios.WALLET_BOX)) if i == 0 else tr.step(img, t)[1]
        if not out.state.visible or out.mask is None or out.pose is None:
            continue
        gray = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (round(W * k), round(H * k)), interpolation=cv2.INTER_AREA)
        m = cv2.resize(out.mask.astype(np.uint8), (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
        trust = (not a.no_trust) and out.debug.get("hand_frac", 0.0) < 0.15
        st = anchor.update(gray, m, True, trust, (W, H), out.pose.scale)
        b = bottom_center(m, anchor.cfg.band, anchor.cfg.inset, anchor.cfg.min_h)
        if st.valid:   # 같은 물체로 커서를 두 방식으로: (1) 분할 중심·크기 (2) 바닥 기준점·흐름 크기
            mouses[0].update(t, None, (out.pose.cx / W, out.pose.cy / H), True, False, None, obj_scale=float(out.pose.scale))
            mouses[1].update(t, None, (st.xy[0] / W, st.xy[1] / H), True, False, None, obj_scale=float(st.scale or out.pose.scale))
            cur_pose.append((sinks[0].x, sinks[0].y)); cur_anchor.append((sinks[1].x, sinks[1].y))
        if st.valid and b is not None:
            pose.append((out.pose.cx, out.pose.cy)); raw.append((b[0] / k, b[1] / k)); anc.append(st.xy); states.append(st.source); ps.append(float(np.log(out.pose.scale))); asc.append(float(np.log(st.scale)))
            if a.png and i % 40 == 0:
                v = img.copy()
                cnt, _ = cv2.findContours(out.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(v, cnt, -1, (0, 255, 0), 2)
                cv2.circle(v, (int(out.pose.cx), int(out.pose.cy)), 8, (0, 165, 255), 2)       # 주황: 분할 중심(포즈)
                cv2.circle(v, (int(b[0] / k), int(b[1] / k)), 8, (255, 0, 0), 2)               # 파랑: 마스크 아래-가운데 (프레임별 측정)
                cv2.circle(v, (int(st.xy[0]), int(st.xy[1])), 7, (0, 0, 255), -1)              # 빨강: 기준점
                shots.append(cv2.resize(v, (640, 360)))
    tr.close() if hasattr(tr, "close") else None
    P, R, A = (np.array(x, float) for x in (pose, raw, anc))
    print(f"frames used {len(A)} of {len(frames)}; sources", {s: states.count(s) for s in set(states)})
    for name, X in (("pose center (분할 중심)", P), ("mask bottom-center (프레임별 측정)", R), ("anchor (광학 흐름)", A)):
        print(f"{name:34s} jitter {jitter(X):6.2f} px   path {np.linalg.norm(np.diff(X, axis=0), axis=1).sum():8.0f} px   떨림(고주파) {hf(X):6.2f} px")
    for name, X in (("log-크기: 포즈(분할)", np.array(ps)), ("log-크기: 기준점 흐름", np.array(asc))):
        X2 = np.stack([X, np.zeros_like(X)], 1)
        print(f"{name:34s} 떨림(고주파) {hf(X2):8.4f}   (1.0 = 크기 100% 변화)")
    for name, X in (("커서: 분할 중심·크기 (예전)", np.array(cur_pose)), ("커서: 바닥 기준점·흐름 (새)", np.array(cur_anchor))):
        print(f"{name:34s} 떨림 x {hf(np.stack([X[:, 0], 0 * X[:, 0]], 1)) * 1000:6.1f} / y {hf(np.stack([X[:, 1], 0 * X[:, 1]], 1)) * 1000:6.1f}  합 {hf(X) * 1000:7.2f} (화면 1000 기준)  경로 {np.linalg.norm(np.diff(X, axis=0), axis=1).sum() * 1000:8.0f}")
    print(f"log-크기 상관(포즈 vs 흐름) {np.corrcoef(ps, asc)[0, 1]:.3f}, 범위 포즈 {np.ptp(ps):.2f} / 흐름 {np.ptp(asc):.2f}")
    if a.png and shots:
        rows = [np.hstack(shots[i:i + 3] + [np.zeros_like(shots[0])] * (3 - len(shots[i:i + 3]))) for i in range(0, len(shots), 3)]
        cv2.imwrite(a.png, np.vstack(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
