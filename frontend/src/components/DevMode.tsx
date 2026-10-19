import { useEffect, useState } from "react";
import { t } from "../i18n";
import { useApp } from "../store";
import { ActionIcon } from "./ActionIcon";

/** 상단 '안내' 옆의 고급 모드 버튼. 켜면 자잘한 설정·실험 기능·개발용 보기가 모두 나타난다 (내부 이름은 devMode). */
export function DevModeToggle() {
  const devMode = useApp((s) => s.devMode);
  return (
    <button type="button" className={`dev-btn dev-toggle ${devMode ? "active" : ""}`} aria-pressed={devMode}
      aria-label={t("고급 모드", "Advanced mode")}
      title={devMode ? t("고급 모드 끄기 (기본 모드로)", "Turn advanced mode off (basic mode)") : t("고급 모드 켜기: 세부 설정·실험 기능 보기", "Turn advanced mode on: detailed settings and experimental features")}
      onClick={() => useApp.getState().setDevMode(!devMode)}><ActionIcon name="wrench" />{devMode ? t("고급", "Advanced") : t("기본", "Basic")}</button>
  );
}

/** 'AnyControl' 제목 옆 표시. 고급 모드일 때만 나온다. */
export function DevBadge() {
  const devMode = useApp((s) => s.devMode);
  return devMode ? <span className="dev-badge">{t("고급 모드", "Advanced mode")}</span> : null;
}

/** 고급 모드: 120초 무입력 시연 화면 켜기·끄기 (발표 중에는 끄면 화면이 어두워지지 않는다) */
export function IdleShowcaseToggle() {
  const devMode = useApp((s) => s.devMode);
  const on = useApp((s) => s.idleShowcase);
  const secs = useApp((s) => s.idleSeconds);
  const [draft, setDraft] = useState(String(secs));
  useEffect(() => setDraft(String(secs)), [secs]);
  if (!devMode) return null;
  const commit = () => { const n = Math.round(Number(draft)); if (n >= 5 && n <= 3600) useApp.getState().setIdleSeconds(n); else setDraft(String(secs)); };
  return (
    <label className="check small dev-check" title={t(`창이 열린 채 ${secs}초 동안 입력이 없으면 시연 영상 화면을 띄웁니다`, `Show the demo video screen after ${secs} s without input`)}>
      <input type="checkbox" checked={on} onChange={(e) => useApp.getState().setIdleShowcase(e.target.checked)} />
      <input type="number" className="idle-secs" min={5} max={3600} value={draft} aria-label={t("시연 화면까지 초", "Seconds before demo screen")}
        onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") commit(); }} />
      {t("초 시연", "s demo")}
    </label>
  );
}

/** 고급 모드: 실시간 카메라 호버링(스크롤하면 뜨는 작은 카메라 창) 켜기·끄기 */
export function FloatingCameraToggle() {
  const devMode = useApp((s) => s.devMode);
  const on = useApp((s) => s.floatingCamera);
  if (!devMode) return null;
  return (
    <label className="check small dev-check" title={t("카메라 미리보기가 스크롤로 가려지면 작은 실시간 카메라 창을 띄웁니다", "Show a small live camera window when the preview scrolls out of view")}>
      <input type="checkbox" checked={on} onChange={(e) => useApp.getState().setFloatingCamera(e.target.checked)} />
      {t("카메라 호버링", "Camera hover")}
    </label>
  );
}
