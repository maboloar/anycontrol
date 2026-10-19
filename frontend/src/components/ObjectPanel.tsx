import { HandInputCard } from "./HandInputCard";
import { editDraft, useDraftStore } from "../mappingDraft";
import { bindObjectRefs, objectRef } from "../objectRefs";
import { BetaBadge } from "./BetaBadge";
import { ActionIcon } from "./ActionIcon";
import { Panel } from "./Panel";
import { Info } from "./Info";
import { AutoResegControl } from "./AutoResegControl";
import { MemoryView } from "./MemoryView";
import { FloorMapView } from "./FloorMapView";
import { useEffect, useRef, useState } from "react";
import { deleteObject, getObjectThumbnail, getTracking, pickCandidate, putTracking, renameObject, setNeutral, type TrackingInfo } from "../api";
import { PatchJack } from "./PatchCables";
import { STATE_LABEL } from "../overlay";
import { AXIS_NAMES, type AxisName, type ObjectInfo } from "../protocol";
import { useApp } from "../store";
import { labels, t as tr } from "../i18n";
import { sv } from "../serverText";

const AXIS_UNIT: Record<AxisName, { unit: string; scale: number }> = {
  x: { unit: "%", scale: 100 }, y: { unit: "%", scale: 100 }, depth: { unit: "", scale: 1 },
  angle: { unit: "°", scale: 1 }, stretch: { unit: "", scale: 1 }, contact: { unit: "%", scale: 100 },
};
const AXIS_NAME = labels<AxisName>({
  x: ["좌우", "X"], y: ["상하", "Y"], depth: ["깊이", "Depth"], angle: ["기울기", "Tilt"], stretch: ["형태", "Shape"], contact: ["바닥선", "Base line"],
});
const AXIS_HINT = labels<AxisName>({
  x: ["프레임 폭 대비 이동", "Movement relative to frame width"],
  y: ["프레임 높이 대비 이동 (아래 +)", "Movement relative to frame height (down +)"],
  depth: ["log(크기/중립). 카메라 쪽으로 오면 +", "log(size/neutral). Toward camera is +"],
  angle: ["화면상 회전 (시계방향 +)", "On-screen rotation (clockwise +)"],
  stretch: ["log(길쭉함/중립). 옆에서 본 회전", "log(elongation/neutral). Rotation seen from the side"],
  contact: ["접촉선 이동. 손이 위를 가려도 안정적인 깊이 신호", "Contact-line shift. Stable depth even when a hand covers the top"],
});
// 막대 표시용 대략적 범위 (매핑 엔진의 실제 범위와는 무관)
const BAR_RANGE: Record<AxisName, number> = { x: 0.3, y: 0.3, depth: 0.8, angle: 45, stretch: 0.5, contact: 0.2 };

