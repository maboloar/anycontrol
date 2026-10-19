import { ActionIcon } from "./ActionIcon";
import { useEffect, useState } from 'react';
import { getDepthMap, getSceneMap, getTracking, putTracking, putPlayback, stopAll } from '../api';
import type { DepthMapData } from '../protocol';
import { useApp } from '../store';
import { Info } from './Info';
import { t } from '../i18n';

/** 개발자 모드: 깊이 맵(또는 배경 모델 판정)을 카메라 영상 위에 겹쳐 본다. 켜 있는 동안만, 응답을 받는 대로 다음을 요청한다
 * (요청이 겹치지 않음). 서버는 추적기가 ~6Hz 로 계산해 둔 최신 결과를 돌려주므로 대략 실시간이다. */
const POLL_GAP_MS = 60;
function DepthMapPoller({ kind }: { kind: 'depth' | 'scene' }) {
  useEffect(() => {
    let alive = true;
    let timer = 0;
    const load = async () => {
      try { const m = await (kind === 'scene' ? getSceneMap() : getDepthMap()); if (alive) useApp.getState().setDepthMap(m); }
      catch { if (alive) useApp.getState().setDepthMap(null); }
      if (alive) timer = window.setTimeout(() => void load(), POLL_GAP_MS);
    };
    void load();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [kind]);
  return null;
}
function depthStatus(kind: 'depth' | 'scene', map: DepthMapData | null): string {
  if (kind === 'scene') {
    if (map?.reason === 'disabled') return t('배경 모델이 꺼져 있습니다', 'The background model is off');
    if (!map?.ready) return t('배경을 배우는 중…', 'Learning the background…');
    const g = map.grid;
    const need = g ? Math.ceil((map.info?.unstable_frac ?? 0.5) * g.known) : 0;
    const cells = g ? t(` · 격자: 바뀐 칸 ${g.changed}/${g.known} (${need}칸 이상이면 끔, 주황=바뀐 칸, 회색=물체·손이 덮어 세지 않음)`,
      ` · grid: ${g.changed}/${g.known} cells changed (off at ${need}+; orange = changed, gray = covered, not counted)`) : '';
    if (map.info && !map.info.valid) return t(`지금은 배경 모델을 쓰지 않습니다 (카메라 이동·장면 변화, 다시 배우는 중)${cells}`,
      `Background model paused (camera moved or scene changed; relearning)${cells}`);
    return t(`배경 모델 · 빨강=배경과 달라짐(물체·손) · 파랑=배경 그대로 · 깊이 ${map.info?.depth ? '사용' : '없음'}${cells}`,
      `Background model · red = changed (objects, hands) · blue = unchanged · depth ${map.info?.depth ? 'on' : 'off'}${cells}`);
  }
  if (map?.ready) return t(`Depth Anything V2 Small · ${map.ms ?? '-'}ms · ${map.age ?? '-'}초 전 · 가까움=밝음`,
    `Depth Anything V2 Small · ${map.ms ?? '-'} ms · ${map.age ?? '-'} s ago · near = bright`);
  return map?.reason === 'model_missing' ? t('깊이 모델이 없습니다', 'The depth model is missing') : t('깊이 맵 계산 중…', 'Computing the depth map…');
}
export function DepthMapButton() {
  const devMode = useApp(s => s.devMode);
  const on = useApp(s => s.depthMapOverlay);
  const map = useApp(s => s.depthMap);
  const kind = useApp(s => s.depthMapKind);
  const opacity = useApp(s => s.depthMapOpacity);
  if (!devMode) return null;
  return <>
    <button type="button" className={`dev-btn ${on ? 'active' : ''}`} aria-pressed={on} onClick={() => useApp.getState().setDepthMapOverlay(!on)}>
      {on ? t('깊이 맵 끄기', 'Hide depth map') : t('깊이 맵 보기', 'Show depth map')}
    </button>
    {on && <DepthMapPoller kind={kind} />}
    {on && <select className="dev-check" aria-label={t('겹쳐 볼 것', 'Overlay')} value={kind}
      onChange={e => useApp.getState().setDepthMapKind(e.target.value as 'depth' | 'scene')}>
      <option value="depth">{t('깊이 (Depth Anything)', 'Depth (Depth Anything)')}</option>
      <option value="scene">{t('배경 모델 (전경 판정)', 'Background model (foreground)')}</option>
    </select>}
    {on && <label className="dev-check small">{t('진하기', 'Opacity')}
      <input type="range" min={0.2} max={1} step={0.05} value={opacity} aria-label={t('겹침 진하기', 'Overlay opacity')}
        onChange={e => useApp.getState().setDepthMapOpacity(Number(e.target.value))} /></label>}
    {on && <span className="small muted" role="status">{depthStatus(kind, map)}</span>}
    <Info>{t('Depth Anything V2 Small이 만든 상대 깊이, 또는 추적에 쓰는 정지 배경 모델(색 + 깊이)의 판정을 카메라 영상 위에 실시간으로 겹쳐 보여 줍니다. 깊이 값은 프레임마다 상대적이라 밝기 절대값에는 뜻이 없고, 책상이 위(먼 쪽)에서 아래(가까운 쪽)로 매끈하게 밝아지는지 보세요. 배경 모델 보기에서는 물체·손만 빨갛고 책상은 파래야 정상입니다(펜에는 쓰지 않습니다).',
      'Overlays, in real time, either the relative depth from Depth Anything V2 Small or the decision of the static background model (color + depth) used for tracking. Depth values are relative per frame, so only the shape matters. In the background-model view, only objects and hands should be red and the desk blue (not used for pens).')}</Info>
  </>;
}
export function CameraTools() {
  const { conn, inputMirror, setInputMirror, viewFlip, overlays, setView, telemetry, devMode: advanced } = useApp();
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { let alive = true; if (conn === 'open') getTracking().then(i => { if (alive) setInputMirror(!!i.input_mirror); }, e => { if (alive) setErr(String(e)); }); return () => { alive = false; }; }, [conn]);
  const mirror = async () => {
    setBusy(true);
    try { const r = await putTracking({ input_mirror: !inputMirror }); setInputMirror(!!r.input_mirror); setErr(''); }
    catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  return <div className="camera-tools">
    <div className="row">
      <button type="button" className={telemetry?.source?.paused ? "act-go" : "act-pause"} disabled={conn !== 'open'} onClick={() => void putPlayback(!telemetry?.source?.paused).catch(e => setErr(String(e)))}><ActionIcon name={telemetry?.source?.paused ? 'play' : 'pause'} />{telemetry?.source?.paused ? t('영상 재생', 'Play video') : t('영상 정지', 'Pause video')}</button>
      <button type="button" className="act-config" aria-pressed={viewFlip} onClick={() => setView({ viewFlip: !viewFlip })}><ActionIcon name="flip" />{t("영상 좌우 반전", "Flip view")}</button>
      <><button type="button" className="act-config" aria-pressed={inputMirror} disabled={busy || conn !== 'open'} onClick={() => void mirror()}><ActionIcon name="flip" />{t("전체 입력 좌우 반전", "Flip all input")}</button>
      <Info>{t(<><b>영상 좌우 반전</b>은 보이는 화면만 뒤집습니다(추적·등록은 그대로). <b>전체 입력 좌우 반전</b>은 마우스·매핑·그리기의 좌우 방향을 함께 뒤집습니다. 둘은 서로 독립입니다.</>,
        <><b>Flip view</b> mirrors only the display; tracking is unchanged. <b>Flip all input</b> mirrors left/right for mouse, mappings and drawing. They are independent.</>)}</Info></>
      <button type="button" className="act-stop" onClick={() => void stopAll().catch(e => setErr(String(e)))}><ActionIcon name="stop" />{t("긴급 정지", "Emergency stop")}</button>
      <DepthMapButton />
    </div>
    {advanced && <div className="row small" aria-label={t("영상 표시", "Overlays")}>
      {(['objects', 'hands', 'pens'] as const).map((key, i) => <label className="check" key={key}><input type="checkbox" checked={overlays[key]} onChange={e => setView({ overlays: { ...overlays, [key]: e.target.checked } })} />{t(['물체', '손 추적', '펜촉'], ['Objects', 'Hands', 'Pen tips'])[i]}</label>)}
      <label className="check"><input type="checkbox" checked={useApp.getState().touchOverlay} onChange={e => useApp.setState({ touchOverlay: e.target.checked })} />{t("터치 감지 표시", "Touch diagnostics")}</label>
      <span className="muted">{t("영상 반전은 표시만 · 입력 반전은 마우스·매핑·그리기에 적용", "View flip is display-only · Input flip affects mouse, mappings and drawing")}</span>
      <Info>{t("영상 위에 그릴 표시를 고릅니다. 표시를 꺼도 추적·손 인식은 그대로 동작합니다.", "Choose what to draw over the video. Tracking keeps running when hidden.")}</Info>
    </div>}
    {err && <p className="error">{err}</p>}
  </div>;
}
