import { GUIDE_IDLE_MS, useGuidePrompt, hideGuidePrompt, showGuidePrompt, dismissGuidePrompt } from "../guidePrompt";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { stopAll } from "../api";
import { t } from "../i18n";
import { useRealStatus } from "../realOutputState";
import { useApp } from "../store";
import { ActionIcon } from "./ActionIcon";
import { HeaderBuddy } from "./CameraBuddy";
import { DisplayControls } from "./DisplayControls";
import { DevBadge, DevModeToggle, FloatingCameraToggle, IdleShowcaseToggle } from "./DevMode";

export function Topbar() {
  useRealStatus();
  const prompt = useGuidePrompt(s => s.visible);
  const advanced = useApp(s => s.devMode);
  useEffect(() => {
    let last = Date.now();
    let dismissTimer: number | null = null;
    const activity = () => {
      last = Date.now();
      if (useGuidePrompt.getState().visible && dismissTimer === null) {
        // Let a new visitor finish reading the invitation after their first input.
        dismissTimer = window.setTimeout(() => { hideGuidePrompt(); dismissTimer = null; }, 10_000);
      }
    };
    const events = ["pointermove", "pointerdown", "keydown", "wheel", "touchstart"] as const;
    events.forEach(e => window.addEventListener(e, activity, { passive: true }));
    const timer = window.setInterval(() => { if (document.visibilityState === "visible" && Date.now() - last >= GUIDE_IDLE_MS && !useApp.getState().tourOpen) showGuidePrompt(); }, 500);
    return () => {
      events.forEach(e => window.removeEventListener(e, activity));
      window.clearInterval(timer);
      if (dismissTimer !== null) window.clearTimeout(dismissTimer);
    };
  }, []);
  const info = useApp(s => s.live.real), version = useApp(s => s.serverVersion), conn = useApp(s => s.conn);
  const state = conn === "open" ? info?.state ?? "off" : "off";
  const active = state !== "off";
  const ref = useRef<HTMLElement>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (!active) setErr(null); }, [active]);
  useLayoutEffect(() => {
    if (!active) return;
    const update = () => document.documentElement.style.setProperty("--float-min-top", `${(ref.current?.getBoundingClientRect().height ?? 0) + 8}px`);
    update();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    if (ref.current) observer?.observe(ref.current);
    window.addEventListener("resize", update);
    return () => { observer?.disconnect(); window.removeEventListener("resize", update); document.documentElement.style.removeProperty("--float-min-top"); };
  }, [active]);
  const stop = async () => {
    try { await stopAll(); setErr(null); }
    catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
  };
  return <header ref={ref} className={`topbar ${prompt ? "guide-invite" : ""} ${active ? `real-active ${state}` : ""}`}>
    <div className="topbar-brand">
      <div className="topbar-title"><h1 className="brand"><HeaderBuddy />AnyControl</h1>{advanced && <small className="topbar-meta"><DevBadge />{version && <span className="topbar-version">backend v{version}</span>}</small>}</div>
      <button type="button" className="help-btn" data-tour="help" title={t("시작 안내를 다시 봅니다", "Show the getting-started tour again")} onClick={() => { hideGuidePrompt(); useApp.getState().setTour(true); }}>? {t("안내", "Guide")}</button>
      {prompt && <span className="guide-invite-text" role="status">
        <span>{t("← 처음이신가요? 안내 버튼을 눌러 시작해 보세요", "← First time? Press Guide to get started")}</span>
        <button type="button" className="guide-invite-x" aria-label={t("안내 문구 닫기", "Close this hint")} title={t("닫기 (다음 시연 화면까지 다시 뜨지 않아요)", "Close (stays hidden until the next demo screen)")} onClick={dismissGuidePrompt}>×</button>
      </span>}
    </div>
    {active && <div className="topbar-real-status" role="alert" aria-atomic="true">
      <span>{state === "arming" ? t(`실제 입력 ${Math.ceil(info?.remaining_s ?? 0)}초 뒤 켜짐`, `Real input starts in ${Math.ceil(info?.remaining_s ?? 0)}s`) : t("실제 입력 켜짐 — ESC(어디서든)로 정지", "Real input on — press ESC anywhere to stop")}</span>
      <button type="button" className="topbar-stop" onClick={() => void stop()}><ActionIcon name="stop" />{t("정지 (ESC)", "Stop (ESC)")}</button>
      {err && <span className="topbar-stop-error">{err}</span>}
    </div>}
    <div className="topbar-controls">
      <DisplayControls />

      <IdleShowcaseToggle /><FloatingCameraToggle /><DevModeToggle />
    </div>
  </header>;
}
