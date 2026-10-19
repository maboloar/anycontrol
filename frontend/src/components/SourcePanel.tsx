import { ActionIcon } from "./ActionIcon";
import { useEffect, useRef, useState } from "react";
import { getCameras, getSource, openDeskViewSetup, putCameraPower, putPlayback, putSource, restartSource, type SourceSpec } from "../api";
import type { CameraDevice } from "../protocol";
import { useApp } from "../store";
import { Panel } from "./Panel";
import { t } from "../i18n";
import { sv } from "../serverText";

/** 카메라 선택. 연속성 카메라(iPhone)를 우선 추천한다. */
export function SourcePanel() {
  const [cams, setCams] = useState<CameraDevice[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [spec, setSpec] = useState<SourceSpec | null>(null);
  const src = useApp((s) => s.telemetry?.source);
  const conn = useApp((s) => s.conn);
  const normalCamera = useRef<Extract<SourceSpec, { kind: 'camera' }> | null>(null);
  const advanced = useApp((s) => s.devMode);

  useEffect(() => {
    if (conn !== "open") return;
    getCameras().then(setCams, (e: unknown) => setErr(String(e)));
    getSource().then((r) => setSpec(r.spec), (e: unknown) => setErr(String(e)));
  }, [conn]);

  const apply = async (spec: SourceSpec, reset = false) => {
    setBusy(true);
    setErr(null);
    try {
      if (reset) await putSource(spec, true); else await putSource(spec);
      setSpec(spec);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const [showSamples, setShowSamples] = useState(() => {
    try { return localStorage.getItem(SAMPLES_KEY) === "1"; } catch { return false; }
  });
  const toggleSamples = (on: boolean) => {
    setShowSamples(on);
    try { localStorage.setItem(SAMPLES_KEY, on ? "1" : "0"); } catch { /* 이번 화면에서만 */ }
  };
  const currentIndex = src?.kind === "camera" ? src.index : undefined;
  const mirror = spec?.kind === "camera" ? Boolean(spec.mirror) : false;
  const deskOn = spec?.kind === 'camera' && Boolean(spec.desk_view);
  const deskAvailable = cams.some((c) => c.is_desk_view);
  const enabled = spec?.kind === "camera" ? (spec.enabled ?? src?.enabled ?? true) : true;
  const currentCam = cams.find((c) => c.unique_id === (spec?.kind === 'camera' ? spec.device_id : undefined)) ?? cams.find((c) => c.index === currentIndex);
  const deskBlocked = !deskOn && !deskAvailable;
  const deviceName = currentCam?.name ?? src?.name ?? t('카메라', 'camera');
  const toggleDesk = async (enabled: boolean) => {
    if (spec?.kind !== 'camera') return;
    if (!enabled) {
      await apply(normalCamera.current ?? { ...spec, desk_view: false });
      return;
    }
    normalCamera.current = { ...spec, desk_view: false };
    const current = cams.find((c) => c.unique_id === spec.device_id) ?? cams.find((c) => c.index === currentIndex);
    const desk = cams.find((c) => c.unique_id === current?.companion_id) ?? cams.find((c) => c.is_desk_view);
    if (!desk) { setErr(t('Desk View 장치를 찾을 수 없습니다. iPhone을 연결하고 장치 새로고침을 누르세요.', 'No Desk View device found. Connect an iPhone and press Refresh devices.')); return; }
    const parent = cams.find((c) => c.unique_id === desk.parent_id);
    await apply({ ...spec, desk_view: true, device_id: parent?.unique_id ?? desk.unique_id,
      index: parent?.index ?? desk.index });
  };
  const refresh = async () => {
    setBusy(true);
    try { setCams(await getCameras()); setErr(null); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  };
  const setup = async () => {
    setBusy(true);
    try { await openDeskViewSetup(); setErr(null); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  };
  const playback = async () => {
    if (!spec) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await putPlayback(!(src?.paused ?? spec.paused));
      setSpec({ ...spec, paused: r.paused });
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const power = async () => {
    if (spec?.kind !== "camera") return;
    setBusy(true);
    try { const r = await putCameraPower(!enabled); setSpec({ ...spec, enabled: r.enabled }); setErr(null); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  };
  const restart = async () => {
    setBusy(true);
    try { const r = await restartSource(); setSpec(r.spec); setErr(null); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  };

  return (
    <Panel title={t("카메라", "Camera")} label="카메라" tour="source" info={t(<>입력 영상을 고릅니다. <b>iPhone 연속성 카메라</b>(USB 유선 권장)가 가장 정확합니다. 책상 옆에 수평으로 세우거나, Mac 위에 걸고 <b>Desk View</b>로 씁니다.</>,
      <>Choose the video input. <b>iPhone Continuity Camera</b> (USB recommended) is most accurate. Stand it level beside the desk, or mount it on the Mac and use <b>Desk View</b>.</>)}>
      <div className="row source-controls">
        {spec?.kind === "camera" && <button type="button" className={enabled ? "act-pause" : "act-go"} disabled={busy} aria-pressed={enabled}
          onClick={() => void power()}><ActionIcon name="power" />{enabled ? t("카메라 끄기", "Turn camera off") : t("카메라 켜기", "Turn camera on")}</button>}
        <button type="button" className={(src?.paused ?? spec?.paused) ? "act-go" : "act-pause"} disabled={busy || !spec || !enabled} onClick={() => void playback()}>
          <ActionIcon name={(src?.paused ?? spec?.paused) ? "play" : "pause"} />{(src?.paused ?? spec?.paused) ? t("영상 재생", "Play video") : t("영상 정지", "Pause video")}</button>
        {spec && spec.kind !== "camera" && <button type="button" className="act-reset" disabled={busy} onClick={() => void restart()}><ActionIcon name="reset" />{t("처음부터 선택", "Restart from beginning")}</button>}
      </div>
      {advanced && <><label className="check dev-check" title={deskBlocked && spec?.kind === 'camera' ? t(`이 ${deviceName}${josa(deviceName)} Desk View를 지원하지 않습니다`, `${deviceName} does not support Desk View`) : undefined}><input type="checkbox" checked={deskOn}
        disabled={busy || spec?.kind !== 'camera' || deskBlocked}
        onChange={(e) => void toggleDesk(e.target.checked)} />{t("Desk View · 책상 위에서 보기", "Desk View · top-down desk view")}</label>
      <div className="row">
        <button type="button" disabled={busy} onClick={() => void refresh()}><ActionIcon name="reset" />{t("장치 새로고침", "Refresh devices")}</button>
        {deskOn && <button type="button" className="dev-btn" disabled={busy} onClick={() => void setup()}>{t("Desk View 설정 열기", "Open Desk View setup")}</button>}
        {deskOn && <button type="button" className="dev-btn" disabled={busy} onClick={() => { if (spec) void apply(spec, true); }}><ActionIcon name="check" />{t("구도 적용 · 다시 선택", "Apply framing · Reselect")}</button>}
      </div>
      <p className="small muted">{deskOn
        ? t('Desk View 1920×1440 · 최대 30fps. 펜·손 이동에 책상 XY 좌표를 사용합니다. 설정 창에서 구도/줌을 바꾼 뒤 [구도 적용 · 다시 선택]을 누르고 물체를 다시 지정하세요. 종이 4점 보정으로 범위를 좁힐 수 있습니다.', 'Desk View 1920×1440 · up to 30fps. Pen and hand movement use desk XY. After changing framing or zoom in setup, press [Apply framing · Reselect] and select objects again. A 4-point paper calibration can narrow the area.')
        : deskAvailable ? t('Desk View를 켜면 지원되는 iPhone의 책상 원근 보정 영상을 사용합니다.', 'Desk View uses the perspective-corrected desk video from a supported iPhone.')
          : t('지원되는 iPhone을 연결하면 Desk View를 사용할 수 있습니다.', 'Connect a supported iPhone to use Desk View.')}</p></>}
      {!advanced && <div className="row">
        <button type="button" disabled={busy} onClick={() => void refresh()}><ActionIcon name="reset" />{t("장치 새로고침", "Refresh devices")}</button>
      </div>}
      <ul className="cam-list">
        {cams.filter((c) => !c.is_desk_view).map((c) => {
          const best = c.formats.reduce((m, f) => Math.max(m, f.max_fps), 0);
          const active = src?.device_id === c.unique_id || src?.parent_id === c.unique_id || currentIndex === c.index;
          return (
            <li key={c.unique_id}>
              <button
                type="button"
                disabled={busy}
                aria-pressed={active}
                className={active ? "active" : ""}
                onClick={() => {
                  const camera = { kind: 'camera' as const, index: c.index, device_id: c.unique_id,
                    width: 1280, height: 720, fps: best >= 60 ? 60 : 30, mirror, desk_view: false };
                  normalCamera.current = camera;
                  void apply({ ...camera, desk_view: deskOn && Boolean(c.companion_id) });
                }}
              >
                <span>{c.name}</span>
                <small>
                  {c.is_continuity ? "iPhone · " : ""}{t(`최대 ${best}fps`, `up to ${best}fps`)}
                </small>
              </button>
            </li>
          );
        })}
      </ul>
      <label className="check small"><input type="checkbox" checked={showSamples} onChange={(e) => toggleSamples(e.target.checked)} />{t("데모 영상 표시", "Show demo videos")}</label>
      {showSamples && <ul className="cam-list samples">
        {advanced && <li><button type="button" disabled={busy} aria-pressed={src?.kind === "synthetic"}
          className={`dev-btn ${src?.kind === "synthetic" ? "active" : ""}`}
          onClick={() => apply({ kind: "synthetic", width: 1280, height: 720, fps: 30, paused: true })}>
          <span>{t("합성 장면", "Synthetic scene")}</span><small>{t("카메라 없이 테스트", "Test without a camera")}</small></button></li>}
        {SAMPLES.map(([path, label]) => <li key={path}><button type="button" disabled={busy}
          aria-pressed={spec?.kind === "file" && spec.path === path}
          className={spec?.kind === "file" && spec.path === path ? "active" : ""}
          onClick={() => apply({ kind: "file", path, loop: true, paused: true })}>
          <span>{path.split("/").pop()}</span><small>{t(...label)}</small></button></li>)}
      </ul>}
      {spec && spec.kind !== "camera" && <p className="small muted">{t("일시정지는 등록·보정을 유지합니다. [처음부터 선택]은 장면과 등록을 초기화하고 첫 화면에서 멈춥니다.", "Pausing keeps registrations and calibration. [Restart from beginning] resets the scene and registrations and stops on the first frame.")}</p>}
      {err && <p className="error" role="alert">{err}</p>}
      {src?.status === 'error' && src.error && <p className="error" role="alert">{sv(src.error)}</p>}
    </Panel>
  );
}

const SAMPLES_KEY = "anycontrol.source.samples";
/** 프로젝트 폴더 samples/ 의 테스트 영상 (반복 재생) */
const SAMPLES: [string, readonly [string, string]][] = [["samples/test.mov", ["지갑 테스트 영상 반복", "Wallet test video, looped"]], ["samples/pen_test.mov", ["펜 테스트 영상 반복", "Pen test video, looped"]]];

/** 받침에 따라 은/는을 고른다. 한글이 아니면 '는'. */
function josa(name: string): string {
  const c = name.trim().charCodeAt(name.trim().length - 1);
  return c >= 0xac00 && c <= 0xd7a3 && (c - 0xac00) % 28 !== 0 ? '은' : '는';
}
