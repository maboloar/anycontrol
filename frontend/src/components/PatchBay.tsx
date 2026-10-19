import { objectLabel } from "../objectRefs";
import { registerPatchConnection } from "../patchConnections";
import { ResetMappingsButton } from "./ResetMappingsButton";
import { useEffect, useId, useLayoutEffect, useMemo, useState } from "react";
import { MappingRow, AddMappingForm } from "./MappingEditor";
import { useDraftStore } from "../mappingDraft";
import { inferredFns, registerFns, unregisterFns, sameOutput, cables, connect, customFn, disconnect, loadCustomJacks, saveCustomJacks, type CustomJack, type PatchFn } from "../patch";
import { type Profile } from "../protocol";
import { useApp } from "../store";
import { t } from "../i18n";
import { PatchCables, PatchJack } from "./PatchCables";

/** 패치 베이: 기능 잭 목록 + 케이블. 케이블이나 연결된 잭 이름을 누르면 세부 조정(입력 종류·감도·반전·빼기)을 연다.
 * allowCustom 이면 사용자가 잭을 직접 만들고 지울 수 있다. */
export function PatchBay({ fns, title, allowCustom = false, draft: full, edit, tour, hide }: {
  fns: PatchFn[]; title?: string; allowCustom?: boolean; draft: Profile; edit: (p: Profile, immediate?: boolean) => void; tour?: string;
  /** 이 패치 베이에서 숨길 매핑 (케이블·추정 잭·세부 설정에 나오지 않음). 편집할 때는 그대로 보존된다 */
  hide?: (m: Profile["mappings"][number]) => boolean;
}) {
  // 매 렌더마다 새 객체를 만들지 않는다 (라이브 값으로 매 프레임 다시 그려져도 확인 버튼 상태 등이 풀리지 않게)
  const draft = useMemo(() => hide ? { ...full, mappings: full.mappings.filter((m) => !hide(m)) } : full, [full, hide]);
  const [error, setError] = useState("");
  const objects = useApp((s) => s.objects);
  const [custom, setCustom] = useState<CustomJack[]>(loadCustomJacks);
  useEffect(() => { const update = () => setCustom(loadCustomJacks()); window.addEventListener("anycontrol.custom-jacks.changed", update); return () => window.removeEventListener("anycontrol.custom-jacks.changed", update); }, []);
  const [selected, setSelected] = useState<string | null>(null);
  const known = allowCustom ? [...fns, ...custom.map(customFn)] : fns;
  const inferred = allowCustom ? inferredFns(draft, known) : [];
  const group = `inferred-${useId()}`;
  useLayoutEffect(() => { registerFns(group, inferred); return () => unregisterFns(group); }, [group, inferred]);
  const shown = [...known, ...inferred];
  const wires = cables(draft, shown);
  useEffect(() => registerPatchConnection((object, fn) => {
    const d = useDraftStore.getState().draft;
    if (d) edit(connect(d, object, fn), true);
  }), [edit]);
  // 세부 조정 창은 늘 떠 있다: 고른 케이블, 없으면 첫 케이블
  const sel = draft.mappings.find((m) => m.id === selected && wires.some(w => w.id === m.id)) ?? draft.mappings.find((m) => wires.some((w) => w.id === m.id)) ?? null;
  const live = useApp((s) => s.live.mapping?.live);
  const selectCable = (id: string) => {
    setSelected(id);
    const wire = wires.find(w => w.id === id);
    if (!wire) return;
    const port = [...document.querySelectorAll<HTMLElement>("[data-jack]")].find(el => el.dataset.jack === `fn:${wire.fn}`);
    const rect = port?.getBoundingClientRect();
    const x = rect ? rect.left + rect.width / 2 : 0, y = rect ? rect.top + rect.height / 2 : 0;
    useApp.getState().setPatchDrag({ from: { kind: "fn", id: wire.fn }, x, y, startX: x, startY: y, sticky: true });
  };
  const removeCustom = (id: string) => {
    const removed = custom.find(c => c.id === id);
    const next = custom.filter(c => c.id !== id); setCustom(next); saveCustomJacks(next);
    if (removed) edit({ ...full, mappings: full.mappings.filter(m => !sameOutput(m.output, removed.output)) }, true);
  };
  return (
    <section className="patch-bay" data-tour={tour} aria-label={title ?? t("패치 베이: 기능 잭", "Patch bay: function jacks")}>
      <ResetMappingsButton draft={full} edit={edit} />   {/* 전체 초기화는 숨긴 연결(DJ 등)까지 모두 지운다 */}
      <PatchCables cables={wires} onCut={selectCable} onDisconnect={id => { edit(disconnect(full, id), true); setSelected(null); }} />
      <p className="small muted">{t(<>오른쪽 <b>물체·맨손 카드의 잭</b>을 끌어 아래 <b>기능 잭</b>에 놓으면 연결됩니다 (반대로 끌어도, 한 번씩 눌러도 됩니다). <b>기능 잭 또는 기존 케이블을 고른 뒤 영상 속 등록 물체를 클릭</b>해도 물체 카드에 연결됩니다. <b>케이블을 누르면</b> 세부 설정, <b>휠 클릭하면 매핑 해제</b>합니다.</>,
        <>Drag the <b>jack on an object or hand card</b> to a <b>function jack</b> (or the other way, or click one then the other). Or <b>select a function jack or existing cable, then click a registered object in the video</b> to connect its card. <b>Click a cable</b> to adjust it; <b>middle-click to unmap</b>.</>)}</p>
      <div className="patch-fns">
        {shown.map((f) => {
          const on = wires.find((w) => w.fn === f.id);
          // 입력이 들어오면 잭이 밝아진다 (값의 크기만큼)
          const v = on ? Math.min(1, Math.abs(live?.find((l) => l.id === on.id)?.value ?? 0)) : 0;
          return <div key={f.id} className={`patch-fn ${on ? "on" : ""} ${on && sel?.id === on.id ? "selected" : ""} ${v > 0.5 ? "firing" : ""}`}
            style={{ "--act": v } as React.CSSProperties} onClick={() => on && setSelected(on.id)}>
            <PatchJack side="fn" name={f.id} connected={Boolean(on)} />
            <span className="patch-meter" aria-hidden="true"><i style={{ height: `${v * 100}%` }} /></span>
            <button type="button" className="patch-fn-label" disabled={!on} onClick={() => on && setSelected(on.id)}
              title={on ? t("눌러서 세부 조정", "Click to adjust") : undefined}>
              <b>{f.label()}</b><small>{on ? `← ${objectLabel(on.object, objects)}` : f.hint()}</small></button>
            {f.custom && <button type="button" className="patch-x" aria-label={t(`${f.label()} 잭 삭제`, `Delete jack ${f.label()}`)} onClick={() => removeCustom(f.id)}>×</button>}
          </div>;
        })}
      </div>
      {sel && <MappingRow m={sel} names={objects.map(o => `#${o.id}`)} onError={e => setError(String(e))}
        onChange={(m) => { const p = useDraftStore.getState().draft; if (p) edit({ ...p, mappings: p.mappings.map(x => x.id === m.id ? m : x) }); }}
        onDelete={() => { edit(disconnect(full, sel.id), true); setSelected(null); }} />}
      {!sel && <div className="cable-editor muted small">{t("케이블을 연결하면 여기서 입력 종류·감도·방향을 조정합니다. 잭이나 케이블을 누르면 그 연결로 바뀝니다.", "Connect a cable to adjust its input, sensitivity and direction here. Click a jack or cable to switch to it.")}</div>}
      {allowCustom && <AddMappingForm draft={draft} edit={edit} />}
      {error && <p role="alert" className="error">{error}</p>}
      {!objects.length && <p className="small warn">{t("카메라에서 물체를 드래그해 등록하거나 기본 맨손 카드의 잭을 연결하세요.", "Register an object in the camera, or connect the built-in bare-hand jack.")}</p>}
    </section>
  );
}

