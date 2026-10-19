import { MappingRow, AddMappingForm } from "./MappingEditor";
import { objectRef } from "../objectRefs";
import { ActionIcon } from "./ActionIcon";
import { Panel } from "./Panel";
import { useEffect, useState } from "react";
import {
  deleteProfile, listProfiles, loadProfile, putOutputMode, saveProfile,
} from "../api";
import {
  preset,
} from "../mapping";
import {
  type Mapping, type ProfileSummary,
} from "../protocol";
import { useApp } from "../store";
import { GamepadView, usePad } from "./GamepadView";
import { VirtualIoView } from "./VirtualIoView";
import { t as L } from "../i18n";
import { sv } from "../serverText";
import { gameFns, GAME_LABEL, GAME_PRESETS, type GameId } from "../gameFunctions";
import { useGameMappingView, buildGameMapping, isDjMapping } from "../gameMapping";
import { PATCH_FNS } from "../patch";
import { PatchBay } from "./PatchBay";
import { TouchSensitivity } from "./TouchSensitivity";
import { useMappingDraft, useDraftStore } from "../mappingDraft";

/** 매핑 편집기: 편집하면 0.3초 뒤 자동 적용. 출력은 '내보내기' 를 켜야 가상 컨트롤러로 나간다. */
const mappingInfo = () => L(<>물체 축(좌우·깊이·기울기 등), 펜 접촉, 손 제스처를 게임패드 축·버튼·키·마우스에 연결합니다. <b>보기만</b>에서도 앱 안 게임은 계산된 연결로 작동합니다. 실제 출력은 출력 설정에서 따로 켭니다.</>,
  <>Connects object axes (X, depth, tilt…), pen contact and hand gestures to gamepad axes, buttons, keys and mouse. In <b>View only</b>, in-app games still use computed mappings. Enable real output separately in Output.</>);

