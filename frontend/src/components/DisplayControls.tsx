import { resetAllSettings } from "../resetSettings";
import { useApp } from "../store";
import { ActionIcon } from "./ActionIcon";
import { useEffect, useRef, useState } from 'react';
import { LANGS, setLang, t, useLang } from '../i18n';

const FONT_KEY = 'anycontrol.font-size';
export function DisplayControls() {
  const busy = useApp(s => s.resetBusy);
  const [armed, setArmed] = useState(false), [err, setErr] = useState("");
  useEffect(() => { if (!armed) return; const id = window.setTimeout(() => setArmed(false), 4000); return () => window.clearTimeout(id); }, [armed]);
  const [fontSize, setFontSize] = useState(() => {
    try { const n = Number(localStorage.getItem(FONT_KEY)); return n >= 12 && n <= 22 ? n : 14; }
    catch { return 14; }
  });
  useEffect(() => {
    document.documentElement.style.fontSize = `${fontSize}px`;
    try { localStorage.setItem(FONT_KEY, String(fontSize)); } catch { /* 표시 설정만 적용 */ }
  }, [fontSize]);
  useEffect(() => { const reset = () => setFontSize(14); window.addEventListener("anycontrol.settings.reset", reset); return () => window.removeEventListener("anycontrol.settings.reset", reset); }, []);
  const resetSizes = () => {
    // 현재 열리지 않은 데모의 저장 크기도 함께 초기화한다.
    try { Object.keys(localStorage).filter(k => k.startsWith('anycontrol.') && k.endsWith('.size')).forEach(k => localStorage.removeItem(k)); } catch { /* 활성 창은 이벤트로 복원 */ }
    window.dispatchEvent(new Event('anycontrol.resize.reset'));
  };
  const resetLayout = () => {
    resetSizes(); setFontSize(14);
    try { Object.keys(localStorage).filter(k => k.startsWith('anycontrol.panel.') && !k.endsWith('.size')).forEach(k => localStorage.removeItem(k)); } catch { /* 활성 패널은 이벤트로 복원 */ }
    window.dispatchEvent(new Event('anycontrol.layout.reset'));
  };
  return <div className="display-controls" role="group" aria-label={t("화면 표시 설정", "Display settings")}>
    <button type="button" className="dc-reset" onClick={resetLayout}
      title={t("창 크기·최소화·글씨 크기를 기본값으로 복원", "Restore window sizes, collapsed panels and text size")}>
      <ActionIcon name="reset" />{t("배치 초기화", "Reset layout")}</button>
    <button type="button" className={`dc-reset-all danger delete-all ${armed ? "armed" : ""}`} aria-live="polite" disabled={busy} onBlur={() => setArmed(false)} onClick={async () => {
      if (!armed) { setArmed(true); return; } setArmed(false);
      try { await resetAllSettings(); setErr(""); } catch (e) { setErr(String(e)); }
    }}><ActionIcon name="reset" />{busy ? t("초기화 중…", "Resetting…") : armed ? t("정말 모든 세팅 초기화?", "Reset all settings? Press again") : t("모든 세팅 초기화", "Reset all settings")}</button>
    {err && <span className="error small" role="alert">{err}</span>}
    <div className="dc-font" role="group" aria-label={t("글씨 크기 조절", "Text size")}>
      <button type="button" aria-label={t("글씨 작게", "Smaller text")} disabled={fontSize <= 12} onClick={() => setFontSize(n => Math.max(12, n - 1))}>A<small>−</small></button>
      <output aria-label={t("글씨 크기", "Text size")}>{fontSize}</output>
      <button type="button" aria-label={t("글씨 크게", "Larger text")} disabled={fontSize >= 22} onClick={() => setFontSize(n => Math.min(22, n + 1))}>A<small>+</small></button>
    </div>
    <LanguageMenu />
  </div>;
}

/** 지구본 버튼: 누르면 언어 목록이 열린다. */
function LanguageMenu() {
  const lang = useLang();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('pointerdown', close);
    window.addEventListener('keydown', close);
    return () => { window.removeEventListener('pointerdown', close); window.removeEventListener('keydown', close); };
  }, [open]);
  return <div className="dc-lang" ref={ref}>
    <button type="button" className="dc-globe" aria-haspopup="menu" aria-expanded={open}
      aria-label={t("언어 선택", "Language")} title={t("언어 선택", "Language")} onClick={() => setOpen(o => !o)}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9s1.3-6.4 3.8-9Z" />
      </svg>
      <span>{lang.toUpperCase()}</span>
    </button>
    {open && <ul className="dc-lang-menu" role="menu">
      {LANGS.map(([code, name]) => <li key={code} role="none">
        <button type="button" role="menuitemradio" aria-checked={lang === code}
          onClick={() => { setLang(code); setOpen(false); }}>{name}{lang === code && <ActionIcon name="check" />}</button>
      </li>)}
    </ul>}
  </div>;
}
