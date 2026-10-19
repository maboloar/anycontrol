import { useEffect, useState } from "react";
import { forgetObjectMemory, getObjectMemory } from "../api";
import { useApp } from "../store";
import { ActionIcon } from "./ActionIcon";
import { t as tr } from "../i18n";
import type { MemorySnapshot, ObjectMemory } from "../protocol";
import { Info } from "./Info";

const KIND_LABEL: Record<MemorySnapshot["kind"], () => string> = {
  registration: () => tr("등록 모습", "Registered"),
  anchor: () => tr("AI 앵커", "AI anchor"),
  reacquired: () => tr("재획득", "Re-found"),
};

const KIND_HINT: Record<MemorySnapshot["kind"], () => string> = {
  registration: () => tr("등록·다시 선택 때 기억한 모습. 모양·색 기억과 AI 모델의 기준 프레임입니다.", "Remembered at registration or reselect. Basis of the shape/color memory and the AI model."),
  anchor: () => tr("추적 중 AI 모델이 '매우 확실하고 크기가 다름'으로 추가 기억한 모습 (최대 3개).", "Extra views the AI model stored while confident at a different size (up to 3)."),
  reacquired: () => tr("놓친 뒤 기억한 모양으로 다시 찾아 AI 모델 기억을 다시 고정한 순간.", "The moment the object was re-found by shape and the AI memory was re-anchored."),
};

function fmt(v: number | string | null): string {
  return typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(2)) : String(v ?? "-");
}

const snapKey = (s: MemorySnapshot) => `${s.kind}-${s.t}`;

/** 물체 실시간 기억 보기·관리. 열려 있는 동안 1초마다 새로 받는다. AI 앵커·재획득은 체크해서 지울 수 있다
 * (등록 모습은 다시 찾는 기준이라 지울 수 없고 [다시 선택]으로만 바뀐다). 세부 수치는 고급 모드에서만. */
