import { useEffect, useRef, useState } from "react";
import { connection } from "../connection";
import { DEFAULT_DJ, DjEngine, type DjControls } from "../djAudio";
import { useMappingDraft } from "../mappingDraft";
import { cables, connect, registerFns, type PatchFn } from "../patch";
import { objectRef } from "../objectRefs";
import { useApp } from "../store";
import type { FrameState, ObjectInfo, Profile } from "../protocol";
import { t } from "../i18n";
import { ActionIcon } from "./ActionIcon";
import { padFromState, ZERO, type PadState } from "./GamepadView";
import { Panel } from "./Panel";
import { PatchBay } from "./PatchBay";

const TOUCH = { range: [0, 1] as [number, number], deadzone: 0 };
const ctl = (name: string, kind: "bipolar" | "unipolar" | "digital") => ({ target: "control" as const, name, kind });
/** DJ 조작 요소마다 잭 하나. 출력은 '데모 조작'(dj.*)이라 게임·OS 와 겹치지 않는다.
 * 한 물체에 케이블을 여러 개 이어 축마다 다른 요소를 움직일 수 있다 (예: 좌우 = 크로스페이더, 위아래 = 볼륨). 케이블을 눌러 입력 축을 바꾼다. */
export const DJ_FNS: PatchFn[] = [
  { id: "dj-play-a", label: () => t("덱 A 재생/정지", "Deck A play"), hint: () => t("손으로 터치", "Touch with a hand"), output: ctl("dj.playA", "digital"), axis: "y", input: "touch", transform: TOUCH },
  { id: "dj-play-b", label: () => t("덱 B 재생/정지", "Deck B play"), hint: () => t("손으로 터치", "Touch with a hand"), output: ctl("dj.playB", "digital"), axis: "y", input: "touch", transform: TOUCH },
  { id: "dj-vol-a", label: () => t("볼륨 A", "Volume A"), hint: () => t("위로 들면 크게", "Lift = louder"), output: ctl("dj.volA", "unipolar"), axis: "y", transform: { range: [-0.15, 0.15], invert: true, deadzone: 0 } },
  { id: "dj-vol-b", label: () => t("볼륨 B", "Volume B"), hint: () => t("위로 들면 크게", "Lift = louder"), output: ctl("dj.volB", "unipolar"), axis: "y", transform: { range: [-0.15, 0.15], invert: true, deadzone: 0 } },
  { id: "dj-cross", label: () => t("크로스페이더", "Crossfader"), hint: () => t("좌우로", "Left/right"), output: ctl("dj.cross", "bipolar"), axis: "x", transform: { range: [-0.2, 0.2], deadzone: 0.04 } },
  { id: "dj-filter", label: () => t("필터", "Filter"), hint: () => t("기울이기", "Tilt"), output: ctl("dj.filter", "bipolar"), axis: "angle", transform: { range: [-40, 40], deadzone: 0.06 } },
  { id: "dj-tempo", label: () => t("템포", "Tempo"), hint: () => t("가까이·멀리", "Near/far"), output: ctl("dj.tempo", "bipolar"), axis: "depth", transform: { range: [-0.4, 0.4], deadzone: 0.05 } },
  { id: "dj-scratch", label: () => t("스크래치", "Scratch"), hint: () => t("손으로 터치", "Touch with a hand"), output: ctl("dj.scratch", "digital"), axis: "y", input: "touch", transform: TOUCH },
  { id: "dj-echo", label: () => t("에코 켜기/끄기", "Echo on/off"), hint: () => t("손으로 터치", "Touch with a hand"), output: ctl("dj.echo", "digital"), axis: "y", input: "touch", transform: TOUCH },
  { id: "dj-horn", label: () => t("클랩", "Clap"), hint: () => t("손으로 터치", "Touch with a hand"), output: ctl("dj.horn", "digital"), axis: "y", input: "touch", transform: TOUCH },
];
registerFns("dj", DJ_FNS);

