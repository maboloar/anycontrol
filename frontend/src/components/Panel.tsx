import { ResizeHandle, useResizable } from "./useResizable";
import { useEffect, useId, useState, type ReactNode } from "react";
import { Info } from "./Info";

/** 접어도 자식은 유지한다. 추적·그림·설정 상태가 최소화 때문에 초기화되지 않는다. */
export function Panel({ title, label = title, children, className = "", detail, info, tour }: {
  title: string; label?: string; children: ReactNode; className?: string; detail?: ReactNode;
  /** 제목 옆 정보 아이콘(ⓘ)의 설명 */ info?: ReactNode;
  /** 튜토리얼이 가리킬 이름 (data-tour) */ tour?: string;
}) {
  const id = useId();
  const key = `anycontrol.panel.${label}`;
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(key) === "collapsed"; } catch { return false; }
  });
  const resize = useResizable(`${key}.size`);
  useEffect(() => {
    const reset = () => { setCollapsed(false); try { localStorage.removeItem(key); } catch { /* 화면만 복원 */ } };
    window.addEventListener('anycontrol.layout.reset', reset);
    return () => window.removeEventListener('anycontrol.layout.reset', reset);
  }, [key]);
  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    try { localStorage.setItem(key, next ? "collapsed" : "expanded"); } catch { /* 저장 불가여도 동작 */ }
  };
  return <section className={`panel ${className} ${collapsed ? "minimized" : ""}`} aria-label={label} data-tour={tour} style={{ ...resize.style, ...(collapsed ? { height: undefined } : {}) }}>
    <div className="panel-header">
      <h2>{title}{info && <Info wide>{info}</Info>}{!collapsed && detail && <small>{detail}</small>}</h2>
      <button type="button" className="minimize" aria-label={`${title} ${collapsed ? "펼치기" : "최소화"}`}
        aria-expanded={!collapsed} aria-controls={id} onClick={toggle} title={collapsed ? "펼치기" : "한 줄로 최소화"}>
        {collapsed ? "+" : "−"}
      </button>
    </div>
    <div id={id} className="panel-body" hidden={collapsed}>{children}</div>
    {!collapsed && <ResizeHandle label={title} grip={resize.grip} />}
  </section>;
}