export function MemoryView({ id }: { id: number }) {
  const [mem, setMem] = useState<ObjectMemory | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const advanced = useApp((s) => s.devMode);
  useEffect(() => {
    let alive = true;
    const load = () => getObjectMemory(id).then(m => { if (alive) { setMem(m); setErr(null); } },
      (e: unknown) => { if (alive) setErr(String(e)); });
    void load();
    const timer = window.setInterval(load, 1000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [id]);

  if (err) return <p className="error small" role="alert">{err}</p>;
  if (!mem) return <p className="small muted">{tr("물체 기억 불러오는 중…", "Loading object memory…")}</p>;
  const deletable = mem.snapshots.filter((s) => s.kind !== "registration");
  const picked = deletable.filter((s) => checked.has(snapKey(s)));
  const toggle = (s: MemorySnapshot, on: boolean) => setChecked((c) => {
    const n = new Set(c);
    if (on) n.add(snapKey(s)); else n.delete(snapKey(s));
    return n;
  });
  const forget = async () => {
    if (!picked.length) return;
    setBusy(true);
    try {
      const r = await forgetObjectMemory(id, picked.map((s) => ({ kind: s.kind, t: s.t })));
      setMem(r); setChecked(new Set()); setErr(null);
      setNote(tr(`${r.removed}개를 지웠습니다.`, `Deleted ${r.removed}.`));
    } catch (e) { setNote(String(e)); }
    finally { setBusy(false); }
  };
  return (
    <section className="memory" aria-label={tr("물체 기억", "Object memory")}>
      <p className="small muted">
        {mem.lost_for_s === null
          ? tr("지금 보이는 중 · 놓치면 아래 기억으로 다시 찾습니다.", "Visible now · if lost, it is re-found with the memory below.")
          : tr(`놓친 지 ${mem.lost_for_s.toFixed(1)}초 · 기억과 맞는 것을 찾는 중`, `Lost for ${mem.lost_for_s.toFixed(1)}s · searching for a match`)}
        {advanced && mem.tier1 && tr(` · AI 기억: 앵커 ${mem.tier1.anchors}/${mem.tier1.max_anchors ?? "-"}, 최근 ${mem.tier1.recent}프레임`,
          ` · AI memory: anchors ${mem.tier1.anchors}/${mem.tier1.max_anchors ?? "-"}, recent ${mem.tier1.recent} frames`)}
      </p>
      {advanced && mem.still && (
        <p className="small muted" data-testid="still-state">
          {mem.still.locked ? tr("정지 잠금: 잠김 (포즈·윤곽 고정)", "Still lock: locked (pose and outline held)") : tr("정지 잠금: 풀림", "Still lock: released")}
          {tr(` · 잠금 ${mem.still.locks}회 · 거절한 측정 ${Object.values(mem.still.rejected).reduce((a, b) => a + b, 0)}회`,
            ` · locked ${mem.still.locks}× · rejected measurements ${Object.values(mem.still.rejected).reduce((a, b) => a + b, 0)}`)}
        </p>
      )}
      <div className="memory-grid">
        {mem.snapshots.map((s) => (
          <figure key={snapKey(s)} title={KIND_HINT[s.kind]()} className={checked.has(snapKey(s)) ? "picked" : ""}>
            <img src={s.image} alt={`${KIND_LABEL[s.kind]()} ${s.age_s}s`} />
            <figcaption>
              {s.kind !== "registration" && <input type="checkbox" checked={checked.has(snapKey(s))} disabled={busy}
                aria-label={tr(`${KIND_LABEL[s.kind]()} ${s.age_s}초 전 선택`, `Select ${KIND_LABEL[s.kind]()} ${s.age_s}s ago`)}
                onChange={(e) => toggle(s, e.target.checked)} />}
              {KIND_LABEL[s.kind]()} · {tr(`${s.age_s}초 전`, `${s.age_s}s ago`)}
              {advanced && Object.keys(s.info).length > 0 && <span className="muted"> {Object.entries(s.info).map(([k, v]) => `${k} ${fmt(v)}`).join(" · ")}</span>}
            </figcaption>
          </figure>
        ))}
        {advanced && mem.shape && (
          <figure title={tr("위치·크기·회전을 맞춘 정규화 모양. 재획득은 후보 마스크와 이 모양의 정렬 IoU를 봅니다.", "Normalized shape (position, size, rotation aligned). Re-finding compares candidates to this by aligned IoU.")}>
            <img src={mem.shape.template} alt={tr("모양 기억", "Shape memory")} />
            <figcaption>{tr("모양 기억", "Shape memory")} · {tr("길쭉함", "elongation")} {mem.shape.elongation}</figcaption>
          </figure>
        )}
      </div>
      <div className="row small memory-actions">
        <button type="button" className="danger" disabled={busy || !picked.length} onClick={() => void forget()}>
          <ActionIcon name="trash" />{tr(`선택한 기억 삭제 (${picked.length})`, `Delete selected (${picked.length})`)}</button>
        {deletable.length > 0 && <button type="button" disabled={busy} onClick={() => setChecked(picked.length === deletable.length ? new Set() : new Set(deletable.map(snapKey)))}>
          {picked.length === deletable.length ? tr("선택 해제", "Clear selection") : tr("모두 선택", "Select all")}</button>}
        <span className="muted">{deletable.length ? tr("잘못된 물체를 기억했다면 골라 지우세요. 등록 모습은 [다시 선택]으로만 바뀝니다.", "Delete memories of the wrong thing. The registered view changes only with [Reselect].")
          : tr("아직 추가로 쌓인 기억이 없습니다.", "No extra memories yet.")}</span>
        {note && <span role="status">{note}</span>}
      </div>
      {advanced && mem.shape && mem.shape.palette.length > 0 && (
        <div className="memory-palette" aria-label={tr("색 기억", "Color memory")}>
          <span className="small muted">{tr("색 기억", "Color memory")}</span>
          {mem.shape.palette.map((c) => (
            <span key={c.hex} className="swatch" style={{ background: c.hex, flexGrow: c.weight }} title={`${c.hex} · ${Math.round(c.weight * 100)}%`} />
          ))}
        </div>
      )}
      {advanced && <p className="small muted">
        {mem.reacquire.enabled
          ? tr(`재획득 탐색 ${mem.reacquire.searches}회 · 복구 ${mem.reacquire.recovered}회`, `Re-find searches ${mem.reacquire.searches} · recovered ${mem.reacquire.recovered}`)
          : tr("재획득 꺼짐 (AI 모델 없음)", "Re-finding off (no AI model)")}
        {mem.reacquire.last && tr(` · 최근 후보 IoU/Hu/색 ${mem.reacquire.last}`, ` · last candidate IoU/Hu/color ${mem.reacquire.last}`)}
        <Info>{tr(`합격 기준: 정렬 IoU ≥ ${mem.reacquire.thresholds.iou}, Hu 거리 ≤ ${mem.reacquire.thresholds.hu}, 색 유사도 ≥ ${mem.reacquire.thresholds.color}. 같은 곳에서 두 번 연속 합격해야 복구합니다. 여기 기억은 추적 중에 바뀌지 않으며 [다시 선택]으로만 새로 만듭니다.`,
          `Pass if aligned IoU ≥ ${mem.reacquire.thresholds.iou}, Hu distance ≤ ${mem.reacquire.thresholds.hu}, color similarity ≥ ${mem.reacquire.thresholds.color}, twice in a row at the same spot. This memory does not change while tracking; only [Reselect] renews it.`)}</Info>
      </p>}
    </section>
  );
}
