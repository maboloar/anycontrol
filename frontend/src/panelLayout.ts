// 패널 배치: 세 열(메인 · 설정 왼쪽 · 설정 오른쪽)에 어떤 패널이 어떤 순서로 있는지. 제목 줄을 끌어 자유롭게 옮긴다.
import { useEffect, useRef, useState } from "react";

export type SlotId = "camera" | "mapping" | "demo" | "real" | "hud" | "objects" | "source" | "mouse";
export type Layout = SlotId[][];

export const SLOT_IDS: SlotId[] = ["camera", "mapping", "demo", "real", "hud", "objects", "source", "mouse"];
/** 기본: 출력 대상 → 성능 → 물체 (매핑하기 쉽게 물체가 가운데), 카메라 → 마우스 */
export const DEFAULT_LAYOUT: Layout = [["camera", "mapping", "demo"], ["real", "hud", "objects"], ["source", "mouse"]];
const KEY = "anycontrol.panelLayout";

export function validLayout(v: unknown): v is Layout {
  if (!Array.isArray(v) || v.length !== 3 || !v.every(Array.isArray)) return false;
  const flat = (v as unknown[][]).flat();
  return flat.length === SLOT_IDS.length && SLOT_IDS.every((id) => flat.includes(id));
}

/** id 를 col 열의 index 자리로 옮긴다 (index 는 옮기기 전 그 열 기준, 끝이면 열 길이). */
export function moveSlot(layout: Layout, id: SlotId, col: number, index: number): Layout {
  const from = layout.findIndex((c) => c.includes(id));
  if (from < 0) return layout;
  const fromIdx = layout[from]!.indexOf(id);
  const next = layout.map((c) => c.filter((x) => x !== id));
  const at = from === col && fromIdx < index ? index - 1 : index;
  next[col]!.splice(Math.max(0, Math.min(at, next[col]!.length)), 0, id);
  return next;
}

export function usePanelLayout(): [Layout, (l: Layout) => void] {
  const [layout, setLayout] = useState<Layout>(() => {
    try { const v = JSON.parse(localStorage.getItem(KEY) ?? "null"); return validLayout(v) ? v : DEFAULT_LAYOUT; }
    catch { return DEFAULT_LAYOUT; }
  });
  useEffect(() => {
    const reset = () => { setLayout(DEFAULT_LAYOUT); try { localStorage.removeItem(KEY); } catch { /* 화면만 */ } };
    window.addEventListener("anycontrol.layout.reset", reset);
    return () => window.removeEventListener("anycontrol.layout.reset", reset);
  }, []);
  const save = (l: Layout) => {
    setLayout(l);
    try { localStorage.setItem(KEY, JSON.stringify(l)); } catch { /* 이번 화면에서만 */ }
  };
  return [layout, save];
}

export interface Drop { col: number; index: number }

/** 패널 제목 줄을 끌어 옮기기. 6px 넘게 움직이면 끌기 시작, 놓은 곳의 패널 위/아래 절반 또는 빈 열 끝에 넣는다. */
export function usePanelDrag(layout: Layout, onMove: (l: Layout) => void): { dragging: SlotId | null; drop: Drop | null } {
  const [dragging, setDragging] = useState<SlotId | null>(null);
  const [drop, setDrop] = useState<Drop | null>(null);
  // 끄는 동안 다시 그려져도 리스너·진행 상태가 유지되게 최신 배치·콜백은 ref 로 읽는다
  const ref = useRef({ layout, onMove });
  ref.current = { layout, onMove };
  useEffect(() => {
    let start: { id: SlotId; x: number; y: number } | null = null;
    let active: SlotId | null = null;
    let target: Drop | null = null;
    const findDrop = (x: number, y: number): Drop | null => {
      const { layout } = ref.current;
      const els = document.elementsFromPoint(x, y);
      const slot = els.map((e) => e.closest("[data-slot]")).find((e) => e && e.getAttribute("data-slot") !== active) as HTMLElement | undefined;
      if (slot) {
        const id = slot.getAttribute("data-slot") as SlotId;
        const col = layout.findIndex((c) => c.includes(id));
        const r = slot.getBoundingClientRect();
        return { col, index: layout[col]!.indexOf(id) + (y > r.top + r.height / 2 ? 1 : 0) };
      }
      const colEl = els.map((e) => e.closest("[data-col]")).find(Boolean);
      if (colEl) { const col = Number(colEl.getAttribute("data-col")); return { col, index: layout[col]!.length }; }
      return null;
    };
    const down = (e: PointerEvent) => {
      if (e.button !== 0) return;
      const el = e.target as Element;
      if (!el.closest?.(".panel-header") || el.closest("button, input, select, textarea, a, label, [role=button]")) return;
      const slot = el.closest("[data-slot]");
      if (!slot) return;
      start = { id: slot.getAttribute("data-slot") as SlotId, x: e.clientX, y: e.clientY };
    };
    const move = (e: PointerEvent) => {
      if (!start) return;
      if (!active) {
        if (Math.hypot(e.clientX - start.x, e.clientY - start.y) < 6) return;
        active = start.id;
        setDragging(active);
        document.body.classList.add("panel-dragging");
      }
      e.preventDefault();
      target = findDrop(e.clientX, e.clientY);
      setDrop(target);
    };
    const up = () => {
      if (active && target) ref.current.onMove(moveSlot(ref.current.layout, active, target.col, target.index));
      start = null; active = null; target = null;
      setDragging(null); setDrop(null);
      document.body.classList.remove("panel-dragging");
    };
    window.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    return () => {
      window.removeEventListener("pointerdown", down);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
  }, []);
  return { dragging, drop };
}
