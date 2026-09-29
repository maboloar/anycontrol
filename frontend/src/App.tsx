import { useEffect, useState } from "react";
import { stopAll } from "./api";
import { CameraView } from "./components/CameraView";
import { DrawingPad } from "./components/DrawingPad";
import { RealOutputPanel } from "./components/RealOutputPanel";
import { Hud } from "./components/Hud";
import { MappingPanel } from "./components/MappingPanel";
import { MousePanel } from "./components/MousePanel";
import { SurvivalDemo } from "./components/SurvivalDemo";
import { RacingDemo } from "./components/RacingDemo";
import { ObjectPanel } from "./components/ObjectPanel";
import { SourcePanel } from "./components/SourcePanel";
import { VirtualDesktop } from "./components/VirtualDesktop";
import { connection } from "./connection";
import { useApp } from "./store";

import { DisplayControls } from "./components/DisplayControls";
import { Tutorial } from "./components/Tutorial";
import { HeaderBuddy } from "./components/CameraBuddy";
import { ResizeHandle, useResizable } from "./components/useResizable";

type Demo = "desktop" | "draw" | "mapping" | "racing" | "survival";
const DEMOS: [Demo, string][] = [["mapping", "매핑·게임패드"], ["racing", "레이싱"], ["survival", "좀비 서바이벌"], ["desktop", "가상 데스크톱"], ["draw", "펜·맨손 그리기"]];

export function App() {
  useEffect(() => {
    connection.connect();
    const onPageHide = () => connection.close();
    const onPageShow = () => connection.connect();
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("pageshow", onPageShow);
      connection.close();
    };
  }, []);
  // ESC = 긴급 정지 (어디서든)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape")
        stopAll().then((m) => {
          const s = useApp.getState();
          s.setMouseInfo(m);
          if (s.mappingInfo) s.setMappingInfo({ ...s.mappingInfo, mode: "observe" });
        }, () => undefined);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  // 키를 바꿔 예전 한 열 폭(320px) 저장값이 두 열을 좁히지 않게 한다
  const sidebar = useResizable('anycontrol.sidebar2.size', { minWidth: 260, widthOnly: true, reverseX: true });
  const version = useApp((s) => s.serverVersion);
  const [demo, setDemo] = useState<Demo>("mapping");

  return (
    <div className="app">
      <Tutorial />
      <header className="topbar">
        <h1 className="brand"><HeaderBuddy />AnyControl</h1>
        <span className="muted">{version ? `backend v${version}` : ""}</span>
        <DisplayControls />
        <button type="button" className="help-btn" data-tour="help" title="시작 안내를 다시 봅니다"
          onClick={() => useApp.getState().setTour(true)}>? 안내</button>
      </header>
      <main className="layout" style={{ '--sidebar-width': sidebar.style.width ? `${sidebar.style.width}px` : '640px' } as import('react').CSSProperties}>
        <div className="main-col">
          <CameraView />
          <div className="row" role="tablist" aria-label="데모" data-tour="demos">
            {DEMOS.map(([d, label]) => (
              <button key={d} type="button" role="tab" aria-selected={demo === d} className={demo === d ? "active" : ""}
                onClick={() => setDemo(d)}>{label}</button>
            ))}
          </div>
          {demo === "desktop" ? <VirtualDesktop /> : demo === "draw" ? <DrawingPad />
            : demo === "mapping" ? <MappingPanel /> : demo === "survival" ? <SurvivalDemo /> : <RacingDemo />}
        </div>
        <aside className="side">
          <ResizeHandle label="설정 열" grip={sidebar.grip} className="sidebar-resize" />
          {/* 두 열: 왼쪽 = 매번 쓰는 입력 설정, 오른쪽 = 준비·상태. 좁으면 한 열로 합치고 order 로 중요도순 */}
          <div className="side-col">
            <div className="side-slot" style={{ order: 1 }}><RealOutputPanel /></div>
            <div className="side-slot" style={{ order: 3 }}><MousePanel /></div>
          </div>
          <div className="side-col">
            <div className="side-slot" style={{ order: 2 }}><SourcePanel /></div>
            <div className="side-slot" style={{ order: 4 }}><ObjectPanel /></div>
            <div className="side-slot" style={{ order: 5 }}><Hud /></div>
          </div>
        </aside>
      </main>
    </div>
  );
}
