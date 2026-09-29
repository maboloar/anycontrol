import { ActionIcon } from "./ActionIcon";
import { useEffect, useState } from 'react';
import { getTracking, putTracking, putPlayback, stopAll } from '../api';
import { useApp } from '../store';
import { Info } from './Info';

export function CameraTools() {
  const { conn, inputMirror, setInputMirror, viewFlip, overlays, setView, telemetry } = useApp();
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (conn === 'open') getTracking().then(i => setInputMirror(!!i.input_mirror), e => setErr(String(e))); }, [conn]);
  const mirror = async () => {
    setBusy(true);
    try { const r = await putTracking({ input_mirror: !inputMirror }); setInputMirror(!!r.input_mirror); setErr(''); }
    catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  return <div className="camera-tools">
    <div className="row">
      <button type="button" className={telemetry?.source?.paused ? "act-go" : "act-pause"} disabled={conn !== 'open'} onClick={() => void putPlayback(!telemetry?.source?.paused).catch(e => setErr(String(e)))}><ActionIcon name={telemetry?.source?.paused ? 'play' : 'pause'} />{telemetry?.source?.paused ? '영상 재생' : '영상 정지'}</button>
      <button type="button" className="act-config" aria-pressed={viewFlip} onClick={() => setView({ viewFlip: !viewFlip })}><ActionIcon name="flip" />영상 좌우 반전</button>
      <button type="button" className="act-config" aria-pressed={inputMirror} disabled={busy || conn !== 'open'} onClick={() => void mirror()}><ActionIcon name="flip" />전체 입력 좌우 반전</button>
      <Info><b>영상 좌우 반전</b>은 보이는 화면만 뒤집습니다(추적·등록은 그대로). <b>전체 입력 좌우 반전</b>은 마우스·매핑·그리기의 좌우 방향을 함께 뒤집습니다. 둘은 서로 독립입니다.</Info>
      <button type="button" className="act-stop" onClick={() => void stopAll().catch(e => setErr(String(e)))}><ActionIcon name="stop" />긴급 정지</button>
    </div>
    <div className="row small" aria-label="영상 표시">
      {(['objects', 'hands', 'pens'] as const).map((key, i) => <label className="check" key={key}><input type="checkbox" checked={overlays[key]} onChange={e => setView({ overlays: { ...overlays, [key]: e.target.checked } })} />{['물체', '손 추적', '펜촉'][i]}</label>)}
      <span className="muted">영상 반전은 표시만 · 입력 반전은 마우스·매핑·그리기에 적용</span>
      <Info>영상 위에 그릴 표시를 고릅니다. 표시를 꺼도 추적·손 인식은 그대로 동작합니다.</Info>
    </div>
    {err && <p className="error">{err}</p>}
  </div>;
}
