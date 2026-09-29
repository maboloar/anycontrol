import { ActionIcon } from "./ActionIcon";
import { Panel } from "./Panel";
import { Info } from "./Info";
import { useEffect, useRef, useState } from "react";
import { deleteObject, getTracking, pickCandidate, putTracking, renameObject, setNeutral, type TrackingInfo } from "../api";
import { STATE_LABEL } from "../overlay";
import { AXIS_NAMES, type AxisName, type ObjectInfo } from "../protocol";
import { useApp } from "../store";

const AXIS_LABEL: Record<AxisName, { name: string; unit: string; scale: number; hint: string }> = {
  x: { name: "좌우", unit: "%", scale: 100, hint: "프레임 폭 대비 이동" },
  y: { name: "상하", unit: "%", scale: 100, hint: "프레임 높이 대비 이동 (아래 +)" },
  depth: { name: "깊이", unit: "", scale: 1, hint: "log(크기/중립). 카메라 쪽으로 오면 +" },
  angle: { name: "기울기", unit: "°", scale: 1, hint: "화면상 회전 (시계방향 +)" },
  stretch: { name: "형태", unit: "", scale: 1, hint: "log(길쭉함/중립). 옆에서 본 회전" },
  contact: { name: "바닥선", unit: "%", scale: 100, hint: "접촉선 이동. 손이 위를 가려도 안정적인 깊이 신호" },
};
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
  if (!t) return null;
  return (
    <div>
    <p className={`small ${t.tier1_mode === "off" ? "warn" : "muted"}`}>
      {t.tier1_mode === "off" ? "경량 추적 · 모델 보정 없음" : `EfficientTAM 보정 · ${t.tier1_mode} · 적용 ${t.tier1_stats?.applied ?? 0}회 · 모양으로 다시 찾음 ${t.tier1_stats?.reacq_ok ?? 0}회`}
      {t.tier1_mode !== "off" && <Info>놓친 물체는 0.3초마다 화면 전체에서 <b>기억한 모양·색</b>과 맞는 것을 찾고, 같은 곳에서 두 번 연속 맞으면
        추적을 되살립니다. 닮은 물체가 둘 이상이면 옮겨붙지 않게 일부러 고르지 않습니다.</Info>}
    </p>
    {t.tier1_error && <p className="error small">모델 보정 오류: {t.tier1_error}</p>}
    <label className="check small"><input type="checkbox" checked={t.segmentation_enabled ?? false}
      onChange={(e) => putTracking({ segmentation_enabled: e.target.checked }).then(setT, () => undefined)} />
      주기적 segmentation 보정
      <Info>2초마다 현재 위치를 AI 모델로 다시 분할해 조금씩 쌓인 위치 오차를 바로잡습니다. 확실할 때만 적용합니다.</Info></label>
    {t.segmentation_enabled && <div className="field small">
      <label>재분할 주기 <select aria-label="재분할 주기" value={t.segmentation_hz ?? .5}
        onChange={(e) => putTracking({ segmentation_hz: Number(e.target.value) }).then(setT, () => undefined)}>
        <option value={.25}>0.25 Hz · 4초</option><option value={.5}>0.5 Hz · 2초 (기본)</option><option value={1}>1 Hz · 1초</option>
      </select></label>
      <p className="muted">부하 반영 {(t.segmentation_effective_hz ?? .5).toFixed(2)} Hz · 보정 {t.segmentation_stats?.applied ?? 0}회 · 제외 {t.segmentation_stats?.rejected ?? 0}회</p>
      {t.segmentation_backend === "grabcut" && <p className="warn">모델을 사용할 수 없어 GrabCut으로 재분할합니다.</p>}
    </div>}
    {t.segmentation_error && <p className="error small">재분할 오류: {t.segmentation_error}</p>}
    {t.hands_available && <label className="check small" title="손 영역을 물체 측정에서 빼고, 쥔 손의 움직임으로 추적을 이어 갑니다. 손 추적(CPU)이 계속 돕니다.">
      <input type="checkbox" checked={t.hand_occlusion} onChange={(e) => putTracking(e.target.checked).then(setT, () => undefined)} />
      손 가림 처리 (손 인식)
      <Info>손이 덮은 부분을 물체에서 빼고, 쥔 손의 움직임으로 추적을 이어 갑니다. 손 인식이 계속 돌아 CPU를 더 씁니다.</Info>
    </label>}
    </div>
  );
}

