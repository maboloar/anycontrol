import { BetaBadge } from "./BetaBadge";
import { ActionIcon } from "./ActionIcon";
import { useEffect, useRef, useState } from "react";
import { getMouse, putMouse, putTracking, resetDepthReference, stopAll } from "../api";
import { Info } from "./Info";
import type { HandBackend, MouseMode, MouseSettings } from "../protocol";
import { useApp } from "../store";
import { Panel } from "./Panel";
import { AutoCalibration, calibrationActive } from './AutoCalibration';
import { labels, t } from "../i18n";

const GESTURE_LABEL: Record<string, string> = labels({
  move: ["이동", "Move"],
  left: ["왼쪽 누름", "Left press"],
  right: ["오른쪽 누름", "Right press"],
  scroll: ["스크롤", "Scroll"],
  none: ["손 없음", "No hand"],
  pen: ["펜 누름", "Pen press"],
  approach: ["클릭 준비", "Getting ready"],
  "object-tap": ["물체 검지 탭", "Index tap on object"],
});

/** 마우스 모드: 끄기 / 맨손 마우스 / 물체 마우스. 손 추적은 필요한 모드에서만 켜진다. */
export function MousePanel() {
  const info = useApp((s) => s.mouseInfo);
  const setInfo = useApp((s) => s.setMouseInfo);
  const objects = useApp((s) => s.objects);
  const live = useApp((s) => s.live.mouse);
  const conn = useApp((s) => s.conn);
  const handInputEnabled = useApp(s => s.handInputEnabled);
  const calibrating = useApp(s => calibrationActive(s.autoCalibration));
  const deskView = useApp((s) => Boolean(s.telemetry?.source?.desk_view));
  const [err, setErr] = useState<string | null>(null);
  const settingsRef = useRef<MouseSettings | null>(null);
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  const generationRef = useRef(0);

  useEffect(() => { if (info) settingsRef.current = info.settings; }, [info]);

  useEffect(() => {
    const cancel = () => { generationRef.current++; settingsRef.current = null; };
    window.addEventListener("anycontrol-stop", cancel);
    return () => { cancel(); window.removeEventListener("anycontrol-stop", cancel); };
  }, []);

  useEffect(() => {
    let alive = true;
    if (conn === "open") getMouse().then((m) => { if (alive) { settingsRef.current = m.settings; setInfo(m); } },
      (e: unknown) => { if (alive) setErr(String(e)); });
    return () => { alive = false; };
  }, [conn, setInfo]);

  const apply = (patch: Partial<MouseSettings>) => {
    const current = settingsRef.current ?? info?.settings;
    if (!current || !info || calibrating) return;
    const next = { ...current, ...patch, ...(patch.mode === "hand" ? { hand_control: "air" as const, hand_click_style: "pinch" as const } : {}) };
    const generation = generationRef.current;
    settingsRef.current = next;
    setInfo({ ...info, settings: next });
    queueRef.current = queueRef.current.then(async () => {
      if (generation !== generationRef.current) return;
      const updated = await putMouse(next);
      if (generation !== generationRef.current) {
        setInfo(await stopAll());
        return;
      }
      if (settingsRef.current === next) setInfo(updated);
      setErr(null);
    }).catch(async (e: unknown) => {
      setErr(String(e instanceof Error ? e.message : e).replace(/^\d+ /, ""));
      try {
        const actual = await getMouse();
        settingsRef.current = actual.settings;
        setInfo(actual);
      } catch { /* 연결 오류는 위에 표시 */ }
    });
  };

  const s = info?.settings;
  const mode = s?.mode ?? "off";
  const advanced = useApp((st) => st.devMode);
  // 한 손 하이브리드는 삭제했다. 예전에 저장된 설정이 켜져 있으면 끈다.
  useEffect(() => { if (s?.object_hybrid) apply({ object_hybrid: false }); }, [s?.object_hybrid]);
  const [engineBusy, setEngineBusy] = useState(false);
  const setEngine = async (b: HandBackend) => {
    setEngineBusy(true);
    try {
      await putTracking({ hand_backend: b });
      setInfo(await getMouse());
      setErr(null);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e).replace(/^\d+ /, ""));
    } finally {
      setEngineBusy(false);
    }
  };
  const depthMode = mode === "hand" && s?.hand_control === "depth" || mode === "object" && s?.coordinate_mode === "depth";
  const setMode = (m: MouseMode) => {
    if (m === "object") {
      const id = s?.object_id && objects.some(o => o.id === s.object_id) ? s.object_id : (objects[0]?.id ?? null);
      apply({ mode: "object", object_id: id, object_hybrid: false });
    } else apply({ mode: m, object_hybrid: false });
  };

  return (
    <Panel title={t("마우스", "Mouse")} label="마우스" tour="mouse" info={t(<>맨손이나 등록한 물체를 커서로 씁니다. <b>끄기</b>는 마우스 입력을 멈춥니다. 물체 터치·맨손 잭·그리기는 각각 설정을 따릅니다.
      <b> ESC</b>(어디서든) 또는 [긴급 정지]로 모든 출력과 눌린 버튼을 즉시 놓습니다.</>,
      <>Use your bare hand or a registered object as the cursor. <b>Off</b> stops mouse input; object touch, hand jacks and drawing have independent settings. <b>ESC</b> (anywhere) or [Emergency stop] releases all output and held buttons.</>)}>
      <div className="row" role="radiogroup" aria-label={t("마우스 모드", "Mouse mode")}>
        {(
          [
            ["off", t("끄기", "Off")],
            ["hand", t("맨손 마우스", "Hand mouse")],
            ["object", t("물체 마우스", "Object mouse")],
          ] as [MouseMode, string][]
        ).map(([m, label]) => (
          <button key={m} type="button" role="radio" aria-checked={mode === m} className={`${m === "off" ? "act-safe" : "act-output"} ${mode === m ? "active" : ""}`}
            disabled={calibrating || !info || (m === "hand" && (!info.hands_available || !handInputEnabled)) || (m === "object" && !objects.length)}
            onClick={() => setMode(m)}>
            <ActionIcon name={m === "off" ? "stop" : "play"} />{label}
          </button>
        ))}
        <button type="button" className="act-stop" onClick={() => stopAll().then(setInfo)} title={t("ESC 키로도 멈춥니다", "ESC also stops")}>
          <ActionIcon name="stop" />{t("긴급 정지 (ESC)", "Emergency stop (ESC)")}
        </button>
      </div>

      {info && !info.hands_available && (
        <p className="warn small">{t("손 인식 모델이 없어 맨손 마우스를 쓸 수 없습니다.", "No hand model is available, so the hand mouse is unavailable.")}</p>
      )}
      {mode === 'off' && !objects.length && <p className="small muted">{t("물체 마우스는 카메라 영상에서 물체를 먼저 드래그해 등록하면 켤 수 있습니다.", "Register an object by dragging it in the camera video to enable the object mouse.")}</p>}
      {advanced && info?.hands_available && (info.hand_backends?.length ?? 0) > 0 && <div className="field">
        <label htmlFor="hand-backend" className="with-info">{t("손 인식 엔진", "Hand engine")}
          <Info wide>{t(<><b>Apple Vision</b>(기본): 물체를 쥔 손도 잘 찾고 빠릅니다 (프레임당 약 9ms). 엄지가 가려지면 위치를 추측해
            쥔 채로 왼쪽 누름으로 오인할 수 있습니다. <b>MediaPipe</b>: 펼친 손에 안정적이지만 쥔 손을 자주 놓칩니다.
            오작동이 잦으면 바꿔 보세요. 영상의 손 뼈대 표시는 어느 엔진이든 같습니다.</>,
            <><b>Apple Vision</b> (default): finds hands even when gripping and is fast (~9ms per frame). A hidden thumb may be guessed and read as a left press. <b>MediaPipe</b>: steady for open hands but often loses gripping ones. Switch if you see misfires. The hand skeleton overlay is the same for both.</>)}</Info></label>
        <select id="hand-backend" value={info.hand_backend ?? "vision"} disabled={engineBusy || calibrating}
          onChange={(e) => void setEngine(e.target.value as HandBackend)}>
          {(info.hand_backends ?? []).includes("vision") && <option value="vision">{t("Apple Vision (기본, macOS에 적합)", "Apple Vision (default, best on macOS)")}</option>}
          {(info.hand_backends ?? []).includes("mediapipe") && <option value="mediapipe">MediaPipe</option>}
        </select>
      </div>}
      {info?.hands_error && <p className="error small">{t("손 인식 오류", "Hand detection error")}: {info.hands_error}</p>}

      {mode !== 'off' && s && <AutoCalibration
        kind={mode === 'hand' ? 'hand' : objects.find(o => o.id === s.object_id)?.kind === 'pen' ? 'pen' : 'object'}
        objectId={mode === 'hand' ? null : s.object_id}
        disabled={mode === 'object' && !objects.some(o => o.id === s.object_id)} prepare={() => queueRef.current} />}

      <fieldset className="manual-settings" disabled={calibrating} aria-label={t("수동 마우스 설정", "Manual mouse settings")}>

      {mode === "object" && s && (
        <div className="field">
          {advanced && <>
          <label htmlFor="object-control" className="with-info">{t("물체 이동 방식", "Object movement")}
            <Info>{t(<><b>좌우 + 깊이</b>: 옆 카메라용 상대 이동 (가까워지면 위). <b>영상 XY</b>: 영상 속 물체 위치가 곧 화면 위치.</>,
              <><b>X + depth</b>: relative movement for a side camera (closer = up). <b>Video XY</b>: the object's position in the video is the screen position.</>)}</Info></label>
          <select id="object-control" value={s.coordinate_mode} onChange={(e) => apply({ coordinate_mode: e.target.value as "depth" | "image" })}>
            <option value="depth">{t("수평 카메라 · 좌우 + 깊이", "Level camera · X + depth")}</option>
            <option value="image">{t("영상 XY · 절대 위치", "Video XY · absolute")}</option>
          </select>
          <label className="check">
            <input type="checkbox" checked={s.anchor_cursor ?? true} onChange={(e) => void apply({ anchor_cursor: e.target.checked })} />
            {t("바닥 기준점으로 커서 움직이기 (떨림 방지)", "Move the cursor by the floor anchor point (steadier)")}
            <Info>{t("영상에 점으로 표시되는 물체의 바닥 아래-가운데 한 점을 광학 흐름으로 따라가 커서를 움직입니다. 손으로 쥐어 분할 영역이 늘었다 줄었다 해도 커서가 거의 흔들리지 않습니다. 앞뒤(크기) 신호도 이 점 주변의 광학 흐름에서 잽니다. 끄면 예전처럼 분할 영역 중심·크기를 씁니다.",
              "Follows one point at the bottom-center of the object (shown as a dot in the video) with optical flow and moves the cursor by it. The cursor barely shakes when the segmentation grows and shrinks as you grip the object. The near/far (size) signal is also measured from the optical flow around that point. Off = the old segmentation center and size.")}</Info>
          </label>
          {s.coordinate_mode === "depth" && (
            <>
              <label htmlFor="depth-source" className="with-info">{t("앞뒤(깊이) 신호", "Depth signal")}
                <Info>{t(<><b>깊이 모델</b>(선택): Depth Anything V2 Small이 책상 면의 먼 쪽~가까운 쪽을 기준으로 물체의 앞뒤 위치를 잽니다. 카메라가 기울어도 영향이 적고, 책상 맨 뒤에서 맨 앞까지 가면 커서가 화면 높이의 여러 배 움직여 훨씬 민감합니다. 약 10Hz로 갱신하고 책상 기준은 천천히 자동으로 따라갑니다. 모델을 못 쓰는 동안은 크기로 돌아갑니다. <b>물체 크기</b>(기본): 가까우면 커 보이는 것을 씁니다 (예전부터 쓰던 방식). 펜에는 적용되지 않습니다.</>,
                  <><b>Depth model</b> (optional): Depth Anything V2 Small measures the object's near/far position between the far and near edges of the desk. Less sensitive to camera tilt, and moving from the far to the near end of the desk moves the cursor several screen heights, so it is much more sensitive. Updates at ~10 Hz while the desk reference follows slowly on its own. Falls back to size while the model is unavailable. <b>Object size</b> (default): uses how large the object looks. Not applied to pens.</>)}</Info></label>
              <select id="depth-source" value={s.depth_source ?? "size"} onChange={(e) => apply({ depth_source: e.target.value as "size" | "model" })}>
                <option value="size">{t("물체 크기 (기본)", "Object size (default)")}</option>
                <option value="model">{t("깊이 모델 · Depth Anything V2 Small", "Depth model · Depth Anything V2 Small")}{info?.depth_model_available === false ? t(" — 모델 없음, 크기 사용", " — not installed, using size") : ""}</option>
              </select>
              {(s.depth_source ?? "size") === "model" && (
                <>
                  <label htmlFor="depth-range" className="with-info">{t("깊이 감도", "Depth sensitivity")}: ×{(s.depth_model_range ?? 3).toFixed(1)}
                    <Info>{t("물체가 책상 맨 뒤에서 맨 앞까지 가면 커서가 움직이는 화면 높이의 배수입니다. 값을 올리면 더 민감하지만 떨림도 함께 커집니다.", "How many screen heights the cursor moves when the object goes from the far end to the near end of the desk. Higher is more sensitive, and jitter grows with it.")}</Info></label>
                  <input id="depth-range" type="range" min={0.5} max={10} step={0.5} value={s.depth_model_range ?? 3}
                    onChange={(e) => apply({ depth_model_range: Number(e.target.value) })} />
                  <div className="row">
                    <button type="button" onClick={() => { void resetDepthReference().then(setInfo, (e) => setErr(String(e))); }}>
                      {t("깊이 기준 다시 잡기", "Retake depth reference")}
                    </button>
                    <span className="small muted">{live?.depth_source === "model" ? t("깊이 모델로 계산 중", "using the depth model")
                      : info?.depth_model_available === false ? t("모델이 없어 크기 사용 중", "model missing, using size")
                      : t("기준을 모으는 중…", "collecting the reference…")}</span>
                  </div>
                </>
              )}
            </>
          )}
          </>}
          <label htmlFor="mouse-obj">{t("커서로 쓸 물체", "Cursor object")}</label>
          <select id="mouse-obj" value={s.object_id ?? ""}
            onChange={(e) => void apply({ object_id: Number(e.target.value) })}>
            {objects.map((o) => (
              <option key={o.id} value={o.id}>{o.name}{o.kind === "pen" ? t(" (펜 · Beta, 닿으면 클릭)", " (pen · Beta, touch = click)") : ""}</option>
            ))}
          </select>
        </div>
      )}

      {mode !== "off" && s && (
        <>
          <div className="field">
            {advanced && depthMode && <>
              <p className="small muted">{t("좌우 이동은 X, 가까워지면 커서 위·멀어지면 아래로 이동합니다. 손바닥/물체 크기로 깊이를 추정합니다.", "Sideways moves X; closer moves the cursor up, farther moves it down. Depth is estimated from palm or object size.")}
                <Info>{t("수평 카메라에서 카메라 쪽으로 다가가면 영상 속 크기가 커집니다. 이 크기 변화를 앞뒤 거리로 바꿔 커서 위아래로 씁니다.", "With a level camera, things get bigger as they approach. That size change becomes distance, which moves the cursor up and down.")}</Info></p>
              <Slider id="depth-sensitivity" label={t("좌우·깊이 이동 감도", "X and depth sensitivity")} value={s.depth_sensitivity} min={.2} max={6} step={.1} onChange={(v) => apply({ depth_sensitivity: v })} />
              <Slider id="depth-gain" label={t("깊이 이동 감도", "Depth sensitivity")} value={s.depth_gain} min={.2} max={5} step={.1} onChange={(v) => apply({ depth_gain: v })} />
            </>}
            <fieldset className="axis-sens">
              <legend className="small with-info">{t(`커서 감도·방향 (${mode === "hand" ? "맨손" : "물체"} 마우스)`, `Cursor sensitivity & direction (${mode === "hand" ? "hand" : "object"} mouse)`)}
                <Info>{t("감도 2× = 조금만 움직여도 커서가 두 배 멀리 움직입니다. 위의 이동 감도에 곱해집니다. 방향이 반대면 반전을 켜세요. 자동 보정도 방향을 정합니다.", "2× = the cursor moves twice as far. Multiplies the sensitivity above. Turn on flip if the direction is reversed; auto calibration also sets it.")}</Info>
              </legend>
              <label htmlFor="sens-x">{t("좌우 감도", "X sensitivity")} ({s.sens_x.toFixed(1)}×)</label>
              <input id="sens-x" type="range" min={0.2} max={5} step={0.1} value={s.sens_x}
                onChange={(e) => void apply({ sens_x: Number(e.target.value) })} />
              <label htmlFor="sens-y">{t("상하 감도", "Y sensitivity")} ({s.sens_y.toFixed(1)}×)</label>
              <input id="sens-y" type="range" min={0.2} max={5} step={0.1} value={s.sens_y}
                onChange={(e) => void apply({ sens_y: Number(e.target.value) })} />
              <div className="row">
                <label className="check">
                  <input type="checkbox" checked={s.mirror} onChange={(e) => void apply({ mirror: e.target.checked })} />
                  {t("좌우 반전", "Flip X")}
                </label>
                <label className="check">
                  <input type="checkbox" checked={s.invert_y} onChange={(e) => void apply({ invert_y: e.target.checked })} />
                  {t("상하 반전", "Flip Y")}
                </label>
                {(s.sens_x !== 1 || s.sens_y !== 1 || s.mirror || s.invert_y) && (
                  <button type="button" className="small act-reset"
                    onClick={() => void apply({ sens_x: 1, sens_y: 1, mirror: false, invert_y: false })}>{t("기본값", "Defaults")}</button>
                )}
              </div>
            </fieldset>
            {advanced && depthMode && <fieldset className="desk-correct">
              <legend className="small with-info">{t("가장자리 사선 보정", "Edge slant correction")}
                <Info wide>{t(<>화면 가운데에서는 앞뒤 이동이 커서 위아래로 곧게 가지만, 가장자리에서는 영상에서 사선으로 보입니다(원근).
                  가까워질수록 물체가 화면 가운데에서 멀어지는 만큼을 빼서 폅니다.</>,
                  <>Near the edges, forward/back looks slanted in the video (perspective). This subtracts how far the object drifts from the center as it approaches.</>)}</Info>
              </legend>
              <label className="check">
                <input type="checkbox" checked={s.depth_perspective} onChange={(e) => void apply({ depth_perspective: e.target.checked })} />
                {t("크기 기반 사선 보정", "Size-based slant correction")} <span className="badge-rec">{t("권장", "Recommended")}</span>
              </label>
              <p className="small muted">{t("지금", "Now")}: {live?.perspective_active ? t("크기 기반 사선 보정 중", "size-based slant correction") : t("보정 없음", "no correction")}</p>
            </fieldset>}
            {advanced && <label className="check">
              <input type="checkbox" checked={s.invert_scroll} onChange={(e) => void apply({ invert_scroll: e.target.checked })} />
              {t("스크롤 반전", "Invert scroll")}
            </label>}
            <label htmlFor="smooth" className="with-info">{t("부드럽게 ↔ 빠르게", "Smooth ↔ Fast")} ({s.smoothing.toFixed(1)})
              <Info>{t("왼쪽 = 떨림이 적지만 조금 늦게 따라옴, 오른쪽 = 빠르지만 손떨림도 보임.", "Left = less jitter but a little lag; right = faster but shows hand tremor.")}</Info></label>
            <input id="smooth" type="range" min={0.3} max={4} step={0.1} value={s.smoothing}
              onChange={(e) => void apply({ smoothing: Number(e.target.value) })} />
            {advanced && mode === "hand" && s.hand_click_style === "pinch" && (
              <>
                <label htmlFor="pinch" className="with-info">{t("집기 민감도", "Pinch sensitivity")} ({s.pinch_on.toFixed(2)})
                  <Info>{t("엄지와 손가락 끝이 이 거리(손 크기 대비)보다 가까우면 집은 것으로 봅니다. 클릭이 잘 안 되면 높이고, 저절로 눌리면 낮추세요.", "A pinch registers when thumb and fingertip are closer than this (relative to hand size). Raise it if clicks are missed; lower it if they fire on their own.")}</Info></label>
                <input id="pinch" type="range" min={0.15} max={0.5} step={0.01} value={s.pinch_on}
                  onChange={(e) => void apply({ pinch_on: Number(e.target.value) })} />
              </>
            )}
          </div>
          {advanced && mode === "hand" && <div className="field">
            <label htmlFor="hand-control" className="with-info">{t("손 이동 방식", "Hand movement")}
              <Info>{t(<><b>좌우 + 깊이</b>: 옆 카메라용, 손을 카메라 쪽으로 밀면 위. <b>터치패드</b>: 검지를 책상에 댄 동안만 이동.
                <b> 공중 마우스</b>: 영상 속 손 위치가 곧 화면 위치.</>,
                <><b>X + depth</b>: for a side camera; push toward the camera to go up. <b>Touchpad</b>: moves only while the index finger touches the desk. <b>Air mouse</b>: the hand's position in the video is the screen position.</>)}</Info></label>
            <select id="hand-control" value={s.hand_control}
              onChange={(e) => void apply({ hand_control: e.target.value as "depth" | "touchpad" | "air" })}>
              <option value="depth">{t("수평 카메라 · 좌우 + 깊이", "Level camera · X + depth")}</option>
              {deskView && <option value="touchpad">{t("책상 터치패드 · 접촉 중 상대 이동 (Desk View)", "Desk touchpad · relative while touching (Desk View)")}</option>}
              <option value="air">{t("공중 마우스 · 영상 XY (기본)", "Air mouse · image XY (default)")}</option>
            </select>
            <label htmlFor="click-style">{t("클릭 방식", "Click style")}</label>
            <select id="click-style" value={s.hand_click_style}
              onChange={(e) => void apply({ hand_click_style: e.target.value as "finger" | "pinch" })}>
              <option value="finger">{t("검지·중지 든 채 내려서 클릭 (마우스처럼)", "Keep fingers raised, lower to click (like a mouse)")}</option>
              <option value="pinch">{t("엄지 집기 + 스크롤", "Thumb pinch + scroll")}</option>
            </select>
            {s.hand_click_style === "finger" && <Slider id="finger-press" label={t("클릭 민감도 (내림 정도)", "Click sensitivity (how far down)")}
              value={s.finger_press} min={.3} max={.85} step={.01} onChange={(v) => apply({ finger_press: v })} />}
            {s.hand_control === "touchpad" && <>
              <p className="small muted">{t("손 검지가 책상에 닿았을 때만 이동합니다. 영상에서 종이 4점 또는 기준선 2점을 먼저 보정하세요.", "Moves only while the index finger touches the desk. Calibrate 4 paper corners or a 2-point baseline first.")}
                {" "}{t("현재", "Now")}: {live?.surface_mode === "quad" ? t("4점 보정", "4-point") : live?.surface_mode === "line" ? t("기준선 보정", "baseline") : live?.surface_mode === 'deskview' ? t('Desk View 전체 책상', 'Desk View whole desk') : t("보정 필요", "needs calibration")} · {live?.touching ? t("접촉", "touching") : t("떨어짐", "lifted")}</p>
              {deskView && <p className="small muted">{t("Desk View에서는 보정된 XY 이동과 손가락 상대 깊이/자세를 사용합니다. 접촉 판정은 추정이며 높이 슬라이더로 조절하세요. 크기 기반 깊이 보정은 적용하지 않습니다.", "In Desk View, calibrated XY and relative finger depth and pose are used. Contact is estimated; tune it with the height slider. Size-based depth correction is off.")}</p>}
              <Slider id="touch-sensitivity" label={t("손 이동 감도", "Hand sensitivity")} value={s.touch_sensitivity} min={0.2} max={6} step={0.1} onChange={(v) => apply({ touch_sensitivity: v })} />
              <Slider id="touch-height" label={t("접촉 판정 높이", "Contact height")} value={s.touch_height} min={-1} max={1} step={0.05} onChange={(v) => apply({ touch_height: v })} />
              <Slider id="touch-margin" label={t("책상 허용 범위", "Desk margin")} value={s.touch_margin} min={0} max={0.15} step={0.005} onChange={(v) => apply({ touch_margin: v })} />
              <Slider id="touch-depth" label={t("크기 변화로 깊이 보정", "Depth from size change")} value={s.touch_depth_blend} min={0} max={1} step={0.05} disabled={deskView} onChange={(v) => apply({ touch_depth_blend: v })} />
              <Slider id="touch-deadzone" label={t("손 떨림 제거", "Tremor filter")} value={s.touch_deadzone} min={0} max={0.04} step={0.001} onChange={(v) => apply({ touch_deadzone: v })} />
              <Slider id="scroll-gain" label={t("두 손가락 스크롤 감도", "Two-finger scroll sensitivity")} value={s.scroll_gain} min={1} max={100} step={1} onChange={(v) => apply({ scroll_gain: v })} />
            </>}
          </div>}
          {mode === "object" && objects.find((o) => o.id === s.object_id)?.kind === "pen" && <div className="field">
            <p className="feature-note"><BetaBadge /> {t("펜 입력: 펜촉·접촉 인식은 환경에 따라 달라질 수 있습니다. 자동 보정 후 사용하세요.", "Pen input: tip and contact detection may vary with your setup. Calibrate before use.")}</p>
            <label className="check"><input type="checkbox" checked={s.pen_relative}
              onChange={(e) => void apply({ pen_relative: e.target.checked })} />{t("펜촉 접촉 중 상대 이동", "Relative movement while the tip touches")}</label>
            <Slider id="pen-sensitivity" label={t("펜 이동 감도", "Pen sensitivity")} value={s.pen_sensitivity} min={0.2} max={6} step={0.1} onChange={(v) => apply({ pen_sensitivity: v })} />
            <Slider id="pen-depth" label={t("펜 크기 변화로 깊이 보정", "Depth from pen size change")} value={s.pen_depth_blend} min={0} max={1} step={0.05} disabled={deskView} onChange={(v) => apply({ pen_depth_blend: v })} />
            {deskView && <p className="small muted">{t("Desk View의 펜 접촉은 [펜·맨손 그리기]에서 닿음·떼기 보정 또는 수동 그리기로 지정하세요.", "In Desk View, set pen contact in [Pen & Hand Drawing] with touch/lift samples or hold-to-draw.")}</p>}
          </div>}
          {advanced && <dl className="mouse-status">
            <div><dt>{t("손", "Hand")}</dt><dd>{live?.hand_visible ? t("보임", "Visible") : t("안 보임", "Not visible")}</dd></div>
            <div><dt>{t("동작", "Gesture")}</dt><dd>{GESTURE_LABEL[live?.gesture ?? "none"] ?? live?.gesture}{live?.freeze ? t(" · 커서 고정", " · Cursor frozen") : ""}</dd></div>
            <div>
              <dt>{t("집기 거리", "Pinch distance")}</dt>
              <dd>
                <span className="bar" aria-hidden="true">
                  <span className="fill" style={{
                    left: 0, width: `${Math.min(100, ((live?.pinch_index ?? 1) / 1.0) * 100)}%`,
                    background: (live?.pinch_index ?? 1) < (s.pinch_on ?? 0.3) ? "#ff4d6d" : "#5b9dff",
                  }} />
                </span>
              </dd>
            </div>
          </dl>}
          {mode === "hand" && (
            <ul className="small muted gesture-help">
              <li>{s.hand_control === "touchpad" ? t("책상에 검지를 댄 채 움직이면 커서가 상대적으로 이동합니다. 손을 떼면 멈춥니다.", "Move with the index finger on the desk to move the cursor; lift to stop.") : t("손바닥을 움직이면 커서가 움직입니다.", "Move your palm to move the cursor.")}</li>
              {s.hand_click_style === "finger" ? <>
                <li>{t("검지·중지를 든 채로 두고, 중지를 내리면 = 왼쪽 클릭 (누른 채 움직이면 드래그)", "Keep index and middle raised; lower the middle finger = left click (move while down to drag)")}</li>
                <li>{t("검지를 내리면 = 오른쪽 클릭", "Lower the index finger = right click")}</li>
              </> : <>
                <li>{t("엄지 + 검지 끝 집기 = 왼쪽 클릭 (집은 채로 움직이면 드래그)", "Thumb + index pinch = left click (move while pinched to drag)")}</li>
                <li>{t("엄지 + 가운뎃손가락 끝 집기 = 오른쪽 클릭", "Thumb + middle pinch = right click")}</li>
                <li>{s.hand_control === "touchpad" ? t("검지·중지를 책상에 대고 위아래로 = 스크롤", "Index and middle on the desk, move up/down = scroll") : t("검지·중지만 펴고 엄지·약지·새끼를 쥔 채 위아래로 = 스크롤", "Extend index and middle, fold thumb, ring and little fingers; move up/down = scroll")}</li>
              </>}
            </ul>
          )}
        </>
      )}
      </fieldset>
      {err && <p className="error small" role="alert">{err}</p>}
    </Panel>
  );
}

function Slider({ id, label, value, min, max, step, disabled, onChange }: {
  id: string; label: string; value: number; min: number; max: number; step: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return <><label htmlFor={id}>{label} ({value.toFixed(step < 0.01 ? 3 : step < 1 ? 2 : 0)})</label>
    <input id={id} type="range" min={min} max={max} step={step} value={value} disabled={disabled}
      onChange={(e) => onChange(Number(e.target.value))} /></>;
}