export function MappingPanel() {
  const gameView = useGameMappingView(s => s.game);
  const djActive = useGameMappingView(s => s.dj);
  const info = useApp((s) => s.mappingInfo);
  const setInfo = useApp((s) => s.setMappingInfo);
  const objects = useApp((s) => s.objects);
  const conn = useApp((s) => s.conn);
  const { draft, edit, err: draftErr } = useMappingDraft();
  const [saved, setSaved] = useState<ProfileSummary[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const pad = usePad();
  const names = objects.map(objectRef);

  const advanced = useApp((s) => s.devMode);
  const fail = (e: unknown) => setErr(String(e instanceof Error ? e.message : e).replace(/^\d+ /, ""));
  useEffect(() => {
    if (conn !== "open") return;
    listProfiles().then(setSaved, fail);
  }, [conn]);
  if (!draft || !info) return <Panel title={L("매핑", "Mapping")} label="매핑" className="demo" info={mappingInfo()}><p className="muted">{L("불러오는 중…", "Loading…")}</p></Panel>;

  const setM = (m: Mapping) => { const p = useDraftStore.getState().draft; if (p) edit({ ...p, mappings: p.mappings.map(x => x.id === m.id ? m : x) }); };
  const obj0 = names[0] ?? L("물체 1", "Object 1");
  const refresh = () => listProfiles().then(setSaved, fail);

  return (
    <Panel title={L("매핑", "Mapping")} label="매핑" className="demo" tour="mapping" info={mappingInfo()}>
      <div className="row">
        <input aria-label={L("프로필 이름", "Profile name")} value={draft.name} maxLength={40}
          onChange={(e) => edit({ ...draft, name: e.target.value || L("기본", "Default") })} />
        <button type="button" className="act-config" onClick={() => saveProfile(draft).then(refresh, fail)}><ActionIcon name="save" />{L("저장", "Save")}</button>
        <select aria-label={L("저장된 프로필", "Saved profiles")} value="" onChange={(e) => e.target.value && loadProfile(e.target.value).then(edit, fail)}>
          <option value="">{L("불러오기…", "Load…")}</option>
          {saved.map((p) => <option key={p.name} value={p.name}>{p.name} ({p.mappings})</option>)}
        </select>
        {advanced && <button type="button" className="danger dev-btn" disabled={!saved.some((p) => p.name === draft.name)}
          onClick={() => deleteProfile(draft.name).then(refresh, fail)}><ActionIcon name="trash" />{L("프로필 삭제", "Delete profile")}</button>}
        <select aria-label={L("예시", "Examples")} value="" onChange={e => {
          if (!e.target.value) return;
          const selected = GAME_PRESETS.find(p => p.id === e.target.value);
          try {
            if (selected) {
              const sources = objects.filter(o => o.kind !== "pen").slice(0, selected.players).map(o => `#${o.id}`);
              if (!sources.length && useApp.getState().handInputEnabled) sources.push("@hand");
              edit(buildGameMapping(draft, selected.game, selected.players, selected.style, sources), true);
              useGameMappingView.getState().setGame(selected.game);
            } else edit(preset(e.target.value as "wasd", obj0));
            setErr(null);
          } catch (e) { fail(e); }
        }}>
          <option value="">{L("예시…", "Examples…")}</option>
          {GAME_PRESETS.map(p => <option key={p.id} value={p.id}>{p.label()}</option>)}
          <option value="joystick">{L("일반 게임패드 스틱 X/Y", "Generic gamepad stick X/Y")}</option>
          <option value="wasd">{L("WASD 키", "WASD keys")}</option>
          <option value="mouse">{L("조이스틱 마우스", "Joystick mouse")}</option>
        </select>
      </div>
      <div className="row" role="radiogroup" aria-label={L("출력", "Output")}>
        {(["observe", "send"] as const).map((m) => (
          <button key={m} type="button" role="radio" aria-checked={info.mode === m} className={`${m === "send" ? "act-real" : "act-safe"} ${info.mode === m ? "active" : ""}`}
            onClick={() => putOutputMode(m).then(setInfo, fail)}>
            <ActionIcon name={m === "observe" ? "virtual" : "play"} />{m === "observe" ? L("보기만", "View only") : L("출력", "Output")}
          </button>
        ))}
        <span className="muted small">{L("출력 패널에서 실제 입력을 켜면 OS에도 적용 · ESC = 긴급 정지", "Turn on real input in Output to reach the OS · ESC = emergency stop")}</span>
      </div>
      {djActive ? <p className="small muted">{L("DJ 셋을 보는 동안에는 게임 잭을 숨깁니다. DJ 연결은 DJ 패널의 잭에서 다뤄요.", "Game jacks are hidden while the DJ Set is open. DJ connections live in the DJ panel's jacks.")}</p> : <>
      <label className="small">{L("게임 잭 보기", "Game jacks")} <select aria-label={L("게임 잭 보기", "Game jacks")} value={gameView} onChange={e => useGameMappingView.getState().setGame(e.target.value as GameId)}>{(Object.keys(GAME_LABEL) as GameId[]).map(g => <option key={g} value={g}>{GAME_LABEL[g]()}</option>)}</select></label>
      <p className="small muted">{L("모든 게임은 가상 게임패드의 스틱·트리거로 조작합니다. 예시는 패드 축 연결을 교체하며 키·마우스·DJ 연결은 유지합니다.", "All games use the virtual gamepad sticks and triggers. Presets replace pad axes and keep key, mouse and DJ mappings.")}</p>
      </>}
      <PatchBay fns={[...(djActive ? [] : gameFns(gameView)), ...PATCH_FNS]} allowCustom draft={draft} edit={edit} tour="patchbay" hide={isDjMapping} />
      {draft.mappings.some((m) => m.input.source === "touch") && <div className="row"><TouchSensitivity kind="object" /></div>}
      <div className="mapping-grid">
        <div>
          {/* DJ 셋의 연결(데모 조작 dj.*)은 DJ 패널에서만 다룬다: 게임 매핑과 겹치지 않으므로 여기 목록에는 보이지 않는다 */}
          {draft.mappings.map((m, i) => isDjMapping(m) ? null : (
            <MappingRow key={m.id} m={m} names={names} onChange={setM}
              onDelete={() => edit({ ...draft, mappings: draft.mappings.filter((_, k) => k !== i) })} onError={fail} />
          ))}
          <AddMappingForm draft={draft} edit={edit} />
        </div>
        <div className="virtual-io">
          <GamepadView pad={pad} />
          <VirtualIoView />
        </div>
      </div>
      {info.warnings.map((w) => <p key={w} className="warn small">{sv(w)}</p>)}
      {(err || draftErr) && <p className="error small" role="alert">{err ?? draftErr}</p>}
    </Panel>
  );
}

