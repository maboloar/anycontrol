import { Panel } from "./Panel";
import { useEffect, useRef, useState } from "react";
import { connection } from "../connection";
import type { FrameState } from "../protocol";
import { t } from "../i18n";

export interface VMouse { x: number; y: number; left: boolean; right: boolean; source: "hand" | "mapping" | null }
const KEY_LOG_MAX = 40;

/** 다음 가상 마우스 위치. 손·물체 마우스는 절대 좌표, 매핑 마우스는 속도(-1..1)를 dt 동안 누적한다. */
export function nextMouse(prev: VMouse, s: FrameState, dt: number): VMouse {
  const m = s.mouse;
  if (m && m.mode !== "off") return { x: m.x, y: m.y, left: m.left, right: m.right, source: "hand" };
  const mm = s.mapping?.computed.mouse;
  if (!mm) return prev.source ? { ...prev, left: false, right: false, source: null } : prev;
  const clamp = (v: number) => Math.max(0, Math.min(1, v));
  return { x: clamp(prev.x + mm.move[0] * dt * 0.6), y: clamp(prev.y + mm.move[1] * dt * 0.6),
    left: mm.left, right: mm.right, source: "mapping" };
}

/** 새로 눌린 키만 차례로 돌려준다 (내보내는 중이면 key_events, 보기만이면 계산된 키 집합의 차이). */
export function pressedKeys(prevKeys: string[], s: FrameState): { down: string[]; keys: string[] } {
  const c = s.controller;
  if (c?.mode === "send") return { down: c.key_events.filter((e) => e.type === "down").map((e) => e.key), keys: c.keys };
  const keys = s.mapping?.computed.keys ?? [];
  return { down: keys.filter((k) => !prevKeys.includes(k)), keys };
}

/** 매핑·손 입력이 만드는 마우스·키보드 출력을 앱 안에서 보여 준다. */
export function VirtualIoView() {
  const [mouse, setMouse] = useState<VMouse>({ x: 0.5, y: 0.5, left: false, right: false, source: null });
  const [log, setLog] = useState<string[]>([]);
  const [held, setHeld] = useState<string[]>([]);
  const last = useRef<{ t: number; keys: string[]; mouse: VMouse }>({ t: 0, keys: [], mouse });
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => connection.onMessage((type, data) => {
    if (type !== "state") return;
    const s = data as unknown as FrameState;
    const now = performance.now();
    const l = last.current;
    const dt = l.t ? Math.min(0.1, (now - l.t) / 1000) : 0;
    const m = nextMouse(l.mouse, s, dt);
    const { down, keys } = pressedKeys(l.keys, s);
    last.current = { t: now, keys, mouse: m };
    if (m !== l.mouse) setMouse(m);
    setHeld((h) => (h.join() === keys.join() ? h : keys));
    if (down.length) setLog((g) => [...g, ...down].slice(-KEY_LOG_MAX));
  }), []);
  useEffect(() => { logRef.current?.scrollTo({ left: logRef.current.scrollWidth }); }, [log]);
  return <>
    <Panel title={t("가상 마우스", "Virtual mouse")} label="가상 마우스 패널" className="pad-panel">
      <div className="vmouse" role="img" aria-label={`${t("가상 마우스", "Virtual mouse")} ${Math.round(mouse.x * 100)}, ${Math.round(mouse.y * 100)}`}>
        <div className="vmouse-grid" />
        {mouse.source && <div className={`vmouse-dot ${mouse.left ? "l" : ""} ${mouse.right ? "r" : ""}`}
          style={{ left: `${mouse.x * 100}%`, top: `${mouse.y * 100}%` }} />}
      </div>
      <p className="small muted">{mouse.source
        ? `x ${mouse.x.toFixed(2)} · y ${mouse.y.toFixed(2)} · ${mouse.source === "hand" ? t("마우스 모드", "Mouse mode") : t("매핑", "Mapping")}${mouse.left ? t(" · 왼쪽 클릭", " · Left click") : ""}${mouse.right ? t(" · 오른쪽 클릭", " · Right click") : ""}`
        : t("마우스 입력 없음", "No mouse input")}</p>
    </Panel>
    <Panel title={t("가상 키보드", "Virtual keyboard")} label="가상 키보드 패널" className="pad-panel">
      <div className="vkeys" ref={logRef} aria-live="polite" aria-label={t("입력된 키", "Pressed keys")}>
        {log.length ? log.map((k, i) => <kbd key={i} className={held.includes(k) && i === log.lastIndexOf(k) ? "on" : ""}>{k}</kbd>)
          : <span className="muted small">{t("입력을 기다리는 중", "Waiting for input")}</span>}
      </div>
      {log.length > 0 && <button type="button" className="small" onClick={() => setLog([])}>{t("지우기", "Clear")}</button>}
    </Panel>
  </>;
}
