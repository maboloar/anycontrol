"""실영상 정답(키프레임 박스) 만들기: 공식 EfficientTAM 비디오 예측기(영상 전체를 보는 오프라인 모드)로 물체를 전파한다.

앱의 실시간 추적기(ViTracker)와 독립적인 기준이다. 결과는 반드시 --sheet 그림으로 사람이 검수하고, 틀린 프레임은
--fix '프레임:x1,y1,x2,y2' 로 그 프레임에 박스를 다시 줘서 고친다 (그 프레임부터 다시 전파). 좌표는 640x360 기준.

    PYTHONPATH=backend/src:third_party/EfficientTAM backend/.venv/bin/python bench/fg/make_gt.py \\
        samples/test.mov --box 340,165,462,203 --every 6 --out bench/fg/gt/test.json --sheet /tmp/test_gt.jpg
출력 형식은 eval.harness.VideoGT (size 640x360, 원본 프레임 번호). 숫자는 영상 원래 fps 기준 프레임 번호다.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/src"))
sys.path.insert(0, str(ROOT / "third_party/EfficientTAM"))
W, H = 640, 360


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--box", required=True, help="첫 프레임(--start) 박스 x1,y1,x2,y2 (640x360)")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--stride", type=int, default=0, help="몇 프레임마다 읽을지 (0 = 30fps 가 되게)")
    ap.add_argument("--every", type=int, default=6, help="정답 키프레임 간격 (읽은 프레임 기준)")
    ap.add_argument("--fix", nargs="*", default=[], help="프레임:x1,y1,x2,y2 (원본 프레임 번호)")
    ap.add_argument("--hide", nargs="*", default=[], help="물체가 안 보이는 원본 프레임 구간 a-b (정답 box=None)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sheet")
    a = ap.parse_args()

    import torch
    from efficient_track_anything.build_efficienttam import build_efficienttam_video_predictor
    from vision_input.tracking import gpu

    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    stride = a.stride or max(1, round(fps / 30))
    tmp = Path(tempfile.mkdtemp(prefix="gt_frames_"))
    orig = []  # 읽은 프레임 → 원본 프레임 번호
    i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i >= a.start and (i - a.start) % stride == 0:
            cv2.imwrite(str(tmp / f"{len(orig):05d}.jpg"), cv2.resize(f, (W, H), interpolation=cv2.INTER_AREA),
                        [cv2.IMWRITE_JPEG_QUALITY, 95])
            orig.append(i)
        i += 1
    cap.release()
    to_local = {o: k for k, o in enumerate(orig)}

    pred = build_efficienttam_video_predictor("configs/efficienttam/efficienttam_ti_512x512.yaml",
                                              str(gpu.MODELS_DIR / "efficienttam_ti_512x512.pt"), device=gpu.device())
    prompts = {0: [float(v) for v in a.box.split(",")]}
    for fx in a.fix:
        fr, b = fx.split(":")
        prompts[to_local[int(fr)]] = [float(v) for v in b.split(",")]
    hidden = []
    for h in a.hide:
        x, y = (int(v) for v in h.split("-"))
        hidden.append((x, y))
    masks: dict[int, np.ndarray] = {}
    with torch.inference_mode(), torch.autocast(gpu.device().type, dtype=torch.float16):
        state = pred.init_state(str(tmp))
        for k, b in sorted(prompts.items()):
            pred.add_new_points_or_box(state, frame_idx=k, obj_id=1, box=np.array(b, np.float32))
        for k, _, logits in pred.propagate_in_video(state):
            masks[k] = (logits[0, 0] > 0).cpu().numpy()

    frames, tiles = {}, []
    for k in range(0, len(orig), a.every):
        o = orig[k]
        m = masks.get(k)
        hid = any(x <= o <= y for x, y in hidden)
        ys, xs = (np.nonzero(m) if m is not None else ([], []))
        box = None if hid or len(xs) < 20 else [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        frames[str(o)] = {"box": box, "visible_frac": 1.0 if box else 0.0}
        if a.sheet:
            img = cv2.imread(str(tmp / f"{k:05d}.jpg"))
            if m is not None:
                img[m] = (0.5 * img[m] + [0, 0, 127]).astype(np.uint8)
            if box:
                cv2.rectangle(img, tuple(box[:2]), tuple(box[2:]), (0, 255, 0), 2)
            cv2.putText(img, str(o), (8, 28), 0, 1.0, (0, 255, 255), 2)
            tiles.append(cv2.resize(img, (320, 180)))
    gt = {"video": str(a.video), "size": [W, H], "fps": fps, "init": {"frame": a.start, "box": prompts[0]},
          "frames": frames, "_note": "EfficientTAM 비디오 예측기(오프라인) 전파 + 사람 검수. make_gt.py"}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(gt, indent=1))
    if a.sheet:
        while len(tiles) % 6:
            tiles.append(np.zeros_like(tiles[0]))
        cv2.imwrite(a.sheet, np.vstack([np.hstack(tiles[r:r + 6]) for r in range(0, len(tiles), 6)]))
    print(f"{len(frames)} keyframes → {a.out}")


if __name__ == "__main__":
    main()
