import { ActionIcon } from "./ActionIcon";
import { useEffect, useState } from 'react';

const FONT_KEY = 'anycontrol.font-size';
export function DisplayControls() {
  const [fontSize, setFontSize] = useState(() => {
    try { const n = Number(localStorage.getItem(FONT_KEY)); return n >= 12 && n <= 22 ? n : 14; }
    catch { return 14; }
  });
  useEffect(() => {
    document.documentElement.style.fontSize = `${fontSize}px`;
    try { localStorage.setItem(FONT_KEY, String(fontSize)); } catch { /* 표시 설정만 적용 */ }
  }, [fontSize]);
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
  return <div className="display-controls" role="group" aria-label="화면 표시 설정">
    <button type="button" className="act-reset" onClick={resetLayout} title="창 크기·최소화·글씨 크기를 기본값으로 복원"><ActionIcon name="reset" />화면 초기화</button>
    <span>글씨</span>
    <button type="button" aria-label="글씨 작게" disabled={fontSize <= 12} onClick={() => setFontSize(n => Math.max(12, n - 1))}>−</button>
    <output aria-label="글씨 크기">{fontSize}px</output>
    <button type="button" aria-label="글씨 크게" disabled={fontSize >= 22} onClick={() => setFontSize(n => Math.min(22, n + 1))}>+</button>
  </div>;
}
