import { useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

const GAP = 8;
const MARGIN = 8;

/** 말풍선 위치: 아이콘 위 가운데 (자리가 없으면 아래). 화면 밖으로 나가지 않게 좌우를 당긴다. */
export function tipPosition(
  anchor: { left: number; top: number; width: number; height: number },
  tip: { width: number; height: number },
  vp: { width: number; height: number },
): { left: number; top: number; below: boolean } {
  const cx = anchor.left + anchor.width / 2;
  const left = Math.max(MARGIN, Math.min(cx - tip.width / 2, vp.width - tip.width - MARGIN));
  const above = anchor.top - GAP - tip.height;
  const below = above < MARGIN;
  return { left, top: below ? anchor.top + anchor.height + GAP : above, below };
}

/**
 * 정보 아이콘 (i). 마우스를 올리거나 키보드로 포커스하면 짧은 설명이 뜬다.
 * 말풍선은 body 에 그려서 패널·영상의 overflow 에 잘리지 않는다. label 안에 있어도 눌러서 체크가 바뀌지 않는다.
 */
export function Info({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const id = useId();

  useLayoutEffect(() => {
    const a = ref.current;
    const t = tipRef.current;
    if (!open || !a || !t) return;
    const p = tipPosition(a.getBoundingClientRect(), t.getBoundingClientRect(),
      { width: window.innerWidth, height: window.innerHeight });
    t.style.left = `${p.left}px`;
    t.style.top = `${p.top}px`;
    t.dataset.below = p.below ? "1" : "0";
    t.style.visibility = "visible";
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  return (
    <>
      <span ref={ref} className="info" tabIndex={0} role="img" aria-label="도움말" aria-describedby={open ? id : undefined}
        onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)} /* 전파는 막지 않는다: ESC = 긴급 정지 */
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}>i</span>
      {open && createPortal(
        <div ref={tipRef} id={id} role="tooltip" className={`info-tip ${wide ? "wide" : ""}`} style={{ visibility: "hidden" }}>
          {children}
        </div>,
        document.body,
      )}
    </>
  );
}
