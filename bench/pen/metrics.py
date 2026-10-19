"""펜 접촉 지표 (independent_pen_algorithm_test/pen/evaluate.py 이식).

라벨 형식 (평가 전용, 알고리즘은 보지 않는다):
    {"fps": 60, "contact_intervals": [[a, b], ...], "low_confidence_intervals": [[a, b]], "ignore_radius": 2}
프레임 번호는 원본 영상 기준. 예측은 원본 프레임 번호 → bool. 처리하지 않은 프레임(30fps 재생 등)은
직전 예측을 유지한 것으로 본다 (앱 화면과 같은 조건).
"""
from __future__ import annotations


def intervals(flags: list[int]) -> list[tuple[int, int]]:
    out, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        if not f and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(flags) - 1))
    return out


def densify(pred: dict[int, bool], n: int) -> list[int]:
    out, last = [], 0
    for i in range(n):
        if i in pred:
            last = int(bool(pred[i]))
        out.append(last)
    return out


def score(pred_flags: list[int], ref: dict, skip_low_conf: bool = False) -> dict:
    n = len(pred_flags)
    gt = [0] * n
    for a, b in ref["contact_intervals"]:
        for i in range(a, min(b, n - 1) + 1):
            gt[i] = 1
    rad = ref.get("ignore_radius", 2)
    bounds = [x for ab in ref["contact_intervals"] for x in ab]
    start = int(ref.get("score_from", 0))  # 펜 등록 전 프레임은 채점하지 않는다
    scored = [i for i in range(start, n) if all(abs(i - b) > rad for b in bounds)]
    if skip_low_conf:
        low = ref.get("low_confidence_intervals", [])
        scored = [i for i in scored if not any(a <= i <= b for a, b in low)]
    p = pred_flags
    tp = sum(1 for i in scored if p[i] and gt[i])
    tn = sum(1 for i in scored if not p[i] and not gt[i])
    fp = sum(1 for i in scored if p[i] and not gt[i])
    fn = sum(1 for i in scored if not p[i] and gt[i])
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    P = intervals(p)
    events, frags = [], []
    for a, b in ref["contact_intervals"]:
        ov = [(s, e) for s, e in P if not (e < a or s > b)]
        frags.append(len(ov))
        events.append((a, b, None, None) if not ov else (a, b, ov[0][0] - a, ov[-1][1] - b))
    spurious = [(s, e) for s, e in P if all(e < a or s > b for a, b in ref["contact_intervals"])]
    return dict(acc=(tp + tn) / max(len(scored), 1), prec=prec, rec=rec,
                f1=2 * prec * rec / max(prec + rec, 1e-9), tp=tp, tn=tn, fp=fp, fn=fn, scored=len(scored),
                events=events, frags=frags, spurious=spurious, pred_intervals=P)


def format_result(name: str, a: dict, b: dict, fps: float) -> str:
    ms = 1000.0 / fps
    lines = [f"{name}: acc {a['acc']:.3f} prec {a['prec']:.3f} rec {a['rec']:.3f} F1 {a['f1']:.3f} | "
             f"excl.low-conf acc {b['acc']:.3f} F1 {b['f1']:.3f} | spurious {len(a['spurious'])} "
             f"pieces {a['frags']}"]
    for (ra, rb, dn, up) in a["events"]:
        lines.append(f"    ref {ra}-{rb}: " + ("MISSED" if dn is None else
                     f"down {dn:+d}f ({dn * ms:+.0f}ms) up {up:+d}f ({up * ms:+.0f}ms)"))
    return "\n".join(lines)
