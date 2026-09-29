import { ActionIcon } from "./ActionIcon";
import { useEffect, useState } from "react";
import { getReal, putReal, requestRealPermission } from "../api";
import type { RealInfo } from "../protocol";
import { useApp } from "../store";
import { Panel } from "./Panel";
const STOP_REASON: Record<string, string> = {
  escape: "ESC 로 꺼졌습니다",
  stop: "긴급 정지로 꺼졌습니다",
  source: "소스가 바뀌어 꺼졌습니다",
  user: "껐습니다", escape_handled: "ESC로 꺼졌습니다", paused: "영상 정지로 꺼졌습니다",
  stale: "영상 입력이 끊겨 꺼졌습니다", disconnected: "앱 연결이 끊겨 꺼졌습니다",
  calibration: "자동 보정을 위해 꺼졌습니다", error: "입력 오류로 꺼졌습니다",
};
const errText = (e: unknown) => String(e instanceof Error ? e.message : e).replace(/^\d+ /, "");
/** 출력 대상: 가상(웹앱 안) / 실제(macOS 전체 마우스·키보드). 켜면 3초 뒤에 실제로 들어간다. */
export function RealOutputPanel() {
  const conn = useApp((s) => s.conn);

  const [fetched, setFetched] = useState<RealInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (conn !== "open") return;
    let active = true;
    const poll = () => getReal().then(r => { if (active) setFetched(r); }, e => { if (active) setErr(errText(e)); });
    void poll();
    const timer = setInterval(poll, 300);
    return () => { active = false; clearInterval(timer); };
  }, [conn]);
  const info = fetched;
  const set = async (on: boolean) => {
    try {
      const r = await putReal(on);
      setFetched(r);
      const s = useApp.getState();
      s.setLive({ ...s.live, real: r }); // 일시정지 중(프레임 없음)에도 바로 반영
      setErr(null);
    } catch (e) {
      setErr(errText(e));
    }
  };
  const permission = async () => {
    try {
      const r = await requestRealPermission();
      setFetched(await getReal());
      setErr(r.trusted ? null : "시스템 설정에서 권한을 켠 뒤 서버를 다시 시작하세요");
    } catch (e) {
      setErr(errText(e));
    }
  };
  const state = info?.state ?? "off";
  const real = state !== "off";
  return (
    <>
      {real && (
        <div className={`real-banner ${state}`} role="alert">
          {state === "arming"
            ? <>실제 입력 {Math.ceil(info?.remaining_s ?? 0)}초 뒤 켜짐</>
            : <>실제 입력 켜짐 — ESC(어디서든)로 정지</>}
          <button type="button" className="act-stop" onClick={() => void set(false)}><ActionIcon name="stop" />{state === "arming" ? "취소" : "끄기"}</button>
        </div>
      )}
      <Panel label="출력 대상" title="출력 대상" tour="real" info={<>기본은 <b>앱 안의 가상 입력</b>입니다. 실제 OS 입력을 켜면 macOS 마우스·키보드로 전달됩니다. 손쉬운 사용 권한이 필요하고, 3초 뒤 시작하며, <b>ESC</b>로 어디서든 즉시 멈춥니다.</>}>
        <div className="row" role="radiogroup" aria-label="출력 대상">
          <button type="button" role="radio" aria-checked={!real} className={`act-safe ${!real ? "active" : ""}`}
            onClick={() => void set(false)}><ActionIcon name="virtual" />가상 (앱 안에서만)</button>
          <button type="button" role="radio" aria-checked={real} className={`act-real ${real ? "active" : ""}`}
            disabled={conn !== "open" || !info || !info.trusted} onClick={() => void set(true)}><ActionIcon name="real" />실제 (시스템 전체)</button>
        </div>
        <p className="muted small">
          실제 모드는 마우스·키보드만 macOS 전체에 보냅니다. 게임패드는 가상 전용입니다.
          매핑 출력을 켜거나 마우스 모드를 켜야 실제로 움직입니다.
        </p>
        {info && !info.trusted && (
          <div className="warn small">
            손쉬운 사용 권한이 필요합니다. 시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용에서
            서버를 실행한 앱(터미널 등)을 켜고 서버를 다시 시작하세요.
            <div className="row"><button type="button" className="act-config" onClick={() => void permission()}><ActionIcon name="key" />권한 설정 열기</button></div>
          </div>
        )}
        {!real && info?.stopped_by && <p className="muted small">실제 입력: {STOP_REASON[info.stopped_by] ?? info.stopped_by}</p>}
        {err && <p className="error small" role="alert">{err}</p>}
      </Panel>
    </>
  );
}