/** Explicit presets only; keep non-DJ mappings and legacy output names. */
export function djPreset(profile: Profile, objects: ObjectInfo[], mirror = false): Profile {
  const available = objects.filter(o => o.kind !== "pen").sort((a, b) => {
    const x = (o: ObjectInfo) => o.box ? (o.box[0] + o.box[2]) / 2 : o.id;
    return (mirror ? -1 : 1) * (x(a) - x(b));
  });
  if (!available.length) throw new Error(t("일반 물체를 먼저 등록하세요.", "Register an object first."));
  const a = objectRef(available[0]!), b = objectRef(available[1] ?? available[0]!);
  let next = { ...profile, mappings: profile.mappings.filter(m => m.output.target !== "control" || !m.output.name.startsWith("dj.")) };
  const add = (ref: string, fn: string, axis?: "x" | "y" | "depth" | "angle", lift = false) => {
    next = connect(next, ref, fn);
    if (axis) {
      const m = next.mappings[next.mappings.length - 1]!;
      m.input = { source: "object", object: ref, axis };
      m.transform = { ...m.transform, range: lift ? [-.15, 0] : axis === "angle" ? [-40, 40] : axis === "depth" ? [-.35, .35] : [-.25, .25], invert: lift, on_lost: "release", lost_ms: 0 };
    }
  };
  if (available.length >= 2) { add(a, "dj-play-a"); add(b, "dj-play-b"); }   // 물체 1개 예시에는 터치 배정을 넣지 않는다 (재생은 화면 버튼)
  add(a, "dj-vol-a", "depth"); add(b, "dj-vol-b", "depth");
  add(a, "dj-cross", "x"); add(b, "dj-filter", "angle"); add(a, "dj-horn", "y", true);
  if (available.length >= 2) { add(a, "dj-tempo", "angle"); add(b, "dj-echo", "y", true); }
  if (next.mappings.length > 64) throw new Error(t("매핑이 너무 많습니다. 불필요한 연결을 먼저 지워 주세요.", "Too many mappings. Remove unused connections first."));
  return next;
}