function HandOcclusionToggle() {
  const conn = useApp((s) => s.conn);
  const [t, setT] = useState<TrackingInfo | null>(null);
  useEffect(() => {
    if (conn !== "open") return;
    const refresh = () => getTracking().then(setT, () => undefined);
    void refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => window.clearInterval(timer);
  }, [conn]);
  const advanced = useApp((s) => s.devMode);
  if (!t) return null;
  return (
    <div>
    {advanced && <><p className={`small ${t.tier1_mode === "off" ? "warn" : "muted"}`}>
      {t.tier1_mode === "off" ? tr("경량 추적 · 모델 보정 없음", "Lightweight tracking · no model correction") : tr(`EfficientTAM 보정 · ${t.tier1_mode} · 적용 ${t.tier1_stats?.applied ?? 0}회 · 모양으로 다시 찾음 ${t.tier1_stats?.reacq_ok ?? 0}회`, `EfficientTAM correction · ${t.tier1_mode} · applied ${t.tier1_stats?.applied ?? 0} · re-found by shape ${t.tier1_stats?.reacq_ok ?? 0}`)}
      {t.tier1_mode !== "off" && <Info>{tr(<>놓친 물체는 0.3초마다 화면 전체에서 <b>기억한 모양·색</b>과 맞는 것을 찾고, 같은 곳에서 두 번 연속 맞으면
        추적을 되살립니다. 닮은 물체가 둘 이상이면 옮겨붙지 않게 일부러 고르지 않습니다.</>,
        <>Every 0.3s a lost object is searched for across the frame by its <b>remembered shape and color</b>; two matches in a row at the same spot resume tracking. If several look alike, none is picked to avoid switching.</>)}</Info>}
    </p>
    {t.tier1_error && <p className="error small">{tr("모델 보정 오류", "Model correction error")}: {t.tier1_error}</p>}
    <label className="check small dev-check"><input type="checkbox" checked={t.segmentation_enabled ?? false}
      onChange={(e) => putTracking({ segmentation_enabled: e.target.checked }).then(setT, () => undefined)} />
      {tr("주기적 segmentation 보정", "Periodic segmentation correction")}
      <Info>{tr("주기적으로 현재 위치를 AI 모델로 다시 분할해 조금씩 쌓인 위치 오차를 바로잡습니다. 확실할 때만 적용합니다.", "Periodically re-segments the object with the AI model to fix accumulated drift. Applied only when confident.")}</Info></label>
    {t.segmentation_enabled && <div className="field small">
      <label>{tr("재분할 주기", "Re-segmentation rate")} <select aria-label={tr("재분할 주기", "Re-segmentation rate")} value={t.segmentation_hz ?? .5}
        onChange={(e) => putTracking({ segmentation_hz: Number(e.target.value) }).then(setT, () => undefined)}>
        <option value={.25}>{tr("0.25 Hz · 4초", "0.25 Hz · 4s")}</option><option value={.5}>{tr("0.5 Hz · 2초 (기본)", "0.5 Hz · 2s (default)")}</option><option value={1}>{tr("1 Hz · 1초", "1 Hz · 1s")}</option>
      </select></label>
      <p className="muted">{tr(`부하 반영 ${(t.segmentation_effective_hz ?? .5).toFixed(2)} Hz · 보정 ${t.segmentation_stats?.applied ?? 0}회 · 제외 ${t.segmentation_stats?.rejected ?? 0}회`, `Load-adjusted ${(t.segmentation_effective_hz ?? .5).toFixed(2)} Hz · applied ${t.segmentation_stats?.applied ?? 0} · rejected ${t.segmentation_stats?.rejected ?? 0}`)}</p>
      {t.segmentation_backend === "grabcut" && <p className="warn">{tr("모델을 사용할 수 없어 GrabCut으로 재분할합니다.", "Model unavailable; using GrabCut for re-segmentation.")}</p>}
    </div>}
    {t.segmentation_error && <p className="error small">{tr("재분할 오류", "Re-segmentation error")}: {t.segmentation_error}</p>}
    </>}
    <label className="check small">
      <input type="checkbox" checked={t.ema ?? true} onChange={(e) => putTracking({ ema: e.target.checked }).then(setT, () => undefined)} />
      {tr("튐 억제 (실시간 EMA)", "Spike guard (real-time EMA)")}
      <Info>{tr("모든 물체·펜의 위치·크기·각도와 펜촉, 물체 마우스 좌표에 지수이동평균을 씌웁니다. 한두 프레임만 확 튀는 값은 거의 반영하지 않고, 0.2초 이상 이어지는 진짜 이동은 곧 따라갑니다. 끄면 필터 없이 그대로 나갑니다.",
        "Applies an exponential moving average to the position, size and angle of every object and pen, the pen tip, and the object-mouse position. A value that jumps for a frame or two is mostly ignored; a real move lasting over ~0.2 s is followed quickly. Off = unfiltered.")}</Info>
    </label>
    {advanced && t.hands_available && <label className="check small dev-check" title={tr("손 영역을 물체 측정에서 빼고, 쥔 손의 움직임으로 추적을 이어 갑니다. 손 추적(CPU)이 계속 돕니다.", "Excludes hands from object measurement and follows the gripping hand. Hand tracking keeps running on the CPU.")}>
      <input type="checkbox" checked={t.hand_occlusion} onChange={(e) => putTracking(e.target.checked).then(setT, () => undefined)} />
      {tr("손 가림 처리 (손 인식)", "Hand occlusion handling (hand detection)")}
      <Info>{tr("손이 덮은 부분을 물체에서 빼고, 쥔 손의 움직임으로 추적을 이어 갑니다. 손 인식이 계속 돌아 CPU를 더 씁니다.", "Removes hand-covered areas from the object and follows the gripping hand. Uses more CPU.")}</Info>
    </label>}
    </div>
  );
}

