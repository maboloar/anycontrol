import { ActionIcon } from "./ActionIcon";
import { useState } from "react";
import { getReal, requestRealPermission } from "../api";
import { changeRealOutput, publishReal } from "../realOutputState";
import { useApp } from "../store";
import { Panel } from "./Panel";
import { labels, t } from "../i18n";
const STOP_REASON: Record<string, string> = labels({
  escape: ["ESC 로 꺼졌습니다", "Stopped by ESC"],
  stop: ["긴급 정지로 꺼졌습니다", "Stopped by emergency stop"],
  source: ["소스가 바뀌어 꺼졌습니다", "Stopped because the source changed"],
  user: ["껐습니다", "Turned off"], escape_handled: ["ESC로 꺼졌습니다", "Stopped by ESC"], paused: ["영상 정지로 꺼졌습니다", "Stopped because the video was paused"],
  stale: ["영상 입력이 끊겨 꺼졌습니다", "Stopped because video input was lost"], disconnected: ["앱 연결이 끊겨 꺼졌습니다", "Stopped because the app disconnected"],
  calibration: ["자동 보정을 위해 꺼졌습니다", "Stopped for auto calibration"], error: ["입력 오류로 꺼졌습니다", "Stopped by an input error"],
});
const errText = (e: unknown) => String(e instanceof Error ? e.message : e).replace(/^\d+ /, "");
/** 출력 대상: 가상(웹앱 안) / 실제(macOS 전체 마우스·키보드). 켜면 3초 뒤에 실제로 들어간다. */
export function RealOutputPanel() {
  const conn = useApp((s) => s.conn);

  const info = useApp(s => s.live.real);
  const [err, setErr] = useState<string | null>(null);
  const set = async (on: boolean) => {
    try { await changeRealOutput(on); setErr(null); }
    catch (e) { setErr(errText(e)); }
  };
  const permission = async () => {
    try {
      const r = await requestRealPermission();
      publishReal(await getReal());
      setErr(r.trusted ? null : t("시스템 설정에서 권한을 켠 뒤 서버를 다시 시작하세요", "Enable the permission in System Settings, then restart the server"));
    } catch (e) {
      setErr(errText(e));
    }
  };
  const state = info?.state ?? "off";
  const real = state !== "off";
  return (
    <>
      <Panel label="출력" title={t("출력", "Output")} tour="real" info={t(<>기본은 <b>앱 안의 가상 입력</b>입니다. 실제 OS 입력을 켜면 macOS 마우스·키보드로 전달됩니다. 손쉬운 사용 권한이 필요하고, 3초 뒤 시작하며, <b>ESC</b>로 어디서든 즉시 멈춥니다.</>,
        <>Default is <b>virtual input inside the app</b>. Real input drives the macOS mouse and keyboard. It needs Accessibility permission, starts after 3 seconds and stops instantly with <b>ESC</b>.</>)}>
        <div className="row" role="radiogroup" aria-label={t("출력", "Output")}>
          <button type="button" role="radio" aria-checked={!real} className={`act-safe ${!real ? "active" : ""}`}
            onClick={() => void set(false)}><ActionIcon name="virtual" />{t("가상 (앱 안에서만)", "Virtual (in app only)")}</button>
          <button type="button" role="radio" aria-checked={real} className={`act-real ${real ? "active" : ""}`}
            disabled={conn !== "open" || !info || !info.trusted} onClick={() => void set(true)}><ActionIcon name="real" />{t("실제 (OS 입력)", "Real (OS input)")}</button>
        </div>
        <p className="muted small">
          {t("실제 모드는 마우스·키보드만 macOS 전체에 보냅니다. 게임패드는 가상 전용입니다. 매핑 출력을 켜거나 마우스 모드를 켜야 실제로 움직입니다.",
            "Real mode sends only mouse and keyboard to macOS; the gamepad stays virtual. Turn on mapping output or a mouse mode to move anything.")}
        </p>
        {info && !info.trusted && (
          <div className="warn small">
            {t("손쉬운 사용 권한이 필요합니다. 시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용에서 서버를 실행한 앱(터미널 등)을 켜고 서버를 다시 시작하세요.",
              "Accessibility permission is required. In System Settings → Privacy & Security → Accessibility, enable the app running the server (e.g. Terminal), then restart the server.")}
            <div className="row"><button type="button" className="act-config" onClick={() => void permission()}><ActionIcon name="key" />{t("권한 설정 열기", "Open permission settings")}</button></div>
          </div>
        )}
        {!real && info?.stopped_by && <p className="muted small">{t("실제 입력", "Real input")}: {STOP_REASON[info.stopped_by] ?? info.stopped_by}</p>}
        {err && <p className="error small" role="alert">{err}</p>}
      </Panel>
    </>
  );
}