/** DJ 셋: 턴테이블 두 대 + 믹서. 화면에서 직접 누르거나, 위 패치 베이에서 물체를 기능 잭에 이어 물체로 조작한다. */
export function DjDemo() {
  const { draft, edit, err } = useMappingDraft();
  const objects = useApp(s => s.objects), conn = useApp(s => s.conn);
  const count = objects.filter(o => o.kind !== "pen").length;
  const [presetError, setPresetError] = useState("");
  const engine = useRef<DjEngine | null>(null);
  const [on, setOn] = useState(false);
  const [c, setC] = useState<DjControls>(DEFAULT_DJ);
  const cRef = useRef(c); cRef.current = c;
  const pad = useRef<PadState>(ZERO);
  const prev = useRef<PadState>(ZERO);
  const [beat, setBeat] = useState(0);
  const [flash, setFlash] = useState<string | null>(null);
  const wired = new Set(draft ? cables(draft).map((w) => w.fn) : []);
  const wiredRef = useRef(wired); wiredRef.current = wired;

  useEffect(() => connection.onMessage((type, data) => { if (type === "state") pad.current = padFromState(data as unknown as FrameState); }), []);
  useEffect(() => () => { engine.current?.stop(); engine.current = null; }, []);
  const ensure = () => {   // 처음 누르는 순간 소리를 켠다 (브라우저는 사용자 조작 뒤에만 소리를 허용)
    if (!engine.current) { engine.current = new DjEngine(); engine.current.set(cRef.current); }
    engine.current.start(); setOn(true);
  };
  const apply = (next: DjControls) => { if ((next.playA && !cRef.current.playA) || (next.playB && !cRef.current.playB)) ensure(); setC(next); cRef.current = next; engine.current?.set(next); };
  const fire = (what: "horn" | "scratch") => {
    ensure();
    if (what === "horn") engine.current?.clap(); else engine.current?.scratch();
    setFlash(what); window.setTimeout(() => setFlash(null), 300);
  };
  // 매핑 값 읽기: 연결된 잭만 물체 값으로, 나머지는 화면 조작 그대로. 버튼은 누르는 순간(올라가는 변화)에만.
  useEffect(() => {
    let raf = 0, last = 0;
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      if (now - last < 50) return;
      last = now;
      const p = pad.current.controls, q = prev.current.controls, w = wiredRef.current;
      let next = cRef.current;
      const edge = (k: string) => (p[k] ?? 0) >= 0.5 && (q[k] ?? 0) < 0.5;
      const analog = (fn: string, k: string, cur: number, map: (v: number) => number) => {
        if (!w.has(fn) || p[k] === undefined) return cur;
        const v = map(p[k]!);
        return Math.abs(v - cur) > 0.01 ? v : cur;
      };
      const upd = { ...next,
        volA: analog("dj-vol-a", "dj.volA", next.volA, (v) => v), volB: analog("dj-vol-b", "dj.volB", next.volB, (v) => v),
        cross: analog("dj-cross", "dj.cross", next.cross, (v) => v), filter: analog("dj-filter", "dj.filter", next.filter, (v) => v),
        tempo: Math.round(analog("dj-tempo", "dj.tempo", next.tempo, (v) => Math.max(90, Math.min(150, DEFAULT_DJ.tempo + 30 * v)))) };
      if (upd.volA !== next.volA || upd.volB !== next.volB || upd.cross !== next.cross || upd.filter !== next.filter || upd.tempo !== next.tempo) next = upd;
      if (w.has("dj-play-a") && edge("dj.playA")) next = { ...next, playA: !next.playA };
      if (w.has("dj-play-b") && edge("dj.playB")) next = { ...next, playB: !next.playB };
      if (w.has("dj-echo") && edge("dj.echo")) next = { ...next, echo: !next.echo };
      if (w.has("dj-horn") && edge("dj.horn")) fire("horn");
      if (w.has("dj-scratch") && edge("dj.scratch")) fire("scratch");
      prev.current = pad.current;
      if (next !== cRef.current) apply(next);
      if (engine.current && engine.current.beat !== beat) setBeat(engine.current.beat);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [beat]);
  const powerOff = () => { engine.current?.stop(); engine.current = null; setOn(false); apply({ ...cRef.current, playA: false, playB: false }); };

  // 화면(파형)·VU 미터는 React 를 거치지 않고 매 프레임 직접 그린다
  const screen = useRef<HTMLCanvasElement>(null);
  const vu = useRef<Record<"A" | "B", HTMLDivElement | null>>({ A: null, B: null });
  useEffect(() => {
    let raf = 0;
    const buf = new Float32Array(1024);
    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      const e = engine.current;
      for (const k of ["A", "B"] as const) {
        const el = vu.current[k]; if (!el) continue;
        const n = Math.round((e ? e.level(k) : 0) * el.children.length);
        Array.from(el.children).forEach((seg, i) => seg.classList.toggle("on", el.children.length - 1 - i < n));
      }
      const cv = screen.current, g = cv?.getContext("2d");
      if (!cv || !g) return;
      const W = cv.width, H = cv.height;
      g.fillStyle = "#06080b"; g.fillRect(0, 0, W, H);
      g.strokeStyle = "#ffffff0d"; g.lineWidth = 1;
      for (let x = 0; x < W; x += 24) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
      ([["A", "#21e6ff", 0], ["B", "#ff3dd8", H / 2]] as const).forEach(([d, col, y0]) => {
        const playing = d === "A" ? cRef.current.playA : cRef.current.playB;
        g.fillStyle = col + "22"; g.fillRect(0, y0 + 2, 4, H / 2 - 4);
        g.font = "bold 10px ui-monospace, monospace"; g.fillStyle = col; g.fillText(`DECK ${d}`, 10, y0 + 13);
        g.strokeStyle = col; g.lineWidth = 2; g.shadowColor = col; g.shadowBlur = playing ? 10 : 0;
        g.beginPath();
        if (e && playing) e.wave(d, buf);
        for (let x = 0; x < W; x++) {
          const v = e && playing ? buf[Math.floor(x / W * buf.length)]! : Math.sin(x / 9 + now / 600) * 0.01;
          const y = y0 + H / 4 + v * H / 4 * 1.6;
          if (x) g.lineTo(x, y); else g.moveTo(x, y);
        }
        g.stroke(); g.shadowBlur = 0;
      });
      g.fillStyle = "#ffffff18"; g.fillRect(0, H / 2, W, 1);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, []);
  const vuRef = (k: "A" | "B") => (el: HTMLDivElement | null) => { vu.current[k] = el; };

  return (
    <Panel title={t("DJ 셋", "DJ Set")} label="DJ 데모" className="demo" detail={t("물체를 잭에 이어 믹싱하기", "Patch objects to the jacks and mix")}
      info={t(<>음원 없이 브라우저에서 만든 비트(덱 A)와 신스(덱 B)를 섞습니다. 화면의 버튼·노브·페이더를 직접 써도 되고(노브는 위아래로 끌기, 두 번 클릭 = 가운데), 위 <b>DJ 패치 베이</b>에서 물체 카드의 잭을 이으면 물체로 조작합니다: 좌우 = 크로스페이더, 기울기 = 필터, <b>손으로 물체를 터치</b> = 재생·에코·클랩·스크래치.</>,
        <>Mixes a browser-made beat (deck A) and synth (deck B). Use the on-screen buttons, knobs (drag up/down, double-click = center) and faders, or patch object jacks in the <b>DJ patch bay</b> above: sideways = crossfader, tilt = filter, <b>touch the object with a finger</b> = play, echo, clap, scratch.</>)}>
      <div className="game-mapping" data-tour="automap">
        <button type="button" className="act-config" disabled={!draft || count === 0 || conn !== "open"} onClick={() => {
          try { edit(djPreset(draft!, objects, useApp.getState().inputMirror), true); setPresetError(""); }
          catch (e) { setPresetError(String(e instanceof Error ? e.message : e)); }
        }}>{count >= 2 ? t("2개 물체 예시 · 자동 매핑", "2-object example · Auto-map") : t("1개 물체 예시 · 자동 매핑", "1-object example · Auto-map")}</button>
        <p className="small muted">{count === 0 ? t("일반 물체를 등록하면 예시를 연결할 수 있습니다.", "Register an object to use the example.") : count >= 2 ? t("선택 순서: 영상 왼쪽부터 덱 A/B. 각 물체 터치 = 해당 덱 재생, 앞뒤 = 볼륨. A 좌우 = 믹스, A 기울기 = 템포, A 들기 = 클랩. B 기울기 = 필터, B 들기 = 에코. 3개 이상이면 앞의 2개를 씁니다.", "Left-to-right controllers are decks A/B. Touch each to play its deck, near/far for volume. A: sideways mix, tilt tempo, lift clap. B: tilt filter, lift echo. With 3+ objects, the first two are used.") : t("좌우 = 믹스, 앞뒤 = 두 덱 볼륨, 기울기 = 필터, 들기 = 클랩. 재생은 화면의 재생 버튼으로 하세요(터치 배정 없음). DJ 연결만 교체하며 다른 매핑은 유지합니다.", "Sideways mixes, near/far controls both volumes, tilt filters, lift triggers clap. Use the on-screen play buttons (no touch mapping). Only DJ connections are replaced.")}</p>
      </div>
      {(err || presetError) && <p className="error small" role="alert">{presetError || err}</p>}
      {draft && <PatchBay fns={DJ_FNS} title={t("DJ 패치 베이", "DJ patch bay")} draft={draft} edit={edit} />}
      <div className="djc">
        <div className="djc-top">
          <span className="djc-brand">ANY<b>CONTROL</b> <i>DDJ-AC2</i></span>
          <div className="djc-lcd" aria-live="off">
            <span>{c.tempo.toFixed(1)}<small>BPM</small></span>
            <span className="djc-beats">{[0, 1, 2, 3].map((i) => <i key={i} className={on && (c.playA || c.playB) && beat % 4 === i ? "lit" : ""} />)}</span>
            <span className={c.echo ? "fx on" : "fx"}>ECHO</span>
            <span className={Math.abs(c.filter) > 0.06 ? "fx on" : "fx"}>{c.filter < -0.06 ? "LPF" : c.filter > 0.06 ? "HPF" : "FLT"}</span>
          </div>
          <button type="button" className={`djc-power ${on ? "on" : ""}`} onClick={on ? powerOff : ensure} aria-pressed={on}>
            <ActionIcon name="power" />{on ? t("전원 켜짐", "Power on") : t("전원", "Power")}</button>
        </div>
        <canvas ref={screen} className="djc-screen" width={900} height={120} role="img" aria-label={t("두 덱의 실시간 파형", "Live waveforms of both decks")} />
        <div className="djc-body">
          <Deck name="A" accent="#21e6ff" label={t("하우스 비트", "HOUSE BEAT")} playing={on && c.playA} scratch={flash === "scratch"} wired={wired.has("dj-play-a")}
            onPlay={() => apply({ ...cRef.current, playA: !cRef.current.playA })} onScratch={() => fire("scratch")} />
          <div className="djc-mixer">
            <div className="djc-channels">
              <Channel deck="A" accent="#21e6ff" vol={c.volA} vuRef={vuRef("A")} wired={wired.has("dj-vol-a")} onVol={(v) => apply({ ...cRef.current, volA: v })} />
              <div className="djc-center">
                <Knob label="FILTER" value={c.filter} min={-1} max={1} center onChange={(v) => apply({ ...cRef.current, filter: v })} accent="#ffb000" big wired={wired.has("dj-filter")} />
                <Knob label="TEMPO" value={c.tempo} min={90} max={150} defaultValue={120} onChange={(v) => apply({ ...cRef.current, tempo: Math.round(v) })} accent="#c9d2df" wired={wired.has("dj-tempo")} />
              </div>
              <Channel deck="B" accent="#ff3dd8" vol={c.volB} vuRef={vuRef("B")} wired={wired.has("dj-vol-b")} onVol={(v) => apply({ ...cRef.current, volB: v })} />
            </div>
            <div className="djc-pads three">
              <Pad color="#21e6ff" label="SCRATCH" lit={flash === "scratch"} wired={wired.has("dj-scratch")} onPress={() => fire("scratch")} />
              <Pad color="#a66bff" label="ECHO" lit={c.echo} wired={wired.has("dj-echo")} onPress={() => apply({ ...cRef.current, echo: !cRef.current.echo })} />
              <Pad color="#ff8a00" label="CLAP" lit={flash === "horn"} wired={wired.has("dj-horn")} onPress={() => fire("horn")} />
            </div>
            <div className="djc-xfader">
              <span>A</span>
              <input type="range" min={-1} max={1} step={0.01} value={c.cross} aria-label={t("크로스페이더", "Crossfader")}
                onChange={(e) => apply({ ...cRef.current, cross: Number(e.target.value) })} onDoubleClick={() => apply({ ...cRef.current, cross: 0 })} />
              <span>B</span>
              {wired.has("dj-cross") && <em className="djc-link">⚡</em>}
            </div>
          </div>
          <Deck name="B" accent="#ff3dd8" label={t("멜로딕 하우스", "MELODIC HOUSE")} playing={on && c.playB} scratch={false} wired={wired.has("dj-play-b")}
            onPlay={() => apply({ ...cRef.current, playB: !cRef.current.playB })} onScratch={() => fire("scratch")} />
        </div>
      </div>
    </Panel>
  );
}

/** 조그 휠 + 덱 화면 + CUE/PLAY. 돌아가는 판, 진행을 따라 도는 LED 링. 휠을 누르면 스크래치. */
function Deck({ name, accent, label, playing, scratch, wired, onPlay, onScratch }: {
  name: string; accent: string; label: string; playing: boolean; scratch: boolean; wired: boolean; onPlay: () => void; onScratch: () => void;
}) {
  const leds = 36;
  return (
    <div className={`djc-deck ${playing ? "playing" : ""}`} style={{ "--acc": accent } as React.CSSProperties}>
      <div className="djc-deck-lcd"><b>{name}</b><span>{label}</span><em>{playing ? "▶ PLAY" : "■ STOP"}</em></div>
      <button type="button" className={`djc-jog ${scratch ? "scratch" : ""}`} onClick={onScratch} aria-label={t(`덱 ${name} 조그 휠 (누르면 스크래치)`, `Deck ${name} jog wheel (press to scratch)`)}>
        <svg viewBox="0 0 200 200" aria-hidden="true">
          <defs>
            <radialGradient id={`vinyl${name}`} cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#1b1b1f" /><stop offset="60%" stopColor="#0c0c0f" /><stop offset="100%" stopColor="#1d1d22" />
            </radialGradient>
            <linearGradient id={`shine${name}`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#ffffff" stopOpacity="0" /><stop offset="48%" stopColor="#ffffff" stopOpacity="0.09" />
              <stop offset="52%" stopColor="#ffffff" stopOpacity="0.09" /><stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
            </linearGradient>
          </defs>
          <circle cx="100" cy="100" r="98" fill="#16181d" stroke="#2c3038" strokeWidth="2" />
          <g className="djc-ring">
            {Array.from({ length: leds }, (_, i) => {
              const a = (i / leds) * Math.PI * 2;
              return <rect key={i} x="98" y="4" width="4" height="9" rx="1.5" transform={`rotate(${(a * 180) / Math.PI} 100 100)`}
                fill={accent} opacity={0.15 + 0.85 * ((leds - i) / leds) ** 3} />;
            })}
          </g>
          <g className="djc-platter">
            <circle cx="100" cy="100" r="82" fill={`url(#vinyl${name})`} />
            {[76, 70, 64, 58, 52, 46].map((r) => <circle key={r} cx="100" cy="100" r={r} fill="none" stroke="#ffffff" strokeOpacity="0.05" />)}
            <circle cx="100" cy="100" r="30" fill={accent} />
            <text x="100" y="96" textAnchor="middle" className="djc-label-t">ANYCONTROL</text>
            <text x="100" y="110" textAnchor="middle" className="djc-label-s">{label} · {name}</text>
            <rect x="97" y="20" width="6" height="16" rx="2" fill="#f2f2f2" />
            <circle cx="100" cy="100" r="3.5" fill="#0c0c0f" />
          </g>
          <circle cx="100" cy="100" r="82" fill={`url(#shine${name})`} pointerEvents="none" />
        </svg>
      </button>
      <div className="djc-transport">
        <button type="button" className={`djc-round play ${playing ? "on" : ""}`} onClick={onPlay} aria-pressed={playing}
          aria-label={t(`덱 ${name} 재생/일시정지`, `Deck ${name} play/pause`)}>{playing ? "❙❙" : "▶"}</button>
        <span className="djc-hint">{playing ? t("재생 중", "Playing") : t("눌러서 재생", "Press to play")}</span>
        {wired && <em className="djc-link" title={t("물체에 연결됨", "Linked to an object")}>⚡</em>}
      </div>
    </div>
  );
}

/** 채널 스트립: VU 미터 + 세로 볼륨 페이더 */
function Channel({ deck, accent, vol, vuRef, onVol, wired }: {
  deck: string; accent: string; vol: number; vuRef: (el: HTMLDivElement | null) => void; onVol: (v: number) => void; wired: boolean;
}) {
  return (
    <div className="djc-channel" style={{ "--acc": accent } as React.CSSProperties}>
      <span className="djc-knob-label">VOLUME{wired && <em className="djc-link">⚡</em>}</span>
      <div className="djc-fader-wrap">
        <div className="djc-vu" ref={vuRef} aria-hidden="true">{Array.from({ length: 14 }, (_, i) => <i key={i} />)}</div>
        <input className="djc-fader" type="range" min={0} max={1} step={0.01} value={vol} aria-label={t(`채널 ${deck} 볼륨`, `Channel ${deck} volume`)}
          onChange={(e) => onVol(Number(e.target.value))} />
      </div>
      <b className="djc-ch">CH {deck}</b>
    </div>
  );
}

/** 회전 노브: 위아래로 끌거나 휠·방향키로 돌린다. 두 번 클릭하면 기본값. */
function Knob({ label, value, min, max, onChange, accent, center = false, big = false, defaultValue, wired = false }: {
  label: string; value: number; min: number; max: number; onChange: (v: number) => void; accent: string; center?: boolean; big?: boolean; defaultValue?: number; wired?: boolean;
}) {
  const frac = (value - min) / (max - min);
  const angle = -135 + frac * 270;
  const set = (v: number) => onChange(Math.max(min, Math.min(max, v)));
  const r = 22, arc = (a0: number, a1: number) => {
    const p = (a: number) => [30 + r * Math.sin((a * Math.PI) / 180), 30 - r * Math.cos((a * Math.PI) / 180)];
    const [x0, y0] = p(a0), [x1, y1] = p(a1);
    return `M${x0},${y0} A${r},${r} 0 ${Math.abs(a1 - a0) > 180 ? 1 : 0} ${a1 > a0 ? 1 : 0} ${x1},${y1}`;
  };
  const from = center ? 0 : -135;
  return (
    <div className={`djc-knob ${big ? "big" : ""}`}>
      <div role="slider" tabIndex={0} aria-label={label} aria-valuemin={min} aria-valuemax={max} aria-valuenow={Number(value.toFixed(2))}
        onPointerDown={(e) => {
          const y0 = e.clientY, v0 = value;
          (e.target as Element).setPointerCapture?.(e.pointerId);
          const move = (ev: PointerEvent) => set(v0 + ((y0 - ev.clientY) / 160) * (max - min));
          const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
          window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
        }}
        onWheel={(e) => set(value - Math.sign(e.deltaY) * (max - min) / 40)}
        onDoubleClick={() => set(defaultValue ?? (center ? (min + max) / 2 : min))}
        onKeyDown={(e) => { if (e.key === "ArrowUp" || e.key === "ArrowRight") set(value + (max - min) / 40); if (e.key === "ArrowDown" || e.key === "ArrowLeft") set(value - (max - min) / 40); }}>
        <svg viewBox="0 0 60 60" aria-hidden="true">
          <path d={arc(-135, 135)} className="djc-knob-track" />
          {Math.abs(angle - from) > 1 && <path d={angle > from ? arc(from, angle) : arc(angle, from)} stroke={accent} className="djc-knob-val" />}
          <circle cx="30" cy="30" r="15" className="djc-knob-cap" />
          <line x1="30" y1="30" x2="30" y2="17" transform={`rotate(${angle} 30 30)`} className="djc-knob-tick" />
        </svg>
      </div>
      <span>{label}{wired && <em className="djc-link">⚡</em>}</span>
    </div>
  );
}

/** 고무 패드: 누르면 색이 켜진다 */
function Pad({ color, label, lit, onPress, wired = false }: { color: string; label: string; lit: boolean; onPress: () => void; wired?: boolean }) {
  return (
    <button type="button" className={`djc-pad ${lit ? "lit" : ""}`} style={{ "--pad": color } as React.CSSProperties} onPointerDown={onPress}
      onKeyDown={(e) => { if (e.key === "Enter") onPress(); }}>
      {label}{wired && <em className="djc-link">⚡</em>}
    </button>
  );
}
