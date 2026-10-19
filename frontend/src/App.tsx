import { useGameMappingView } from "./gameMapping";
import { BetaBadge } from "./components/BetaBadge";
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
import { HockeyDemo } from "./components/HockeyDemo";
import { PongDemo } from "./components/PongDemo";
import { FruitDemo } from "./components/FruitDemo";
import { DjDemo } from "./components/DjDemo";
import { ObjectPanel } from "./components/ObjectPanel";
import { SourcePanel } from "./components/SourcePanel";
import { VirtualDesktop } from "./components/VirtualDesktop";
import { connection } from "./connection";
import { useApp } from "./store";

import { Topbar } from "./components/Topbar";
import { Panel } from "./components/Panel";
import { Tutorial } from "./components/Tutorial";
import { IdleShowcase } from "./components/IdleShowcase";
import { ResizeHandle, useResizable } from "./components/useResizable";
import { labels, t, useLang } from "./i18n";
import { usePanelDrag, usePanelLayout, type SlotId } from "./panelLayout";

type Demo = "desktop" | "draw" | "racing" | "survival" | "pong" | "fruit" | "dj" | "hockey";
const DEMO_LABEL = labels<Demo>({ racing: ["레이싱", "Racing"], survival: ["좀비 서바이벌", "Zombie Survival"],
  hockey: ["에어 하키", "Air Hockey"], pong: ["퐁", "Pong"], fruit: ["과일 받기", "Fruit Catch"], dj: ["DJ 셋", "DJ Set"],
  desktop: ["가상 데스크톱", "Virtual Desktop"], draw: ["펜·맨손 그리기", "Pen & Hand Drawing"] });
