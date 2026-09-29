"""평가 CLI.

    python -m vision_input.eval run --tracker csrt --split tune           # 합성 튜닝 세트
    python -m vision_input.eval run --tracker csrt --split eval           # 합성 평가 세트 (튜닝 금지)
    python -m vision_input.eval run --tracker csrt --video input.mov --gt annotations.json
    python -m vision_input.eval preview --seq tune/dark-grasp --out /tmp/p.jpg   # 합성 시퀀스 미리보기
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from .harness import VideoGT, VideoSequence, build_suite, report, run_suite, run_video
from .synth import SynthSequence
from .trackers import available, make_tracker


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vision_input.eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--tracker", required=True)
    r.add_argument("--split", choices=["tune", "eval"])
    r.add_argument("--only", help="이름에 이 문자열이 들어간 시퀀스만 (쉼표로 여러 개)")
    r.add_argument("--video")
    r.add_argument("--gt")
    r.add_argument("--pace", choices=["offline", "realtime"], default="offline")
    r.add_argument("--hands", action="store_true", help="정답 손 마스크를 트래커에 준다 (손 인식 가림 처리 평가)")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--frames", type=int, default=150)
    r.add_argument("--out", help="결과 JSON 저장 경로")
    p = sub.add_parser("preview")
    p.add_argument("--seq", required=True)
    p.add_argument("--out", required=True)
    sub.add_parser("list")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        print("trackers:", ", ".join(available()))
        print("sequences:", ", ".join(s.name for s in build_suite("tune")))
        return 0

    if a.cmd == "preview":
        split = a.seq.split("/")[0]
        spec = next(s for s in build_suite(split) if s.name == a.seq)
        seq = SynthSequence(spec)
        tiles = []
        for i in np.linspace(0, len(seq) - 1, 12).astype(int):
            img, gt = seq.render(int(i))
            img = img.copy()
            for key, col in (("amodal_box", (0, 255, 255)), ("visible_box", (0, 255, 0))):
                b = gt.target[key]
                if b:
                    cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), col, 1)
            cv2.putText(img, f"{i} vis={gt.target['visible_frac']:.2f} hand={gt.hand_frac:.2f}", (6, 18), 0, 0.5,
                        (255, 255, 255), 1)
            tiles.append(img)
        sheet = np.vstack([np.hstack(tiles[k * 4 : (k + 1) * 4]) for k in range(3)])
        cv2.imwrite(a.out, sheet)
        return 0

    t0 = time.time()
    if a.video:
        if not a.gt:
            ap.error("--video 에는 --gt 가 필요합니다")
        seq = VideoSequence(a.video, VideoGT.load(a.gt))
        results = [run_video(lambda: make_tracker(a.tracker), seq, a.pace)]
    else:
        specs = build_suite(a.split or "tune", frames=a.frames)
        if a.only:
            keys = a.only.split(",")
            specs = [s for s in specs if any(k in s.name for k in keys)]
        results = run_suite(a.tracker, specs, a.pace, a.workers, a.hands)
    print(report(results))
    print(f"({len(results)} sequences, {time.time() - t0:.1f}s)")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps({"tracker": a.tracker, "pace": a.pace, "results": results}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
