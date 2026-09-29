import { ActionIcon } from "./ActionIcon";
import { Panel } from "./Panel";
import { useEffect, useRef, useState } from "react";
import {
  deleteProfile, getMapping, learnStart, learnStop, listProfiles, loadProfile, putMapping, putOutputMode, saveProfile,
} from "../api";
import {
  INPUT_AXIS_LABEL, KEY_RE, MOUSE_LABEL, PAD_AXIS_LABEL, PAD_BUTTON_LABEL, applySuggestion, makeMapping, outputKind,
  preset, withInput, withOutput,
} from "../mapping";
import {
  GAMEPAD_AXES, GAMEPAD_BUTTONS, INPUT_AXES, type InputAxis, type MapInput, type Mapping, type MapOutput,
  type Profile, type ProfileSummary, type Transform,
} from "../protocol";
import { useApp } from "../store";
import { GamepadView, usePad } from "./GamepadView";

/** 매핑 편집기: 편집하면 0.3초 뒤 자동 적용. 출력은 '내보내기' 를 켜야 가상 컨트롤러로 나간다. */
const MAPPING_INFO = <>물체 축(좌우·깊이·기울기 등), 펜 접촉, 손 제스처를 게임패드 축·버튼·키·마우스에 연결합니다. <b>보기만</b>은 값만 계산하고, <b>내보내기</b>를 눌러야 가상 컨트롤러로 전달됩니다.</>;

export function MappingPanel() {
  const info = useApp((s) => s.mappingInfo);
  const setInfo = useApp((s) => s.setMappingInfo);
  const objects = useApp((s) => s.objects);
  const conn = useApp((s) => s.conn);
  const [draft, setDraft] = useState<Profile | null>(null);
  const [saved, setSaved] = useState<ProfileSummary[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const pad = usePad();
  const names = objects.map((o) => o.name);

  const fail = (e: unknown) => setErr(String(e instanceof Error ? e.message : e).replace(/^\d+ /, ""));
  useEffect(() => {
    if (conn !== "open") return;
    getMapping().then((i) => { setInfo(i); setDraft(i.profile); }, fail);
    listProfiles().then(setSaved, fail);
  }, [conn, setInfo]);

  const edit = (p: Profile) => {
    setDraft(p);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => putMapping(p).then((i) => { setInfo(i); setErr(null); }, fail), 300);
  };
  if (!draft || !info) return <Panel title="매핑 · 가상 게임패드" label="매핑" className="demo" info={MAPPING_INFO}><p className="muted">불러오는 중…</p></Panel>;

  const setM = (i: number, m: Mapping) => edit({ ...draft, mappings: draft.mappings.map((x, k) => (k === i ? m : x)) });
  const obj0 = names[0] ?? "물체 1";
  const add = () => edit({ ...draft, mappings: [...draft.mappings,
    makeMapping(draft.mappings, { source: "object", object: obj0, axis: "x" }, { target: "gamepad_axis", axis: "left_x" })] });
  const refresh = () => listProfiles().then(setSaved, fail);

  return (
    <Panel title="매핑 · 가상 게임패드" label="매핑" className="demo" info={MAPPING_INFO}>
      <div className="row">
        <input aria-label="프로필 이름" value={draft.name} maxLength={40}
          onChange={(e) => edit({ ...draft, name: e.target.value || "기본" })} />
        <button type="button" className="act-config" onClick={() => saveProfile(draft).then(refresh, fail)}><ActionIcon name="save" />저장</button>
        <select aria-label="저장된 프로필" value="" onChange={(e) => e.target.value && loadProfile(e.target.value).then(edit, fail)}>
          <option value="">불러오기…</option>
          {saved.map((p) => <option key={p.name} value={p.name}>{p.name} ({p.mappings})</option>)}
        </select>
        <button type="button" className="danger" disabled={!saved.some((p) => p.name === draft.name)}
          onClick={() => deleteProfile(draft.name).then(refresh, fail)}><ActionIcon name="trash" />프로필 삭제</button>
        <select aria-label="예시" value="" onChange={(e) => e.target.value && edit(preset(e.target.value as "racing", obj0))}>
          <option value="">예시…</option>
          <option value="racing">레이싱 (조향·가속·브레이크)</option>
          <option value="joystick">게임 조이스틱 (왼쪽 스틱 X/Y)</option>
          <option value="race-stick">레이싱 (좌우 이동 조향)</option>
          <option value="zombie">좀비 (위치 대응·충격파)</option>
          <option value="wasd">WASD 키</option>
          <option value="mouse">조이스틱 마우스</option>
        </select>
      </div>
      <div className="row" role="radiogroup" aria-label="출력">
        {(["observe", "send"] as const).map((m) => (
          <button key={m} type="button" role="radio" aria-checked={info.mode === m} className={`${m === "send" ? "act-output" : "act-safe"} ${info.mode === m ? "active" : ""}`}
            onClick={() => putOutputMode(m).then(setInfo, fail)}>
            <ActionIcon name={m === "observe" ? "virtual" : "play"} />{m === "observe" ? "보기만" : "가상 출력"}
          </button>
        ))}
        <span className="muted small">출력 대상 패널에서 실제 입력을 켜면 OS에도 적용 · ESC = 긴급 정지</span>
      </div>
      <div className="mapping-grid">
        <div>
          {draft.mappings.map((m, i) => (
            <MappingRow key={m.id} m={m} names={names} onChange={(x) => setM(i, x)}
              onDelete={() => edit({ ...draft, mappings: draft.mappings.filter((_, k) => k !== i) })} onError={fail} />
          ))}
          <button type="button" onClick={add}>+ 매핑 추가</button>
        </div>
        <GamepadView pad={pad} />
      </div>
      {info.warnings.map((w) => <p key={w} className="warn small">{w}</p>)}
      {err && <p className="error small" role="alert">{err}</p>}
    </Panel>
  );
}

