import { BetaBadge } from "./BetaBadge";
import { ActionIcon } from "./ActionIcon";
import { useEffect, useRef, useState } from 'react';
import { applyAutoCalibration, autoCalibrationAction, getAutoCalibration, startAutoCalibration } from '../api';
import type { AutoCalibrationKind, AutoCalibrationState } from '../protocol';
import { useApp } from '../store';
import { ResizeHandle, useResizable } from './useResizable';
import { labels as i18nLabels, t } from '../i18n';
import { sv } from '../serverText';

export const calibrationActive = (s: AutoCalibrationState | null) =>
  !!s && ['ready', 'recording', 'review'].includes(s.phase);
const labels = i18nLabels({ hand: ['맨손 마우스', 'Hand mouse'], object: ['물체 마우스', 'Object mouse'], pen: ['펜', 'Pen'] });
const cues: Record<string, string> = { right: '→', left: '←', near: '↑', far: '↓', lr: '↔', nf: '⇅', clicks: '☝ ✌', click: '☝', right_click: '✌', scroll: '↕', touch: '⤓', lift: '⤒', rest: '◎' };

/** 수동 조절을 보존하고, 안내에 따라 실제 관측을 측정한 뒤 한 번에 적용한다. */
export function AutoCalibration({ kind, objectId = null, disabled = false, prepare, movementOnly = false }: {
  kind: AutoCalibrationKind; objectId?: number | null; disabled?: boolean; prepare?: () => Promise<unknown>; movementOnly?: boolean;
}) {
  const conn = useApp(s => s.conn);
  const status = useApp(s => s.autoCalibration);
  const [open, setOpen] = useState(false);
  const [includeGestures, setIncludeGestures] = useState(false);
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
    const next = await startAutoCalibration(kind, objectId, kind !== "pen" && (movementOnly || !includeGestures));
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

  return <section className="auto-calibration" aria-label={t(`${labels[kind]} 자동 보정`, `${labels[kind]} auto calibration`)}>
    <button type="button" className="calibration-start act-config" disabled={busy || disabled || conn !== 'open' || (active && !matches)}
      onClick={() => active && matches ? setOpen(true) : void start()}>
      <ActionIcon name="tune" />{active && matches ? t('진행 중인 자동 보정 보기', 'Show calibration in progress') : t(`${labels[kind]} 자동 보정`, `Auto-calibrate ${labels[kind].toLowerCase()}`)}{kind === "pen" && <BetaBadge />}
    </button>
    {kind !== "pen" && !movementOnly && <label className="check small"><input type="checkbox" checked={includeGestures} disabled={busy || active} onChange={e => setIncludeGestures(e.target.checked)} />{t("클릭·스크롤도 맞추기 (선택)", "Also tune clicks and scrolling (optional)")}</label>}
    <p className="small muted">{movementOnly ? t("물체의 정지·좌우·앞뒤 이동을 측정해 방향과 감도를 맞춥니다. 맨손 집기 클릭과 전환 거리는 수동 설정을 사용합니다.", "Measures object rest, left/right and near/far movement to tune direction and sensitivity. Hand pinch clicks and separation distance use manual settings.") : kind === "pen" ? t("펜은 잠깐 정지한 뒤 책상에 닿음·들기를 확인하고 이동 범위를 맞춥니다. 매번 중앙으로 돌아올 필요 없이 현재 위치에서 진행하세요.", "For a pen, pause, check contact and lift, then tune movement. Continue from your current position without returning to the center.") : t("기본은 잠깐 정지 → 좌우 왕복 → 앞뒤 또는 영상 위아래 왕복입니다. 매번 중앙으로 돌아갈 필요 없이 현재 위치에서 이어서 움직이세요. 클릭 설정은 선택하지 않으면 그대로 둡니다.", "Pause briefly, sweep left and right, then near and far or up and down in the video. Start each sweep wherever you are; no return to the center is needed. Click settings stay unchanged unless selected.")}</p>
    {status && matches && status.phase === 'complete' && <p className="small calibration-success" role="status">{t("자동 보정 설정을 적용했습니다.", "Auto calibration applied.")}</p>}
    {status && matches && status.phase === 'cancelled' && status.error && <p className="small warn" role="status">{sv(status.error)}</p>}
    {error && <p className="error small" role="alert">{error}</p>}
    {open && status && matches && active && <div className="calibration-dialog" style={resize.style} role="dialog" aria-modal="false" aria-label={t(`${labels[kind]} 자동 보정 안내`, `${labels[kind]} auto calibration guide`)}>
      <div className="calibration-heading"><strong>{t(`${labels[kind]} 자동 보정`, `${labels[kind]} auto calibration`)}</strong>
        <button type="button" className="act-stop" disabled={busy} onClick={() => void action('cancel')}><ActionIcon name="stop" />{t('취소', 'Cancel')}</button></div>
      <p className="small muted">{t("현재 위치에서 그대로 이어가세요. 중앙으로 원위치할 필요 없어요.", "Continue from your current position. No need to return to the center.")}</p>
      <p className="small muted">{t(`${status.completed}/${status.total} 검사 완료 · ${status.skipped?.length ?? 0}개 건너뜀 · 측정 중 클릭과 그리기 출력은 멈춥니다. 취소하면 기존 설정을 유지합니다.`, `${status.completed}/${status.total} checks done · ${status.skipped?.length ?? 0} skipped · Clicks and drawing pause while measuring. Cancel keeps your settings.`)}</p>
      {status.phase === 'review' && status.result ? <>
        <h4>{t("측정을 마쳤습니다", "Measurement complete")}</h4>
        <ul className="small">{status.result.summary.map((s, i) => <li key={i}>{sv(s)}</li>)}</ul>
        {status.result.notes.map((s, i) => <p className="small muted" key={i}>{sv(s)}</p>)}
        <button type="button" className="calibration-start act-config" disabled={busy} onClick={() => void apply()}><ActionIcon name="check" />{t("자동 설정 적용", "Apply settings")}</button>
      </> : <>
        <div className="calibration-cue" aria-hidden="true">{cues[status.step.key] ?? '◎'}</div>
        <h4>{status.index + 1}. {sv(status.step.title)}</h4>
        <p>{sv(status.step.instruction)}</p>
        {status.feedback && <div className={`calibration-feedback ${status.feedback.level}`} aria-live="polite">
          <strong>{status.feedback.level === 'good' ? t('✓ 인식 중', '✓ Detected') : status.feedback.level === 'waiting' ? t('◎ 인식 대기', '◎ Waiting') : t('동작을 조정해 주세요', 'Adjust your movement')}</strong>
          <p>{sv(status.feedback.message)}</p>
        </div>}
        {status.phase === 'recording' ? <>
          <progress max={1} value={status.progress} aria-label={t("측정 진행률", "Measurement progress")} />
          <p className="small" role="status">{t(`유효 관측 수집 중 · 약 ${Math.ceil(status.step.duration * (1 - status.progress))}초 · 관측 ${status.samples}개`, `Collecting samples · about ${Math.ceil(status.step.duration * (1 - status.progress))}s · ${status.samples} samples`)}</p>
        </> : <button type="button" className="calibration-start act-config" disabled={busy || status.feedback?.level === 'waiting'} onClick={() => void action('record')}>
          <ActionIcon name="play" />{status.error ? t('이 단계 다시 측정', 'Measure this step again') : t('측정 시작', 'Start measuring')}</button>}
        {!!status.attempts_failed && <p className="small warn">{t(`이 단계 검사 실패 ${status.attempts_failed}회 · 자세를 조정해 다시 측정하거나 건너뛸 수 있습니다.`, `This check failed ${status.attempts_failed} time(s). Adjust and measure again, or skip it.`)}</p>}
        <button type="button" className="calibration-skip" disabled={busy} onClick={() => void action('skip')}>{t('이 검사 건너뛰기', 'Skip this check')}</button>
        <p className="small muted">{t("건너뛴 검사에 필요한 설정은 기존 값을 유지하고 다음 검사를 진행합니다.", "Settings that need a skipped check keep their current values.")}</p>
      </>}
      {status.error && <p className="error small" role="alert">{sv(status.error)}</p>}
      {status.index > 0 && status.phase !== 'recording' && <button type="button" disabled={busy} onClick={() => void action('back')}>{t('이전 단계 다시 측정', 'Redo previous step')}</button>}
      <ResizeHandle label={t("자동 보정 안내", "Calibration guide")} grip={resize.grip} />
    </div>}
  </section>;
}