const objectInfo = () => tr(<>등록한 물체·펜의 상태와 축 값입니다. 등록할 때 <b>모양과 색을 기억</b>해 두었다가, 가려지거나 화면 밖에 나갔다 와도
  기억한 모양으로 다시 찾아 추적을 이어 갑니다. 잘못 잡혔으면 <b>[다시 선택]</b>으로 모양을 새로 기억시키세요.</>,
  <>State and axis values of registered objects and pens. Each object's <b>shape and color are remembered</b>, so it is found again after being covered or leaving the frame. If it grabbed the wrong thing, use <b>[Reselect]</b>.</>);

/** 물체마다 등록 모습 사진을 받아 둔다. 다시 선택·후보 교체 뒤, 그리고 15초마다 새로 받는다 (자동 재분할 반영). */
function useThumbnails(objects: ObjectInfo[]): Record<number, string | null> {
  const [thumbs, setThumbs] = useState<Record<number, string | null>>({});
  const reselectId = useApp((s) => s.reselectId);
  const key = objects.map((o) => `${o.id}:${o.candidate_index}`).join(",");
  useEffect(() => {
    let alive = true;
    const load = () => objects.forEach((o) => Promise.resolve(getObjectThumbnail(o.id)).then(
      (r) => { if (alive && r) setThumbs((m) => (m[o.id] === r.image ? m : { ...m, [o.id]: r.image })); }, () => undefined));
    load();
    const timer = window.setInterval(load, 15000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [key, reselectId]);
  return thumbs;
}

export function ObjectPanel() {
  const objects = useApp((s) => s.objects);
  const thumbs = useThumbnails(objects);
  const selectedId = useApp((s) => s.selectedId);
  const select = useApp((s) => s.select);
  const [clearing, setClearing] = useState(false);
  const [clearErr, setClearErr] = useState<string | null>(null);
  // 한 번 누르면 버튼이 확인 문구로 바뀌고, 한 번 더 눌러야 지운다. 4초 지나거나 다른 곳을 누르면 되돌아간다.
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), 4000);
    return () => window.clearTimeout(timer);
  }, [armed]);
  const deleteAll = async () => {
    if (!armed) { setArmed(true); return; }
    setArmed(false);
    setClearing(true);
    const results = await Promise.allSettled(objects.map((o) => deleteObject(o.id)));
    const failed = results.filter((r) => r.status === "rejected").length;
    setClearErr(failed ? tr(`${failed}개를 삭제하지 못했습니다.`, `${failed} could not be deleted.`) : null);
    setClearing(false);
  };

  if (objects.length === 0) {
    return (
      <Panel title={tr("물체", "Objects")} label="물체" tour="objects" info={objectInfo()}>
        <HandInputCard />
        <HandOcclusionToggle />
        <p className="muted">{tr("아직 등록된 물체가 없습니다. 영상에서 물체를 드래그하세요.", "No objects yet. Drag around an object in the video.")}</p>
      </Panel>
    );
  }
  return (
    <Panel title={tr("물체", "Objects")} label="물체" tour="objects" info={objectInfo()}>
      <HandInputCard />
        <HandOcclusionToggle />
      <div className="obj-cards" data-tour="obj-cards" role="tablist" aria-label={tr("등록한 물체", "Registered objects")}>
        {objects.map((o) => (
          <div key={o.id} className={`obj-card ${o.id === selectedId ? "active" : ""}`} style={{ "--obj": o.color } as React.CSSProperties}>
            <button type="button" role="tab" aria-selected={o.id === selectedId} onClick={() => select(o.id)}
              title={`${o.name} · ${STATE_LABEL[o.state]}`}>
              <span className="obj-photo">
                {thumbs[o.id] ? <img src={thumbs[o.id]!} alt="" /> : <span className="dot" style={{ background: o.color }} aria-hidden="true" />}
                <span className={`obj-state state-${o.state}`} aria-hidden="true" />
              </span>
              <span className="obj-card-name">{o.name}{o.warnings.some(w => w.includes("겹침")) && <small className="warn"> · {tr("겹침", "Overlap")}</small>}{o.kind === "pen" && <BetaBadge />}</span>
            </button>
            <PatchJack side="obj" name={objectRef(o)} color={o.color} />
          </div>
        ))}
      </div>
      <div className="row">
        <button type="button" className={`danger delete-all ${armed ? "armed" : ""}`} disabled={clearing}
          onClick={() => void deleteAll()} onBlur={() => setArmed(false)} aria-live="polite">
          <ActionIcon name="trash" />{armed ? tr(`${objects.length}개 정말 삭제할까요?`, `Really delete ${objects.length}?`) : `${tr("모두 삭제", "Delete all")} (${objects.length})`}</button>
      </div>
      {clearErr && <p className="error small" role="alert">{clearErr}</p>}
      {objects.filter((o) => o.id === selectedId).map((o) => <ObjectDetail key={o.id} obj={o} />)}
    </Panel>
  );
}