const DEMO_ICON: Record<Demo, string> = { hockey: "🏒", racing: "🏎️", pong: "🏓", fruit: "🍎", survival: "🧟", dj: "🎧", desktop: "🖥️", draw: "✏️" };
const DEMOS: Demo[] = ["racing", "pong", "hockey", "fruit", "survival", "dj", "desktop", "draw"];

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
  const conn = useApp((s) => s.conn);
  const dormant = useApp((s) => s.dormant);
  // 다시 연결을 계속 시도해도 8초 넘게 안 되면 서버가 종료된 것으로 본다 (다시 켜지면 저절로 연결된다)
  const [backendGone, setBackendGone] = useState(false);
  useEffect(() => {
    if (conn === "open") { setBackendGone(false); return; }
    const timer = window.setTimeout(() => setBackendGone(true), 8000);
    return () => window.clearTimeout(timer);
  }, [conn === "open"]);
  const resetBusy = useApp(s => s.resetBusy);
  const resetGeneration = useApp(s => s.resetGeneration);
  useEffect(() => { setDemo("racing"); }, [resetGeneration]);
  const [picked, setDemo] = useState<Demo>("racing");
  useEffect(() => { useGameMappingView.getState().setDj(picked === "dj"); }, [picked]);
  const demos = DEMOS;
  const demo = picked;
  useLang(); // 언어가 바뀌면 화면 전체를 다시 그린다
  const [layout, setLayout] = usePanelLayout();
  const { dragging, drop } = usePanelDrag(layout, setLayout);
  /** 끌어 놓을 자리 표시: 그 패널 위(drop-before) 또는 열 맨 끝 패널 아래(drop-after), 빈 열이면 열 전체 */
  const slotsFor = (col: number) => layout[col]!.map((id, index) => ({ id, index })).filter(({ id }) => id !== "demo").map(({ id, index: k }, visibleIndex, entries) => {
    const n = layout[col]!.length;
    const mark = drop?.col !== col ? "" : drop.index === k ? "drop-before" : (drop.index === n || drop.index === k + 1) && visibleIndex === entries.length - 1 ? "drop-after" : "";
    return <div key={id} data-slot={id} style={{ order: col * 10 + k }} className={`side-slot ${dragging === id ? "slot-dragging" : ""} ${mark}`}>
      {renderSlot(id)}
    </div>;
  });
  const emptyDrop = (col: number) => (drop?.col === col && !layout[col]!.some(id => id !== "demo") ? "drop-empty" : "");
  const renderSlot = (id: SlotId) => {
    switch (id) {
      case "camera": return <CameraView />;
      case "mapping": return <MappingPanel />;
      case "demo": return <Panel title={t("데모", "Demos")} label="데모" className="demo-shell" info={t("왼쪽에서 데모를 고르세요. 게임은 Space 로 시작·일시정지합니다.", "Pick a demo on the left. Space starts / pauses games.")}>
        <div className="demo-split">
          <nav className="demo-nav" role="tablist" aria-orientation="vertical" aria-label={t("데모", "Demos")} data-tour="demos">
            {demos.map((d) => (
              <button key={d} type="button" role="tab" aria-selected={demo === d} className={demo === d ? "active" : ""} data-tour={d === "draw" || d === "desktop" ? undefined : "game-pick"}
                onClick={() => setDemo(d)}><span aria-hidden="true">{DEMO_ICON[d]}</span><span className="demo-nav-text">{DEMO_LABEL[d]}{d === 'draw' && <span className="demo-nav-badge"><BetaBadge /></span>}</span></button>
            ))}
          </nav>
          <div className="demo-stage" data-tour="demo-stage">
            {demo === "desktop" ? <VirtualDesktop /> : demo === "draw" ? <DrawingPad />
              : demo === "survival" ? <SurvivalDemo /> : demo === "pong" ? <PongDemo /> : demo === "hockey" ? <HockeyDemo /> : demo === "fruit" ? <FruitDemo />
                : demo === "dj" ? <DjDemo /> : <RacingDemo />}
          </div>
        </div>
      </Panel>;
      case "real": return <RealOutputPanel />;
      case "hud": return <Hud />;
      case "objects": return <ObjectPanel />;
      case "source": return <SourcePanel />;
      case "mouse": return <MousePanel />;
    }
  };

  return (
    <div className="app">
      <Tutorial />
      <IdleShowcase />
      {/* 서버가 꺼지면(터미널 Ctrl+C 등) 화면 전체를 어둡게 덮고, 다시 연결되면 사라진다 */}
      {dormant && <div className="backend-overlay gone" role="status">
        <div className="backend-gone">
          <b>{dormant === "restarted" ? t("AnyControl이 새 창에서 열렸습니다", "AnyControl opened in a new window") : t("다른 창에서 AnyControl을 열었습니다", "AnyControl was opened in another window")}</b>
          <span>{t("이 창은 연결을 놓았습니다. 이 창을 닫아도 됩니다.", "This window let go of the connection. You can close it.")}</span>
          <button type="button" className="act-go" onClick={() => location.reload()}>{t("이 창에서 계속", "Continue here")}</button>
        </div>
      </div>}
      {!dormant && conn !== "open" && <div className={`backend-overlay ${backendGone ? "gone" : ""}`} role="status" aria-live="polite">
        {backendGone ? <div className="backend-gone">
          <b>{t("백엔드가 종료되었습니다", "Backend has stopped")}</b>
          <span>{t("터미널에서 AnyControl을 다시 실행하면 자동으로 다시 연결됩니다.", "Run AnyControl again from Terminal and this page reconnects automatically.")}</span>
        </div> : <><span className="backend-spinner" aria-hidden="true" />{t("백엔드 연결 중…", "Connecting to backend…")}</>}
      </div>}
      <Topbar />
      <main inert={resetBusy} key={resetGeneration} className="layout" style={{ '--sidebar-width': sidebar.style.width ? `${sidebar.style.width}px` : '640px' } as import('react').CSSProperties}>
        <div className={`main-col ${emptyDrop(0)}`} data-col={0}>{slotsFor(0)}</div>
        <aside className="side">
          <ResizeHandle label={t("설정 열", "Settings column")} grip={sidebar.grip} className="sidebar-resize" />
          {/* 두 열. 좁으면 한 열로 합치고 order 로 배치 순서를 지킨다 */}
          <div className={`side-col ${emptyDrop(1)}`} data-col={1}>{slotsFor(1)}</div>
          <div className={`side-col ${emptyDrop(2)}`} data-col={2}>{slotsFor(2)}</div>
        </aside>
        <div className="demo-fullwidth">{renderSlot("demo")}</div>
      </main>
    </div>
  );
}