const OBJECT_INFO = <>등록한 물체·펜의 상태와 축 값입니다. 등록할 때 <b>모양과 색을 기억</b>해 두었다가, 가려지거나 화면 밖에 나갔다 와도
  기억한 모양으로 다시 찾아 추적을 이어 갑니다. 잘못 잡혔으면 <b>[다시 선택]</b>으로 모양을 새로 기억시키세요.</>;

export function ObjectPanel() {
  const objects = useApp((s) => s.objects);
  const selectedId = useApp((s) => s.selectedId);
  const [editId, setEditId] = useState<number | null>(null);
  const select = useApp((s) => s.select);

  if (objects.length === 0) {
    return (
      <Panel title="물체" tour="objects" info={OBJECT_INFO}>
        <HandOcclusionToggle />
        <p className="muted">아직 등록된 물체가 없습니다. 영상에서 물체를 드래그하세요.</p>
      </Panel>
    );
  }
  return (
    <Panel title="물체" tour="objects" info={OBJECT_INFO}>
      <HandOcclusionToggle />
      <div className="obj-tabs" role="tablist">
        {objects.map((o) => (
          <button
            key={o.id}
            type="button"
            role="tab"
            aria-selected={o.id === selectedId}
            className={o.id === selectedId ? "active" : ""}
            style={{ borderColor: o.color }}
            onClick={() => { select(o.id); setEditId(o.id); }}
            title="이름을 눌러 변경"
          >
            <span className="dot" style={{ background: o.color }} aria-hidden="true" />
            {o.name}
          </button>
        ))}
      </div>
      {objects.filter((o) => o.id === selectedId).map((o) => <ObjectDetail key={o.id} obj={o} editRequested={editId === o.id} onEditDone={() => setEditId(null)} />)}
    </Panel>
  );
}

