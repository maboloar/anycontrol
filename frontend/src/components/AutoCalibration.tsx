import { ActionIcon } from "./ActionIcon";
import { useEffect, useRef, useState } from 'react';
import { applyAutoCalibration, autoCalibrationAction, getAutoCalibration, startAutoCalibration } from '../api';
import type { AutoCalibrationKind, AutoCalibrationState } from '../protocol';
import { useApp } from '../store';
import { ResizeHandle, useResizable } from './useResizable';

export const calibrationActive = (s: AutoCalibrationState | null) =>
  !!s && ['ready', 'recording', 'review'].includes(s.phase);
const labels = { hand: '맨손 마우스', object: '물체 마우스', pen: '펜' };
const cues: Record<string, string> = { right: '→', left: '←', near: '↑', far: '↓', click: '☝', right_click: '✌', scroll: '↕' };

/** 수동 조절을 보존하고, 안내에 따라 실제 관측을 측정한 뒤 한 번에 적용한다. */
export function AutoCalibration({ kind, objectId = null, disabled = false, prepare }: {
  kind: AutoCalibrationKind; objectId?: number | null; disabled?: boolean; prepare?: () => Promise<unknown>;
}) {
  const conn = useApp(s => s.conn);
  const status = useApp(s => s.autoCalibration);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const owner = useRef<string | null>(null);
  const mounted = useRef(true);
  const resize = useResizable('anycontrol.calibration.size', { minWidth: 320, minHeight: 250, floating: true });
  const matches = status?.kind === kind && status.object_id === objectId;
  const active = calibrationActive(status);

  useEffect(() => {
    const previous = useApp.getState().autoCalibration;
    if (conn === 'open') void getAutoCalibration().then(s => {
      if (useApp.getState().autoCalibration === previous) useApp.getState().setAutoCalibration(s);
    }).catch(() => undefined);
  }, [conn]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const current = useApp.getState().autoCalibration;
      if (current && owner.current === current.id && calibrationActive(current))
        void autoCalibrationAction('cancel', current.id).then(s => useApp.getState().setAutoCalibration(s)).catch(() => undefined);
      owner.current = null;
    };
  }, [kind, objectId]);

  const run = async (operation: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setError(null);
    try { await operation(); }
    catch (e) {
      if (mounted.current) setError(String(e instanceof Error ? e.message : e).replace(/^\d+ /, ''));
      void getAutoCalibration().then(s => useApp.getState().setAutoCalibration(s)).catch(() => undefined);
    } finally { if (mounted.current) setBusy(false); }
  };
  const start = () => run(async () => {
    await prepare?.();
    const next = await startAutoCalibration(kind, objectId);
    if (!mounted.current) { await autoCalibrationAction('cancel', next.id); return; }
    owner.current = next.id;
    useApp.getState().setAutoCalibration(next); setOpen(true);
  });
  const action = (a: 'record' | 'back' | 'cancel' | 'skip') => run(async () => {
    if (!status) return;
    const next = await autoCalibrationAction(a, status.id, a === 'record' || a === 'skip' ? status.step.key : undefined);
    useApp.getState().setAutoCalibration(next);
    if (a === 'cancel') setOpen(false);
  });
  const apply = () => run(async () => {
    if (!status) return;
    const result = await applyAutoCalibration(status.id);
    const app = useApp.getState();
    app.setAutoCalibration(result.calibration); app.setMouseInfo(result.mouse);
    if (result.pen && objectId !== null)
      app.setLive({ ...app.live, pens: { ...app.live.pens, [String(objectId)]: result.pen } });
    setOpen(false);
  });

  return <section className="auto-calibration" aria-label={`${labels[kind]} 자동 보정`}>
    <button type="button" className="calibration-start act-config" disabled={busy || disabled || conn !== 'open' || (active && !matches)}
      onClick={() => active && matches ? setOpen(true) : void start()}>
      <ActionIcon name="tune" />{active && matches ? '진행 중인 자동 보정 보기' : `${labels[kind]} 자동 보정`}
    </button>
    <p className="small muted">안내대로 움직이고 클릭하면 감도·접촉·떨림을 자동으로 조절합니다. 기존 슬라이더도 계속 사용할 수 있습니다.</p>
    {status && matches && status.phase === 'complete' && <p className="small calibration-success" role="status">자동 보정 설정을 적용했습니다.</p>}
    {status && matches && status.phase === 'cancelled' && status.error && <p className="small warn" role="status">{status.error}</p>}
    {error && <p className="error small" role="alert">{error}</p>}
    {open && status && matches && active && <div className="calibration-dialog" style={resize.style} role="dialog" aria-modal="false" aria-label={`${labels[kind]} 자동 보정 안내`}>
      <div className="calibration-heading"><strong>{labels[kind]} 자동 보정</strong>
        <button type="button" className="act-stop" disabled={busy} onClick={() => void action('cancel')}><ActionIcon name="stop" />취소</button></div>
      <p className="small muted">{status.completed}/{status.total} 검사 완료 · {status.skipped?.length ?? 0}개 건너뜀 · 측정 중 클릭과 그리기 출력은 멈춥니다. 취소하면 기존 설정을 유지합니다.</p>
      {status.phase === 'review' && status.result ? <>
        <h4>측정을 마쳤습니다</h4>
        <ul className="small">{status.result.summary.map((s, i) => <li key={i}>{s}</li>)}</ul>
        {status.result.notes.map((s, i) => <p className="small muted" key={i}>{s}</p>)}
        <button type="button" className="calibration-start act-config" disabled={busy} onClick={() => void apply()}><ActionIcon name="check" />자동 설정 적용</button>
      </> : <>
        <div className="calibration-cue" aria-hidden="true">{cues[status.step.key] ?? '◎'}</div>
        <h4>{status.index + 1}. {status.step.title}</h4>
        <p>{status.step.instruction}</p>
        {status.feedback && <div className={`calibration-feedback ${status.feedback.level}`} aria-live="polite">
          <strong>{status.feedback.level === 'good' ? '✓ 인식 중' : status.feedback.level === 'waiting' ? '◎ 인식 대기' : '동작을 조정해 주세요'}</strong>
          <p>{status.feedback.message}</p>
        </div>}
        {status.phase === 'recording' ? <>
          <progress max={1} value={status.progress} aria-label="측정 진행률" />
          <p className="small" role="status">유효 관측 수집 중 · 약 {Math.ceil(status.step.duration * (1 - status.progress))}초 · 관측 {status.samples}개</p>
        </> : <button type="button" className="calibration-start act-config" disabled={busy || status.feedback?.level === 'waiting'} onClick={() => void action('record')}>
          <ActionIcon name="play" />{status.error ? '이 단계 다시 측정' : '측정 시작'}</button>}
        {!!status.attempts_failed && <p className="small warn">이 단계 검사 실패 {status.attempts_failed}회 · 자세를 조정해 다시 측정하거나 건너뛸 수 있습니다.</p>}
        <button type="button" className="calibration-skip" disabled={busy} onClick={() => void action('skip')}>이 검사 건너뛰기</button>
        <p className="small muted">건너뛴 검사에 필요한 설정은 기존 값을 유지하고 다음 검사를 진행합니다.</p>
      </>}
      {status.error && <p className="error small" role="alert">{status.error}</p>}
      {status.index > 0 && status.phase !== 'recording' && <button type="button" disabled={busy} onClick={() => void action('back')}>이전 단계 다시 측정</button>}
      <ResizeHandle label="자동 보정 안내" grip={resize.grip} />
    </div>}
  </section>;
}
