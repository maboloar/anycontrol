import { findObject, objectLabel, objectRef } from "../objectRefs";
import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { allFns, type Cable } from "../patch";
import { useApp, type PatchDrag } from "../store";

/** 잭 하나. side=obj 는 물체 카드 오른쪽, side=fn 은 매핑 패널의 기능 잭. 매핑 패널이 열려 있을 때만 보인다.
 * 끌어서 반대쪽 잭에 놓거나, 한 번 눌러 집은 뒤 반대쪽 잭을 눌러도 이어진다 (양방향). ESC = 취소. */
export function PatchJack({ side, name, color, connected = false }: { side: "obj" | "fn"; name: string; color?: string; connected?: boolean }) {
  const objects = useApp(s => s.objects);
  const enabled = useApp((s) => s.patchConnect !== null);
  const drag = useApp((s) => s.patchDrag);
  if (!enabled) return null;
  const holding = drag && (drag.from.kind === "obj" ? side === "obj" && drag.from.name === name : side === "fn" && drag.from.id === name);
  const target = drag && drag.from.kind !== side;
  const label = side === "obj" ? t(`${objectLabel(name, objects)} 잭: 끌어서 기능에 연결`, `${objectLabel(name, objects)} jack: drag to a function`)
    : t("기능 잭: 끌어서 물체에 연결", "Function jack: drag to an object");
  return (
    <button type="button" className={`patch-jack ${connected ? "on" : ""} ${holding ? "holding" : ""} ${target ? "target" : ""}`}
      data-jack={`${side}:${name}`} aria-label={label} title={label} style={color ? { "--jack": color } as React.CSSProperties : undefined}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        pressJack(`${side}:${name}`, e.clientX, e.clientY);
      }} />
  );
}

/** 잭을 눌렀다: 반대쪽 선을 집고 있으면 꽂고, 아니면 이 잭에서 선을 끌기 시작한다 */
function pressJack(jack: string, x: number, y: number): void {
  const [side, ...rest] = jack.split(":");
  const name = rest.join(":");
  const cur = useApp.getState().patchDrag;
  if (cur && cur.from.kind !== side) { finish(cur, jack); return; }   // 집은 선을 반대쪽 잭에 꽂기
  const from: PatchDrag["from"] = side === "obj" ? { kind: "obj", name } : { kind: "fn", id: name };
  useApp.getState().setPatchDrag({ from, x, y, sticky: false, startX: x, startY: y });
}

/** 케이블 끝은 잭 위에 겹친다. 케이블을 눌렀는데 그 아래에 잭이 있으면 잭을 누른 것으로 본다. */
function jackUnder(x: number, y: number): string | null {
  return document.elementsFromPoint(x, y).map((el) => el.closest("[data-jack]")?.getAttribute("data-jack")).find(Boolean) ?? null;
}

/** 놓은 자리의 잭이 반대쪽이면 연결한다 */
function finish(d: PatchDrag, jack: string | null | undefined): boolean {
  if (!jack) return false;
  const [side, ...rest] = jack.split(":");
  const name = rest.join(":");
  if (side === d.from.kind) return false;   // 같은 쪽 잭: 연결하지 않음 (집은 상태는 호출한 쪽이 정한다)
  const app = useApp.getState();
  app.setPatchDrag(null);
  const object = d.from.kind === "obj" ? d.from.name : name;
  const fn = d.from.kind === "fn" ? d.from.id : name;
  app.patchConnect?.(object, fn);
  return true;
}

type P = { x: number; y: number };
function center(el: Element | null): P | null {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return null;   // 접힌 패널 등 화면에 없음
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}
const jackEl = (key: string) => document.querySelector(`[data-jack="${CSS.escape(key)}"]`);

/** 늘어진 케이블 모양 (두 점 사이, 아래로 처짐) */
export function cablePath(a: P, b: P): string {
  const sag = 30 + Math.hypot(b.x - a.x, b.y - a.y) * 0.22;
  return `M${a.x},${a.y} C${a.x},${a.y + sag} ${b.x},${b.y + sag} ${b.x},${b.y}`;
}