function ObjectDetail({ obj, editRequested, onEditDone }: { obj: ObjectInfo; editRequested: boolean; onEditDone: () => void }) {
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
  useEffect(() => { if (editRequested) { setName(obj.name); setEditing(true); } }, [editRequested, obj.name]);
  const cancelName = () => { setEditing(false); setName(obj.name); onEditDone(); };
  const saveName = async () => {
    if (saveLock.current) return;
    const trimmed = name.trim();
    if (!trimmed || trimmed === obj.name) { cancelName(); return; }
    saveLock.current = true; setSaving(true);
    try {
      const result = await renameObject(obj.id, trimmed);
      const app = useApp.getState();
      app.setObjects(app.objects.map(o => o.id === obj.id ? { ...o, name: result.name } : o));
      if (mounted.current) { setErr(null); setEditing(false); onEditDone(); }
    } catch (e) { if (mounted.current) setErr(String(e)); }
    finally { saveLock.current = false; if (mounted.current) setSaving(false); }
  };
  const nextCandidate = async () => {
    if (candidateLock.current) return;
    candidateLock.current = true; setCandidateBusy(true);
    const next = (attempted + 1) % obj.candidates;
    setAttempted(next); // 실패한 후보도 시도한 번호로 기억해 다음 클릭에서 건너뛴다.
    try {
      const result = await pickCandidate(obj.id, next);
      const app = useApp.getState();
      // 서버는 교체 시 새 ID를 발급한다. 늦은 UI 갱신까지 기다리지 않는다.
      if (app.objects.some(o => o.id === obj.id)) app.setObjects(app.objects.map(o => o.id === obj.id ? result : o));
      else if (app.objects.some(o => o.id === result.id)) app.select(result.id);
      if (mounted.current) setErr(null);
    } catch (e) { if (mounted.current) setErr(`${String(e)} · 후보 ${next + 1}은 적용하지 못했습니다. 다시 누르면 다음 후보를 시도합니다.`); }
    finally { candidateLock.current = false; if (mounted.current) setCandidateBusy(false); }
  };
  const run = (p: Promise<unknown>) => p.then(() => setErr(null), (e: unknown) => setErr(String(e)));
  const reselecting = useApp((s) => s.reselectId === obj.id);

  return (
    <div role="tabpanel">
      <div className="obj-head">
        {editing ? (
          <form onSubmit={(e) => { e.preventDefault(); void saveName(); }}>
            <input name="name" value={name} onChange={e => setName(e.target.value)} maxLength={40}
              aria-label={obj.kind === 'pen' ? '펜 이름' : '물체 이름'} autoFocus disabled={saving}
              onFocus={e => e.currentTarget.select()} onBlur={() => { if (editing) void saveName(); }}
              onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cancelName(); } }} />
          </form>
        ) : (
          <button type="button" className="link" onClick={() => { setName(obj.name); setEditing(true); }} title="이름 바꾸기">
            {obj.name}
          </button>
        )}
        <span className={`state state-${obj.state}`}>{STATE_LABEL[obj.state]}</span>
        <span className="muted">신뢰도 {Math.round(obj.confidence * 100)}%</span>
        <Info>추적 중 / 쥠 / 가려짐 / 찾는 중 / 놓침. 가려지거나 놓치면 기억한 모양으로 스스로 다시 찾습니다.</Info>
      </div>

      <dl className="axes">
        {AXIS_NAMES.map((a) => {
          const v = obj.axes[a];
          const L = AXIS_LABEL[a];
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
        무늬 {Math.round(obj.texture * 100)}% · 배경 대비 {Math.round(obj.contrast * 100)}%
        <Info>무늬가 많고 배경과 색이 뚜렷이 다를수록 추적이 안정적입니다. 둘 다 낮으면 경고가 표시됩니다.</Info>
      </p>
      {obj.warnings.map((w) => (
        <p key={w} className="warn small">{w}</p>
      ))}

      <div className="row">
        <button type="button" className="act-config" onClick={() => run(setNeutral(obj.id))}
          title="지금 자세를 축 값 0 으로"><ActionIcon name="target" />현재 위치를 중립으로</button>
        <button type="button" className={reselecting ? "active" : "act-output"} aria-pressed={reselecting}
          onClick={() => {
            const app = useApp.getState();
            if (reselecting) { app.setReselect(null); return; }
            app.setSelectMode("object");
            app.setReselect(obj.id);
            document.querySelector('[data-tour="camera"]')?.scrollIntoView({ behavior: "smooth", block: "center" });
          }}>
          <ActionIcon name="target" />{reselecting ? "다시 선택 취소" : "다시 선택"}
        </button>
        <Info>추적이 어긋나면 누르고 영상에서 {obj.kind === "pen" ? "펜촉 → 반대쪽 끝 두 점을 다시 찍으세요" : "물체를 다시 드래그(또는 클릭)하세요"}.
          이름·색·매핑·마우스 연결은 그대로 두고 <b>모양 기억</b>만 새로 합니다. 선택된 물체는 영상에서 <b>Shift+드래그</b>로도 바로 다시 선택됩니다. ESC 취소.</Info>
        {obj.candidates > 1 && (
          <button type="button" disabled={candidateBusy} onClick={() => void nextCandidate()}
            title="같은 선택에서 분할기가 낸 다른 모양으로 바꿉니다 (새 id)">
            다른 분할 후보 ({attempted + 1}/{obj.candidates})
          </button>
        )}
        <button type="button" className="danger" onClick={() => run(deleteObject(obj.id))}><ActionIcon name="trash" />삭제</button>
      </div>
      {err && <p className="error small" role="alert">{err}</p>}
    </div>
  );
}
