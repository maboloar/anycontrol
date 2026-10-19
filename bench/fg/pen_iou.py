"""펜 벤치 캐시(앱과 같은 register_line 경로)를 bench/fg/gt 정답 박스로 채점한다.
    PEN_TRACKER=vi_fgd backend/.venv/bin/python bench/fg/pen_iou.py bench/pen/configs/img_0002.json bench/fg/gt/img_0002.json
"""
import json, sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend/src"))
sys.path.insert(0, str(HERE.parent / "pen"))
import track_cache  # noqa: E402
from vision_input.tracking.api import box_iou  # noqa: E402

cfg = json.loads(Path(sys.argv[1]).read_text()); gt = json.loads(Path(sys.argv[2]).read_text())
step = int(sys.argv[3]) if len(sys.argv) > 3 else 1
cache = track_cache.load(cfg, step)
k = int(cfg.get("width", 1280)) / gt["size"][0]
ok = n = fp = inv = 0; errs = []
for f, g in gt["frames"].items():
    row = cache["rows"].get(int(f))
    if row is None:
        continue
    said = row["state"] in ("tracking", "grasped") and row["box"] is not None
    if g["box"] is None:
        inv += 1; fp += said; continue
    n += 1
    b = [v * k for v in g["box"]]
    if said:
        iou = box_iou(tuple(row["box"]), tuple(b))
        ok += iou >= 0.5
        if iou >= 0.5:
            c = ((row["box"][0] + row["box"][2]) / 2, (row["box"][1] + row["box"][3]) / 2)
            errs.append(np.hypot(c[0] - (b[0] + b[2]) / 2, c[1] - (b[1] + b[3]) / 2) / np.sqrt((b[2] - b[0]) * (b[3] - b[1])))
print(f"{track_cache.tracker_name()}: success {ok}/{n} = {ok / max(n, 1):.3f}  center_err {np.mean(errs) if errs else float('nan'):.3f}  fp {fp}/{inv}")