/** 화면 전체를 덮는 SVG 하나에 모든 케이블과 끌고 있는 선을 그린다. 왼쪽 클릭은 선택, 휠 클릭은 매핑 해제. */
export function PatchCables({ cables, onCut, onDisconnect }: { cables: Cable[]; onCut: (id: string) => void; onDisconnect?: (id: string) => void }) {
  const drag = useApp((s) => s.patchDrag);
  const objects = useApp((s) => s.objects);
  const objKey = (ref: string) => { const o = findObject(ref, objects); return o ? objectRef(o) : ref; };
  const [pos, setPos] = useState<Record<string, P>>({});
  const last = useRef("");

  // 잭 위치는 레이아웃·스크롤에 따라 바뀌므로 매 프레임 읽고, 바뀌었을 때만 다시 그린다
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const keys = [...new Set([...cables.flatMap((c) => [`obj:${objKey(c.object)}`, `fn:${c.fn}`]),
        ...(drag ? [drag.from.kind === "obj" ? `obj:${drag.from.name}` : `fn:${drag.from.id}`] : [])])];
      const next: Record<string, P> = {};
      for (const k of keys) { const p = center(jackEl(k)); if (p) next[k] = { x: Math.round(p.x), y: Math.round(p.y) }; }
      const s = JSON.stringify(next);
      if (s !== last.current) { last.current = s; setPos(next); }
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [cables, drag?.from, objects]);

  // 끄는 동안 포인터를 따라가고, 놓으면 그 자리의 잭에 꽂는다. 제자리에서 떼면 '집은' 상태로 남는다.
  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => {
      const d = useApp.getState().patchDrag;
      if (d) useApp.getState().setPatchDrag({ ...d, x: e.clientX, y: e.clientY });
    };
    const up = (e: PointerEvent) => {
      const d = useApp.getState().patchDrag;
      if (!d) return;
      if (d.from.kind === "fn" && (e.target as Element | null)?.closest?.("[data-video-map-target]")) return; // video handles its own endpoint
      const jack = jackUnder(e.clientX, e.clientY);
      if (finish(d, jack)) return;
      if (!d.sticky && Math.hypot(e.clientX - d.startX, e.clientY - d.startY) < 6) {
        useApp.getState().setPatchDrag({ ...d, sticky: true, x: e.clientX, y: e.clientY });   // 한 번 눌러 집기
        return;
      }
      useApp.getState().setPatchDrag(null);
    };
    const down = (e: PointerEvent) => {   // 집은 상태에서 잭이 아닌 곳을 누르면 취소
      const target = e.target as Element | null;
      if (useApp.getState().patchDrag?.from.kind === "fn" && target?.closest?.("[data-video-map-target]")) return;
      if (!target?.closest?.("[data-jack]")) useApp.getState().setPatchDrag(null);
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") useApp.getState().setPatchDrag(null); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    if (drag.sticky) window.addEventListener("pointerdown", down);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointerdown", down);
      window.removeEventListener("keydown", key);
    };
  }, [drag !== null, drag?.sticky]);

  const color = (name: string) => name === "@hand" ? "#8aafff" : findObject(name, objects)?.color ?? "#9aa4b2";
  const start = drag ? pos[drag.from.kind === "obj" ? `obj:${drag.from.name}` : `fn:${drag.from.id}`] : undefined;
  return (
    <svg className="patch-cables" aria-hidden="true">
      {cables.map((c) => {
        const a = pos[`obj:${objKey(c.object)}`], b = pos[`fn:${c.fn}`];
        if (!a || !b) return null;
        const d = cablePath(a, b);
        return <g key={c.id} className="cable">
          <path d={d} className="cable-shadow" />
          <path d={d} className="cable-wire" style={{ stroke: color(c.object) }} />
          <path d={d} className="cable-hit"
            onPointerDown={(e) => { if (e.button !== 0) { if (e.button === 1) { e.preventDefault(); e.stopPropagation(); useApp.getState().setPatchDrag(null); } return; } const j = jackUnder(e.clientX, e.clientY); if (j) { e.preventDefault(); e.stopPropagation(); pressJack(j, e.clientX, e.clientY); } }}
            onMouseDown={e => { if (e.button === 1) e.preventDefault(); }}
            onAuxClick={e => { if (e.button === 1) { e.preventDefault(); e.stopPropagation(); onDisconnect?.(c.id); } }}
            onClick={(e) => { if (!jackUnder(e.clientX, e.clientY)) onCut(c.id); }}>
            <title>{t(`${objectLabel(c.object, objects)} → ${allFns().find((f) => f.id === c.fn)?.label() ?? c.fn} · 클릭: 설정·영상 연결 / 휠 클릭: 매핑 해제`, `${objectLabel(c.object, objects)} → ${allFns().find((f) => f.id === c.fn)?.label() ?? c.fn} · click: settings/video connect / middle-click: unmap`)}</title>
          </path>
        </g>;
      })}
      {drag && start && <path d={cablePath(start, { x: drag.x, y: drag.y })} className="cable-wire dragging"
        style={{ stroke: drag.from.kind === "obj" ? color(drag.from.name) : "#e8edf5" }} />}
    </svg>
  );
}