function MappingRow({ m, names, onChange, onDelete, onError }: {
  m: Mapping; names: string[]; onChange: (m: Mapping) => void; onDelete: () => void; onError: (e: unknown) => void;
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
      ? { target: tg, button: "a" } : tg === "key" ? { target: tg, key: "space" } : { target: tg, action: "move_x" };
    onChange(withOutput(m, out));
  };
  const learn = async () => {
    const o = objects.find((x) => x.name === objName);
    if (!o) return onError("먼저 물체를 등록하세요");
    try {
      setLearning(true);
      await learnStart(o.id);
      await new Promise((r) => setTimeout(r, 2500));
      const r = await learnStop();
      const best = r.suggestions[0];
      if (!best) throw new Error("움직임이 잡히지 않았습니다");
      onChange(applySuggestion(m, o.name, best));
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
        <input type="checkbox" aria-label="사용" checked={m.enabled} onChange={(e) => onChange({ ...m, enabled: e.target.checked })} />
        <input aria-label="설명" placeholder="설명 (예: 조향)" value={m.label} maxLength={60}
          onChange={(e) => onChange({ ...m, label: e.target.value })} />
        <span className="bar" aria-hidden="true"><span className="fill" style={bar} /></span>
        <span className="val small">{live?.active ? (live.raw ?? 0).toFixed(3) : "–"}</span>
      </div>
      <div className="row">
        <select aria-label="입력 종류" value={m.input.source} onChange={(e) => setSource(e.target.value as MapInput["source"])}>
          <option value="object">물체 축</option><option value="visible">물체 보임</option>
          <option value="pen">펜촉 닿음</option><option value="hand">손 제스처</option>
        </select>
        {"object" in m.input && (
          <select aria-label="물체" value={objName} onChange={(e) => onChange({ ...m, input: { ...m.input, object: e.target.value } as MapInput })}>
            {objOpts.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        )}
        {m.input.source === "object" && (
          <select aria-label="축" value={m.input.axis}
            onChange={(e) => onChange(withInput(m, { source: "object", object: objName, axis: e.target.value as InputAxis }))}>
            {INPUT_AXES.map((a) => <option key={a} value={a}>{INPUT_AXIS_LABEL[a]}</option>)}
          </select>
        )}
        {m.input.source === "hand" && (
          <select aria-label="제스처" value={m.input.gesture}
            onChange={(e) => onChange({ ...m, input: { source: "hand", gesture: e.target.value as "pinch" } })}>
            <option value="pinch">엄지+검지</option><option value="pinch_middle">엄지+중지</option>
          </select>
        )}
        <span aria-hidden="true">→</span>
        <select aria-label="출력 종류" value={m.output.target} onChange={(e) => setTarget(e.target.value as MapOutput["target"])}>
          <option value="gamepad_axis">게임패드 축</option><option value="gamepad_button">게임패드 버튼</option>
          <option value="key">키</option><option value="mouse">마우스</option>
        </select>
        {m.output.target === "gamepad_axis" && (
          <select aria-label="축" value={m.output.axis} onChange={(e) => onChange(withOutput(m, { target: "gamepad_axis", axis: e.target.value as "lt" }))}>
            {GAMEPAD_AXES.map((a) => <option key={a} value={a}>{PAD_AXIS_LABEL[a]}</option>)}
          </select>
        )}
        {m.output.target === "gamepad_button" && (
          <select aria-label="버튼" value={m.output.button} onChange={(e) => onChange({ ...m, output: { target: "gamepad_button", button: e.target.value as "a" } })}>
            {GAMEPAD_BUTTONS.map((b) => <option key={b} value={b}>{PAD_BUTTON_LABEL[b]}</option>)}
          </select>
        )}
        {m.output.target === "key" && (
          <KeyInput value={m.output.key} onChange={(key) => onChange({ ...m, output: { target: "key", key } })} />
        )}
        {m.output.target === "mouse" && (
          <select aria-label="마우스 동작" value={m.output.action}
            onChange={(e) => onChange(withOutput(m, { target: "mouse", action: e.target.value as "left" }))}>
            {Object.entries(MOUSE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        )}
      </div>
      <div className="row">
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}>세부 설정</button>
        {m.input.source !== "hand" && (
          <button type="button" className="act-config" disabled={learning} onClick={learn} title="2.5초 동안 원하는 방식으로 물체를 움직이세요">
            <ActionIcon name="tune" />{learning ? "움직여 보세요…" : "보여 주며 설정"}
          </button>
        )}
        <button type="button" className="danger" onClick={onDelete}><ActionIcon name="trash" />삭제</button>
      </div>
      {open && (
        <div className="map-detail small">
          <label>방식 <select value={t.mode} onChange={(e) => tr({ mode: e.target.value as "absolute" })}>
            <option value="absolute">위치</option><option value="velocity">변화 속도</option></select></label>
          <label>범위 <NumIn v={t.range[0]} on={(v) => v < t.range[1] && tr({ range: [v, t.range[1]] })} />
            ~ <NumIn v={t.range[1]} on={(v) => v > t.range[0] && tr({ range: [t.range[0], v] })} /></label>
          <label><input type="checkbox" checked={t.invert} onChange={(e) => tr({ invert: e.target.checked })} /> 반전</label>
          <label>데드존 {t.deadzone.toFixed(2)} <input type="range" min={0} max={0.5} step={0.01} value={t.deadzone}
            onChange={(e) => tr({ deadzone: Number(e.target.value) })} /></label>
          <label>곡선 <select value={t.curve} onChange={(e) => tr({ curve: e.target.value as "expo" })}>
            <option value="linear">직선</option><option value="expo">expo (가운데 둔하게)</option></select></label>
          {kind === "digital" ? (
            <label>누름/뗌 <NumIn v={t.on} on={(v) => v >= t.off && v <= 1 && tr({ on: v })} />
              / <NumIn v={t.off} on={(v) => v <= t.on && v >= 0 && tr({ off: v })} /></label>
          ) : (
            <label>부드럽게(ms) <NumIn v={t.smoothing_ms} on={(v) => v >= 0 && v <= 1000 && tr({ smoothing_ms: v })} /></label>
          )}
          <label>놓쳤을 때 <select value={t.on_lost} onChange={(e) => tr({ on_lost: e.target.value as "hold" })}>
            <option value="center">서서히 중립</option><option value="hold">마지막 값 유지</option>
            <option value="release">즉시 중립</option></select></label>
        </div>
      )}
    </div>
  );
}

function NumIn({ v, on }: { v: number; on: (v: number) => unknown }) {
  const [s, setS] = useState(String(v));
  useEffect(() => setS(String(v)), [v]);
  return <input className="num" inputMode="decimal" value={s} aria-label="숫자"
    onChange={(e) => { setS(e.target.value); const n = Number(e.target.value); if (e.target.value !== "" && Number.isFinite(n)) on(n); }} />;
}

function KeyInput({ value, onChange }: { value: string; onChange: (k: string) => void }) {
  const [s, setS] = useState(value);
  const ok = KEY_RE.test(s.toLowerCase());
  return <input aria-label="키" aria-invalid={!ok} className={`num ${ok ? "" : "bad"}`} value={s}
    onChange={(e) => { setS(e.target.value); if (KEY_RE.test(e.target.value.toLowerCase())) onChange(e.target.value.toLowerCase()); }} />;
}
