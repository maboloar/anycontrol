import { allowGuidePrompt, showGuidePrompt } from "../guidePrompt";
import { resetAllSettings } from "../resetSettings";
import { useEffect, useRef, useState } from "react";
import { getPresence } from "../api";
import { t } from "../i18n";
import { useApp, type LiveState } from "../store";

export const IDLE_MS = 120_000;
const PRESENCE_MS = 350;

/** 카메라로 하는 입력(맨손·물체 커서 이동, 매핑 값 변화)이 있었나. 부스에서는 마우스 없이 물체로만 노는 사람도 있다. */
export function liveActivity(prev: LiveState | null, next: LiveState): boolean {
  const a = prev?.mouse, b = next.mouse;
  if (b && b.mode !== "off") {
    if (b.hand_visible && b.mode === "hand") return true;
    if (a && b.cursor_active && Math.hypot((b.x ?? 0) - (a.x ?? 0), (b.y ?? 0) - (a.y ?? 0)) > 0.01) return true;
  }
  const pv = new Map(prev?.mapping?.live.map((l) => [l.id, l.value ?? 0]) ?? []);
  return (next.mapping?.live ?? []).some((l) => l.active && Math.abs((l.value ?? 0) - (pv.get(l.id) ?? 0)) > 0.05);
}

/** 창이 열린 채 120초 동안 입력이 전혀 없으면 화면을 어둡게 덮고 시연 영상을 튼다 (영상이 준비될 때까지는 안내 문구).
 * 마우스 움직임·클릭·키보드·휠, 카메라 입력 활동, 또는 카메라에 사람이 가까이 오면(Depth Anything, 배경 제외) 바로 닫힌다. */
export function IdleShowcase() {
  const enabled = useApp((s) => s.idleShowcase);
  const idleMs = useApp((s) => s.idleSeconds) * 1000;
  const [show, setShow] = useState(false);
  const [resetErr, setResetErr] = useState("");
  const wasShowing = useRef(false);
  const showing = useRef(show); showing.current = show;
  const wake = () => { const returning = showing.current; showing.current = false; lastInput.current = Date.now(); setShow(false); if (returning) queueMicrotask(() => showGuidePrompt(true)); };
  useEffect(() => {
    if (show && !wasShowing.current) allowGuidePrompt();
    if (show && !wasShowing.current) void resetAllSettings().then(() => setResetErr(""), e => setResetErr(String(e)));
    wasShowing.current = show;
  }, [show]);
  const lastInput = useRef(Date.now());

  useEffect(() => {
    if (!enabled) { setShow(false); return; }
    const events = ["pointermove", "pointerdown", "keydown", "wheel", "touchstart"] as const;
    events.forEach((e) => window.addEventListener(e, wake, { passive: true }));
    const unsub = useApp.subscribe((s, p) => { if (s.live !== p.live && liveActivity(p.live, s.live)) wake(); });
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && Date.now() - lastInput.current >= idleMs) setShow(true);
    }, 1000);
    return () => { events.forEach((e) => window.removeEventListener(e, wake)); unsub(); window.clearInterval(timer); };
  }, [enabled, idleMs]);

  // 시연 화면이 떠 있는 동안: 뜬 순간의 장면을 배경으로 잡고, 사람이 가까이 오면 닫는다
  useEffect(() => {
    if (!show) return;
    let alive = true, timer = 0, first = true;
    const poll = async () => {
      try {
        const r = await getPresence(first);
        first = false;
        if (alive && r.present) { wake(); return; }
      } catch { /* 서버·모델 없음: 마우스·키보드로만 복귀 */ }
      if (alive) timer = window.setTimeout(() => void poll(), PRESENCE_MS);
    };
    void poll();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [show]);

  if (!show) return null;
  return (
    <div className="idle-showcase" role="dialog" aria-label={t("시연 영상", "Demo video")}>
      {resetErr && <p className="error" role="alert">{resetErr}</p>}
      <div className="idle-placeholder">시연영상placeholder</div>
      <p className="idle-hint">{t("마우스를 움직이거나 카메라 앞으로 다가오면 바로 체험할 수 있어요", "Move the mouse or step up to the camera to try it")}</p>
    </div>
  );
}
