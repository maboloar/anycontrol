import { loadCustomJacks, saveCustomJacks } from "../patch";
import { useEffect, useState } from "react";
import { objectRef, objectLabel, findObject } from "../objectRefs";
import { ActionIcon } from "./ActionIcon";
import { learnStart, learnStop } from "../api";
import { INPUT_AXIS_LABEL, KEY_RE, MOUSE_LABEL, PAD_AXIS_LABEL, PAD_BUTTON_LABEL, applySuggestion, makeMapping, outputKind, withInput, withOutput } from "../mapping";
import { GAMEPAD_AXES, GAMEPAD_BUTTONS, INPUT_AXES, type InputAxis, type MapInput, type Mapping, type MapOutput, type Transform, type Profile } from "../protocol";
import { useApp } from "../store";
import { t as L } from "../i18n";
import { sensitivity, withSensitivity } from "../mappingSensitivity";
export function MappingRow({ m, names, onChange, onDelete, onError, onValidity, creating = false }: {
  m: Mapping; names: string[]; onChange: (m: Mapping) => void; onDelete: () => void; onError: (e: unknown) => void; onValidity?: (valid: boolean) => void; creating?: boolean;
}) {
  const live = useApp((s) => s.live.mapping?.live.find((l) => l.id === m.id));
  const objects = useApp((s) => s.objects);
  const [open, setOpen] = useState(false);
  const [learning, setLearning] = useState(false);
  const t = m.transform;
  const kind = outputKind(m.output);
  const tr = (p: Partial<Transform>) => onChange({ ...m, transform: { ...t, ...p } });
  const objName = "object" in m.input ? m.input.object : (names[0] ?? "");
  const objOpts = names.includes(objName) ? names : [objName, ...names];

  const setSource = (src: MapInput["source"]) => {
    const inp: MapInput = src === "hand" ? { source: "hand", gesture: "pinch" }
      : src === "object" ? { source: "object", object: objName, axis: "x" } : { source: src, object: objName };
    onChange(withInput(m, inp));
  };
  const setTarget = (tg: MapOutput["target"]) => {
    const out: MapOutput = tg === "gamepad_axis" ? { target: tg, axis: "left_x" } : tg === "gamepad_button"
      ? { target: tg, button: "a" } : tg === "key" ? { target: tg, key: "space" } : tg === "control" ? { target: tg, name: "custom", kind: "digital" } : { target: tg, action: "move_x" };
    onChange(withOutput(m, out));
  };
  const learn = async () => {
    const o = findObject(objName, objects);
    if (!o) return onError(L("먼저 물체를 등록하세요", "Register an object first"));
    try {
      setLearning(true);
      await learnStart(o.id);
      await new Promise((r) => setTimeout(r, 2500));
      const r = await learnStop();
      const best = r.suggestions[0];
      if (!best) throw new Error(L("움직임이 잡히지 않았습니다", "No movement detected"));
      onChange(applySuggestion(m, objectRef(o), best));
    } catch (e) {
      onError(e);
    } finally {
      setLearning(false);
    }
  };
  const val = live?.value ?? 0;
  const bar = kind === "bipolar"
    ? { left: `${50 + Math.min(0, val) * 50}%`, width: `${Math.abs(val) * 50}%` } : { left: 0, width: `${val * 100}%` };

  return (
    <div className={`map-row ${m.enabled ? "" : "off"}`}>
      <div className="row">
        <input type="checkbox" aria-label={L("사용", "Enabled")} checked={m.enabled} onChange={(e) => onChange({ ...m, enabled: e.target.checked })} />
        <input aria-label={L("설명", "Label")} placeholder={L("설명 (예: 조향)", "Label (e.g. steer)")} value={m.label} maxLength={60}
          onChange={(e) => onChange({ ...m, label: e.target.value })} />
        <span className="bar" aria-hidden="true"><span className="fill" style={bar} /></span>
        <span className="val small">{live?.active ? (live.raw ?? 0).toFixed(3) : "–"}</span>
      </div>
      <div className="row">
        <select aria-label={L("입력 종류", "Input type")} value={m.input.source} onChange={(e) => setSource(e.target.value as MapInput["source"])}>
          <option value="object">{L("물체 축", "Object axis")}</option><option value="visible">{L("물체 보임", "Object visible")}</option>
          <option value="pen">{L("펜촉 닿음", "Pen tip touching")}</option><option value="hand">{L("맨손 입력", "Hand input")}</option>
          <option value="touch">{L("손이 물체에 닿음", "Hand touches object")}</option>
        </select>
        {"object" in m.input && (
          <select aria-label={L("물체", "Object")} value={objName} onChange={(e) => onChange({ ...m, input: { ...m.input, object: e.target.value } as MapInput })}>
            {objOpts.map((n) => <option key={n} value={n}>{objectLabel(n, objects)}</option>)}
          </select>
        )}
        {m.input.source === "object" && (
          <select aria-label={L("축", "Axis")} value={m.input.axis}
            onChange={(e) => onChange(withInput(m, { source: "object", object: objName, axis: e.target.value as InputAxis }))}>
            {INPUT_AXES.map((a) => <option key={a} value={a}>{INPUT_AXIS_LABEL[a]}</option>)}
          </select>
        )}
        {m.input.source === "hand" && (
          <select aria-label={L("제스처", "Gesture")} value={m.input.gesture}
            onChange={(e) => onChange(withInput(m, { source: "hand", gesture: e.target.value as "pinch" | "pinch_middle" | "x" | "y" }))}>
            <option value="x">{L("손바닥 좌우 (영상 X)", "Palm left/right (video X)")}</option><option value="y">{L("손바닥 상하 (영상 Y)", "Palm up/down (video Y)")}</option><option value="pinch">{L("엄지 + 검지 집게", "Thumb + index pinch")}</option><option value="pinch_middle">{L("엄지 + 중지 집게", "Thumb + middle pinch")}</option>
          </select>
        )}
        <span aria-hidden="true">→</span>
        <select aria-label={L("출력 종류", "Output type")} value={m.output.target} onChange={(e) => setTarget(e.target.value as MapOutput["target"])}>
          <option value="gamepad_axis">{L("게임패드 축", "Gamepad axis")}</option><option value="gamepad_button">{L("게임패드 버튼", "Gamepad button")}</option>
          <option value="key">{L("키", "Key")}</option><option value="mouse">{L("마우스", "Mouse")}</option>
          {m.output.target === "control" && <option value="control">{L("데모 조작", "Demo control")}</option>}
        </select>
        {m.output.target === "gamepad_axis" && (
          <select aria-label={L("축", "Axis")} value={m.output.axis} onChange={(e) => onChange(withOutput(m, { target: "gamepad_axis", axis: e.target.value as "lt" }))}>
            {GAMEPAD_AXES.map((a) => <option key={a} value={a}>{PAD_AXIS_LABEL[a]}</option>)}
          </select>
        )}
        {m.output.target === "gamepad_button" && (
          <select aria-label={L("버튼", "Button")} value={m.output.button} onChange={(e) => onChange({ ...m, output: { target: "gamepad_button", button: e.target.value as "a" } })}>
            {GAMEPAD_BUTTONS.map((b) => <option key={b} value={b}>{PAD_BUTTON_LABEL[b]}</option>)}
          </select>
        )}
        {m.output.target === "key" && (
          <KeyInput value={m.output.key} onValidity={onValidity} onChange={(key) => onChange({ ...m, output: { target: "key", key } })} />
        )}
        {m.output.target === "control" && <span className="small muted">{m.output.name}</span>}
        {m.output.target === "mouse" && (
          <select aria-label={L("마우스 동작", "Mouse action")} value={m.output.action}
            onChange={(e) => onChange(withOutput(m, { target: "mouse", action: e.target.value as "left" }))}>
            {Object.entries(MOUSE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        )}
      </div>
      <div className="row">
        {(m.input.source === "object" || m.input.source === "hand" && ["x", "y"].includes(m.input.gesture)) && <label>{L("민감도", "Sensitivity")} ×{sensitivity(m).toFixed(1)} <input aria-label={L("매핑 민감도", "Mapping sensitivity")} type="range" min="0.3" max="4" step="0.1" value={Math.max(.3, Math.min(4, sensitivity(m)))} onChange={e => onChange(withSensitivity(m, Number(e.target.value)))} /></label>}
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}>{L("세부 설정", "Details")}</button>
        {m.input.source !== "hand" && (
          <button type="button" disabled={learning} onClick={learn} title={L("2.5초 동안 원하는 방식으로 물체를 움직이세요", "Move the object the way you want for 2.5 seconds")}>
            <ActionIcon name="tune" />{learning ? L("움직여 보세요…", "Move it now…") : L("보여 주며 설정", "Learn by showing")}
          </button>
        )}
        {!creating && <button type="button" className="danger" onClick={onDelete}><ActionIcon name="trash" />{L("매핑 해제", "Unmap")}</button>}
      </div>
      {open && (
        <div className="map-detail small">
          <label>{L("방식", "Mode")} <select value={t.mode} onChange={(e) => tr({ mode: e.target.value as "absolute" })}>
            <option value="absolute">{L("위치", "Position")}</option><option value="velocity">{L("변화 속도", "Rate of change")}</option></select></label>
          <label>{L("범위", "Range")} <NumIn v={t.range[0]} on={(v) => v < t.range[1] && tr({ range: [v, t.range[1]] })} />
            ~ <NumIn v={t.range[1]} on={(v) => v > t.range[0] && tr({ range: [t.range[0], v] })} /></label>
          <label><input type="checkbox" checked={t.invert} onChange={(e) => tr({ invert: e.target.checked })} /> {L("반전", "Invert")}</label>
          <label>{L("데드존", "Deadzone")} {t.deadzone.toFixed(2)} <input type="range" min={0} max={0.5} step={0.01} value={t.deadzone}
            onChange={(e) => tr({ deadzone: Number(e.target.value) })} /></label>
          <label>{L("곡선", "Curve")} <select value={t.curve} onChange={(e) => tr({ curve: e.target.value as "expo" })}>
            <option value="linear">{L("직선", "Linear")}</option><option value="expo">{L("expo (가운데 둔하게)", "Expo (softer center)")}</option></select></label>
          {kind === "digital" ? (
            <label>{L("누름/뗌", "Press/release")} <NumIn v={t.on} on={(v) => v >= t.off && v <= 1 && tr({ on: v })} />
              / <NumIn v={t.off} on={(v) => v <= t.on && v >= 0 && tr({ off: v })} /></label>
          ) : (
            <label>{L("부드럽게(ms)", "Smoothing (ms)")} <NumIn v={t.smoothing_ms} on={(v) => v >= 0 && v <= 1000 && tr({ smoothing_ms: v })} /></label>
          )}
          <label>{L("놓쳤을 때", "When lost")} <select value={t.on_lost} onChange={(e) => tr({ on_lost: e.target.value as "hold" })}>
            <option value="center">{L("서서히 중립", "Ease to neutral")}</option><option value="hold">{L("마지막 값 유지", "Hold last value")}</option>
            <option value="release">{L("즉시 중립", "Neutral immediately")}</option></select></label>
        </div>
      )}
    </div>
  );
}

function NumIn({ v, on }: { v: number; on: (v: number) => unknown }) {
  const [s, setS] = useState(String(v));
  useEffect(() => setS(String(v)), [v]);
  return <input className="num" inputMode="decimal" value={s} aria-label={L("숫자", "Number")}
    onChange={(e) => { setS(e.target.value); const n = Number(e.target.value); if (e.target.value !== "" && Number.isFinite(n)) on(n); }} />;
}

function KeyInput({ value, onChange, onValidity }: { value: string; onChange: (k: string) => void; onValidity?: (valid: boolean) => void }) {
  const [s, setS] = useState(value);
  useEffect(() => setS(value), [value]);
  const ok = KEY_RE.test(s.toLowerCase());
  return <input aria-label={L("키", "Key")} aria-invalid={!ok} className={`num ${ok ? "" : "bad"}`} value={s}
    onChange={(e) => { setS(e.target.value); onValidity?.(KEY_RE.test(e.target.value.toLowerCase())); if (KEY_RE.test(e.target.value.toLowerCase())) onChange(e.target.value.toLowerCase()); }} />;
}

export function AddMappingForm({ draft, edit }: { draft: Profile; edit: (p: Profile, immediate?: boolean) => void }) {
  const objects = useApp(s => s.objects);
  const names = objects.map(objectRef);
  const [pending, setPending] = useState<Mapping | null>(null);
  const [error, setError] = useState("");
  const [valid, setValid] = useState(true);
  if (!pending) return <button type="button" className="act-config" onClick={() => { setValid(true); setPending(makeMapping(draft.mappings, names.length ? { source: "object", object: names[0]!, axis: "x" } : { source: "hand", gesture: "x" }, { target: "gamepad_axis", axis: GAMEPAD_AXES.find(a => !draft.mappings.some(m => m.output.target === "gamepad_axis" && m.output.axis === a)) ?? "left_x" })); }}>{L("+ 매핑 추가", "+ Add mapping")}</button>;
  return <div className="custom-jack" role="group" aria-label={L("매핑 추가", "Add mapping")}>
    <MappingRow creating m={pending} names={names} onChange={m => { setPending(m); if (m.output.target !== "key") setValid(true); }} onValidity={setValid} onDelete={() => setPending(null)} onError={e => setError(String(e))} />
    <button type="button" className="act-go" disabled={!valid || draft.mappings.length >= 64} onClick={() => {
      if (pending.label.trim()) {
        const input = pending.input;
        saveCustomJacks([...loadCustomJacks(), { id: `c-${Date.now().toString(36)}-${pending.id}`, label: pending.label.trim(), output: pending.output,
          input: input.source === "object" ? "axis" : input.source === "hand" ? (["x", "y"].includes(input.gesture) ? "axis" : "touch") : input.source,
          axis: input.source === "object" ? input.axis : input.source === "hand" && input.gesture === "x" ? "x" : "y",
          handGesture: input.source === "hand" ? input.gesture : undefined, transform: pending.transform }]);
      }
      edit({ ...draft, mappings: [...draft.mappings, { ...pending, label: pending.label.trim(), id: makeMapping(draft.mappings, pending.input, pending.output).id }] }, true); setPending(null); }}>{L("추가", "Add")}</button>
    <button type="button" onClick={() => setPending(null)}>{L("취소", "Cancel")}</button>
    {error && <p role="alert">{error}</p>}
  </div>;
}
