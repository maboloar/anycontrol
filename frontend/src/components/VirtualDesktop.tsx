import { useApp } from "../store";
import { Panel } from "./Panel";
import { useEffect, useRef, useState } from "react";
import { connection } from "../connection";
import type { FrameState, MouseState } from "../protocol";
import { t as tr } from "../i18n";

/**
 * 가상 데스크톱: 실제 OS 입력 대신 이 안의 커서가 움직인다.
 * - 버튼 3개: 왼쪽 클릭 횟수
 * - 오른쪽 클릭: 커서 위치에 메뉴
 * - 목록: 스크롤
 * - 카드: 왼쪽 버튼을 누른 채 움직이면 끌기
 */
export function VirtualDesktop() {
  /** 맨손·물체 마우스가 꺼져 있으면 연습장을 어둡게 잠그고 켜고 오라고 안내한다 */
  const mouseOff = useApp((s) => (s.mouseInfo?.settings.mode ?? "off") === "off");
  const areaRef = useRef<HTMLDivElement>(null);
  const [cursor, setCursor] = useState({ x: 0.5, y: 0.5, left: false, right: false, active: false });
  const [counts, setCounts] = useState([0, 0, 0]);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [card, setCard] = useState({ x: 0.72, y: 0.62 });
  const [log, setLog] = useState<string[]>([]);
  const listRef = useRef<HTMLUListElement>(null);
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  const cardRef = useRef(card);
  cardRef.current = card;

  useEffect(() => {
    const push = (s: string) => setLog((l) => [s, ...l].slice(0, 5));
    const hit = (x: number, y: number): Element | null => {
      const area = areaRef.current;
      if (!area) return null;
      const r = area.getBoundingClientRect();
      return document.elementFromPoint(r.left + x * r.width, r.top + y * r.height);
    };
    return connection.onMessage((type, data) => {
      if (type !== "state") return;
      const m = (data as unknown as FrameState).mouse as MouseState | undefined;
      if (!m || m.mode === "off") {
        setCursor((c) => (c.active ? { ...c, active: false } : c));
        drag.current = null;
        return;
      }
      setCursor({ x: m.x, y: m.y, left: m.left, right: m.right, active: true });
      if (drag.current) setCard({ x: m.x - drag.current.dx, y: m.y - drag.current.dy });
      if (m.scroll && listRef.current) listRef.current.scrollTop += m.scroll * 18;
      for (const ev of m.events) {
        const el = hit(ev.x, ev.y);
        if (ev.button === "left" && ev.type === "down") {
          setMenu(null);
          if (el?.closest("[data-card]")) {
            drag.current = { dx: ev.x - cardRef.current.x, dy: ev.y - cardRef.current.y };
            push(tr("카드 잡음", "Card grabbed"));
          }
        } else if (ev.button === "left" && ev.type === "up") {
          if (drag.current) {
            drag.current = null;
            push(tr("카드 놓음", "Card dropped"));
            continue;
          }
          const btn = el?.closest("[data-btn]");
          if (btn) {
            const i = Number(btn.getAttribute("data-btn"));
            setCounts((c) => c.map((v, k) => (k === i ? v + 1 : v)));
            push(tr(`버튼 ${i + 1} 클릭`, `Button ${i + 1} clicked`));
          } else {
            const item = el?.closest("[data-menu]");
            if (item) push(`${tr("메뉴", "Menu")}: ${item.textContent}`);
          }
        } else if (ev.button === "right" && ev.type === "down") {
          setMenu({ x: ev.x, y: ev.y });
          push(tr("오른쪽 클릭", "Right click"));
        }
      }
    });
  }, []);

  return (
    <Panel title={tr("가상 데스크톱", "Virtual desktop")} label="가상 데스크톱 데모" className="demo" detail={tr("실제 OS 입력은 보내지 않습니다", "No real OS input is sent")} info={tr(<>맨손·물체 마우스의 가상 커서로 창을 끌고 클릭해 보는 연습장입니다.</>, <>Practice dragging and clicking with the virtual cursor from hand or object mouse.</>)}>
      <div ref={areaRef} className="vdesk">
        <div className="vdesk-buttons">
          {counts.map((c, i) => (
            <div key={i} data-btn={i} className="vbtn">{tr("버튼", "Button")} {i + 1}<b>{c}</b></div>
          ))}
        </div>
        <ul ref={listRef} className="vlist" aria-label={tr("스크롤 목록", "Scroll list")}>
          {Array.from({ length: 40 }, (_, i) => <li key={i}>{tr("항목", "Item")} {i + 1}</li>)}
        </ul>
        <div data-card className="vcard" style={{ left: `${card.x * 100}%`, top: `${card.y * 100}%` }}>{tr("끌어 보세요", "Drag me")}</div>
        {menu && (
          <ul className="vmenu" style={{ left: `${menu.x * 100}%`, top: `${menu.y * 100}%` }}>
            {tr(["복사", "붙여넣기", "삭제"], ["Copy", "Paste", "Delete"]).map((m) => <li key={m} data-menu>{m}</li>)}
          </ul>
        )}
        {cursor.active && (
          <div className={`vcursor ${cursor.left ? "l" : ""} ${cursor.right ? "r" : ""}`}
            style={{ left: `${cursor.x * 100}%`, top: `${cursor.y * 100}%` }} aria-hidden="true" />
        )}
        {mouseOff ? <div className="vdesk-lock" role="status">
          <b>{tr("먼저 마우스를 켜 주세요", "Turn on a mouse first")}</b>
          <span>{tr("마우스 패널에서 [맨손 마우스] 또는 [물체 마우스]를 켜면 여기서 커서로 창을 끌고 클릭해 볼 수 있어요.", "In the Mouse panel, turn on [Hand mouse] or [Object mouse] to drag and click here with the cursor.")}</span>
          <button type="button" className="act-go" onClick={() => document.querySelector('[data-tour="mouse"]')?.scrollIntoView({ behavior: "smooth", block: "center" })}>{tr("마우스 패널로 이동", "Go to the Mouse panel")}</button>
        </div> : !cursor.active && <p className="vdesk-hint">{tr("커서를 찾는 중… 손이나 물체가 카메라에 보이게 해 주세요.", "Looking for the cursor… keep your hand or object in view.")}</p>}
      </div>
      <ol className="small muted vlog" aria-live="polite">{log.map((l, i) => <li key={i}>{l}</li>)}</ol>
    </Panel>
  );
}