function ObjectDetail({ obj }: { obj: ObjectInfo }) {
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(obj.name);
  const [saving, setSaving] = useState(false);
  const [candidateBusy, setCandidateBusy] = useState(false);
  const [attempted, setAttempted] = useState(obj.candidate_index);
  const candidateLock = useRef(false);
  const saveLock = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const cancelName = () => { setEditing(false); setName(obj.name); };
  const saveName = async () => {
    if (saveLock.current) return;
    const trimmed = name.trim();
    if (!trimmed || trimmed === obj.name) { cancelName(); return; }
    saveLock.current = true; setSaving(true);
    try {
      const draft = useDraftStore.getState().draft;
      if (draft && draft.mappings.some(m => "object" in m.input && m.input.object === obj.name))
        editDraft(bindObjectRefs(draft, useApp.getState().objects));
      const result = await renameObject(obj.id, trimmed);
      const app = useApp.getState();
      app.setObjects(app.objects.map(o => o.id === obj.id ? { ...o, name: result.name } : o));
      if (mounted.current) { setErr(null); setEditing(false); }
    } catch (e) { if (mounted.current) setErr(String(e)); }
    finally { saveLock.current = false; if (mounted.current) setSaving(false); }
  };
  const nextCandidate = async () => {
    if (candidateLock.current) return;
    candidateLock.current = true; setCandidateBusy(true);
    const next = (attempted + 1) % obj.candidates;
    setAttempted(next); // 실패한 후보도 시도한 번호로 기억해 다음 클릭에서 건너뛴다.
    // 후보 변경은 같은 ID로 모양만 갱신하므로 선택과 매핑을 유지한다.
    useApp.getState().setReplacing(obj.id);
    try {
      const result = await pickCandidate(obj.id, next);
      // 같은 물체 카드에 갱신된 후보/윤곽을 반영한다.
      useApp.getState().replaceObject(obj.id, result);
      if (mounted.current) setErr(null);
    } catch (e) { if (mounted.current) setErr(`${String(e)} · ${tr(`후보 ${next + 1}은 적용하지 못했습니다. 다시 누르면 다음 후보를 시도합니다.`, `Candidate ${next + 1} could not be applied. Press again to try the next one.`)}`); }
    finally {
      if (useApp.getState().replacingId === obj.id) useApp.getState().setReplacing(null);
      candidateLock.current = false; if (mounted.current) setCandidateBusy(false);
    }
  };
  const run = (p: Promise<unknown>) => p.then(() => setErr(null), (e: unknown) => setErr(String(e)));
  const reselecting = useApp((s) => s.reselectId === obj.id);
  // 전역 상태: 다른 물체를 고르거나 후보를 바꿔 이 컴포넌트가 새로 만들어져도 켜진 채로 둔다.
  const devMode = useApp((s) => s.devMode);
  const showMemory = useApp((s) => s.memoryOpen);
  const showFloor = useApp((s) => s.floorMapOpen) && devMode && obj.kind === "pen";
  const setShowMemory = useApp((s) => s.setMemoryOpen);

  return (
    <div role="tabpanel">
      <div className="obj-head">
        {editing ? (
          <form onSubmit={(e) => { e.preventDefault(); void saveName(); }}>
            <input name="name" value={name} onChange={e => setName(e.target.value)} maxLength={40}
              aria-label={obj.kind === 'pen' ? tr('펜 이름', 'Pen name') : tr('물체 이름', 'Object name')} autoFocus disabled={saving}
              onFocus={e => e.currentTarget.select()} onBlur={() => { if (editing) void saveName(); }}
              onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cancelName(); } }} />
          </form>
        ) : (
          <button type="button" className="link obj-name" onClick={() => { setName(obj.name); setEditing(true); }} title={tr("이름 바꾸기", "Rename")}>
            {obj.name}
            <svg className="pencil" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 20h4L19 9l-4-4L4 16v4ZM13.5 6.5l4 4" /></svg>
          </button>
        )}
        <span className={`state state-${obj.state}`}>{STATE_LABEL[obj.state]}</span>
        <span className="muted">{tr("신뢰도", "Confidence")} {Math.round(obj.confidence * 100)}%</span>
        <Info>{tr("추적 중 / 쥠 / 가려짐 / 찾는 중 / 놓침. 가려지거나 놓치면 기억한 모양으로 스스로 다시 찾습니다.", "Tracking / held / occluded / searching / lost. When covered or lost, it re-finds itself by remembered shape.")}</Info>
      </div>

      <><dl className="axes">
        {AXIS_NAMES.map((a) => {
          const v = obj.axes[a];
          const L = { ...AXIS_UNIT[a], name: AXIS_NAME[a], hint: AXIS_HINT[a] };
          const frac = v === null ? 0 : Math.max(-1, Math.min(1, v / BAR_RANGE[a]));
          return (
            <div key={a} title={L.hint}>
              <dt>{L.name}</dt>
              <dd>
                <span className="bar" aria-hidden="true">
                  <span
                    className="fill"
                    style={{ left: `${50 + Math.min(0, frac) * 50}%`, width: `${Math.abs(frac) * 50}%`, background: obj.color }}
                  />
                </span>
                <span className="val">{v === null ? "–" : `${(v * L.scale).toFixed(a === "angle" ? 1 : 2)}${L.unit}`}</span>
              </dd>
            </div>
          );
        })}
      </dl>

      <p className="muted small">
        {tr("무늬", "Texture")} {Math.round(obj.texture * 100)}% · {tr("배경 대비", "Contrast")} {Math.round(obj.contrast * 100)}%
        <Info>{tr("무늬가 많고 배경과 색이 뚜렷이 다를수록 추적이 안정적입니다. 둘 다 낮으면 경고가 표시됩니다.", "More texture and stronger contrast with the background make tracking steadier. A warning appears when both are low.")}</Info>
      </p>
      </>
      {obj.warnings.map((w) => (
        <p key={w} className="warn small">{sv(w)}</p>
      ))}

      <div className="row">
        <button type="button" className="act-config" onClick={() => run(setNeutral(obj.id))}
          title={tr("지금 자세를 축 값 0 으로", "Make the current pose zero on every axis")}><ActionIcon name="target" />{tr("현재 위치를 중립으로", "Set current position as neutral")}</button>
        <button type="button" className={reselecting ? "active" : "act-output"} aria-pressed={reselecting}
          onClick={() => {
            const app = useApp.getState();
            if (reselecting) { app.setReselect(null); return; }
            app.setSelectMode("object");
            app.setReselect(obj.id);
            document.querySelector('[data-tour="camera"]')?.scrollIntoView({ behavior: "smooth", block: "center" });
          }}>
          <ActionIcon name="target" />{reselecting ? tr("다시 선택 취소", "Cancel reselect") : tr("다시 선택", "Reselect")}
        </button>
        <Info>{tr(<>추적이 어긋나면 누르고 영상에서 {obj.kind === "pen" ? "펜촉 → 반대쪽 끝 두 점을 다시 찍으세요" : "물체를 다시 드래그(또는 클릭)하세요"}.
          이름·색·매핑·마우스 연결은 그대로 두고 <b>모양 기억</b>만 새로 합니다. 선택된 물체는 영상에서 <b>Shift+드래그</b>로도 바로 다시 선택됩니다. ESC 취소.</>,
          <>If tracking drifts, press this and {obj.kind === "pen" ? "click the tip, then the other end, again" : "drag (or click) the object again"}. Name, color, mappings and mouse links stay; only the <b>remembered shape</b> is renewed. <b>Shift+drag</b> in the video also reselects the selected object. ESC cancels.</>)}</Info>
        {obj.candidates > 1 && (
          <button type="button" disabled={candidateBusy} onClick={() => void nextCandidate()}
            title={tr("같은 선택에서 분할기가 낸 다른 모양으로 바꿉니다 (새 id)", "Switch to another shape the segmenter proposed for this selection (new id)")}>
            {tr("다른 분할 후보", "Next candidate")} ({attempted + 1}/{obj.candidates})
          </button>
        )}
        <button type="button" className={showMemory ? "active" : ""} aria-pressed={showMemory} aria-expanded={showMemory}
          onClick={() => setShowMemory(!showMemory)}
          title={tr("놓쳤을 때 다시 찾는 데 쓰는 실시간 기억을 보고, 잘못 기억한 것은 골라 지웁니다", "See the live memory used to re-find the object when lost, and delete wrong ones")}>
          {showMemory ? tr("실시간 기억 닫기", "Hide live memory") : tr("실시간 기억 관리", "Manage live memory")}
        </button>
        {devMode && obj.kind === "pen" && <button type="button" className={`dev-btn ${showFloor ? "active" : ""}`} aria-pressed={showFloor} aria-expanded={showFloor}
          onClick={() => useApp.getState().setFloorMapOpen(!showFloor)}
          title={tr("펜이 바닥에 닿았을 때의 예상 굵기를 가까움=밝음, 멈=어둠의 흑백 그라데이션으로 봅니다", "Show the expected touching pen width as a near=bright, far=dark grayscale gradient over the floor")}>
          {showFloor ? tr("바닥 맵 닫기", "Hide floor map") : tr("바닥 그라데이션 맵 보기", "Show floor gradient map")}
        </button>}
        <button type="button" className="danger" onClick={() => run(deleteObject(obj.id))}><ActionIcon name="trash" />{tr("삭제", "Delete")}</button>
      </div>
      {obj.kind !== "pen" && <AutoResegControl />}
      {showMemory && <MemoryView id={obj.id} />}
      {showFloor && <FloorMapView id={obj.id} />}
      {err && <p className="error small" role="alert">{err}</p>}
    </div>
  );
}
