import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react';

type Size = { width: number; height?: number };
/** 크기만 바꾼다. 자식과 추적/게임 상태는 유지한다. */
export function useResizable(key: string, { minWidth = 220, minHeight = 100, floating = false, widthOnly = false, reverseX = false } = {}) {
  const [size, setSize] = useState<Size | null>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(key) ?? 'null') as Size | null;
      return saved && Number.isFinite(saved.width) && saved.width >= minWidth &&
        (saved.height === undefined || Number.isFinite(saved.height) && saved.height >= minHeight) ? saved : null;
    } catch { return null; }
  });
  const latest = useRef(size);
  const drag = useRef<{ x: number; y: number; width: number; height: number; max: number; dx: number; dy: number } | null>(null);
  const save = () => { try {
    if (latest.current) localStorage.setItem(key, JSON.stringify(latest.current));
    else localStorage.removeItem(key);
  } catch { /* 크기 저장이 막혀도 사용 가능 */ } };
  const reset = () => { latest.current = null; setSize(null); save(); };
  const update = (width: number, height: number, max: number) => {
    const next = { width: Math.round(Math.max(Math.min(minWidth, max), Math.min(max, width))),
      ...(!widthOnly ? { height: Math.round(Math.max(minHeight, Math.min(window.innerHeight * 2, height))) } : {}) };
    latest.current = next; setSize(next);
  };
  const bounds = (el: HTMLElement) => floating || widthOnly ? Math.max(minWidth, window.innerWidth - 32) : (el.parentElement?.clientWidth || window.innerWidth - 32);
  useEffect(() => () => { drag.current = null; }, []);
  useEffect(() => {
    const onReset = () => { drag.current = null; latest.current = null; setSize(null);
      try { localStorage.removeItem(key); } catch { /* 저장 불가여도 초기화 */ } };
    window.addEventListener('anycontrol.resize.reset', onReset);
    return () => window.removeEventListener('anycontrol.resize.reset', onReset);
  }, [key]);
  const grip = {
    onPointerDown: (e: PointerEvent<HTMLButtonElement>) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const el = e.currentTarget.parentElement!;
      const r = el.getBoundingClientRect();
      const edge = e.currentTarget.dataset.edge;
      drag.current = { x: e.clientX, y: e.clientY, width: r.width, height: r.height, max: bounds(el),
        dx: edge === 'top' || edge === 'bottom' ? 0 : edge === 'left' || reverseX ? -1 : 1,
        dy: widthOnly || edge === 'left' || edge === 'right' ? 0 : edge === 'top' ? -1 : 1 };
      e.currentTarget.setPointerCapture?.(e.pointerId);
    },
    onPointerMove: (e: PointerEvent<HTMLButtonElement>) => {
      const d = drag.current;
      if (d) update(d.width + (e.clientX - d.x) * d.dx, d.height + (e.clientY - d.y) * d.dy, d.max);
    },
    onPointerUp: () => { if (drag.current) { drag.current = null; save(); } },
    onPointerCancel: () => { drag.current = null; save(); },
    onLostPointerCapture: () => { drag.current = null; save(); },
    onDoubleClick: reset,
    onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => {
      if (e.key === 'Home') { e.preventDefault(); reset(); return; }
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      const el = e.currentTarget.parentElement!; const r = el.getBoundingClientRect();
      update(r.width + (e.key === 'ArrowRight' ? 20 : e.key === 'ArrowLeft' ? -20 : 0),
        r.height + (e.key === 'ArrowDown' ? 20 : e.key === 'ArrowUp' ? -20 : 0), bounds(el)); save();
    },
  };
  const style: CSSProperties = size ? { width: size.width, ...(!widthOnly ? { height: size.height } : {}) } : {};
  return { style, grip };
}

export function ResizeHandle({ label, grip, className = '' }: { label: string; grip: ReturnType<typeof useResizable>['grip']; className?: string }) {
  const title = '경계를 끌어서 크기 조절 · 방향키로 조절 · 두 번 클릭 또는 Home으로 원래 크기';
  if (className === 'sidebar-resize') return <button type="button" className={`resize-handle ${className}`} aria-label={`${label} 크기 조절`} title={title} {...grip} />;
  return <>
    {(['left', 'right', 'top', 'bottom'] as const).map(edge => <button key={edge} type="button"
      className={`resize-edge resize-edge-${edge}`} data-edge={edge}
      aria-label={`${label} ${ { left: '왼쪽', right: '오른쪽', top: '위쪽', bottom: '아래쪽' }[edge]} 경계 크기 조절`}
      title={title} {...grip} />)}
    <button type="button" className={`resize-handle ${className}`} aria-label={`${label} 크기 조절`}
      title={title} {...grip}>◢</button>
  </>;
}
