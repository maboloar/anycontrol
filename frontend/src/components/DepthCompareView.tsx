import { useEffect, useRef, useState } from "react";
import { downloadDepthModel, getDepthCompare, getDepthModel } from "../api";
import { t as tr } from "../i18n";
import type { DepthCompareData, DepthModelStatus, DepthRollInfo } from "../protocol";
import { Info } from "./Info";

const REASON = (r: string | undefined) => {
  switch (r) {
    case "model_missing": return tr("깊이 모델이 아직 없습니다.", "The depth model is not installed yet.");
    case "contact_method": return tr("‘바닥 기하 접촉 판정 (실험)’을 먼저 켜 주세요.", "Turn on ‘Floor-geometry contact detection’ first.");
    case "learning": return tr("책상 면을 더 배워야 비교할 수 있습니다.", "The desk plane needs more learning before comparing.");
    case "no_floor": return tr("바닥 영역을 찾지 못했습니다.", "No floor region found.");
    default: return tr("영상을 기다리는 중…", "Waiting for video…");
  }
};

function statusText(d: DepthRollInfo | null | undefined): string {
  if (!d) return tr("바닥 맵이 준비되면 표시됩니다", "Shown once the floor map is ready");
  if (!d.enabled) return tr("꺼짐 · 터치로 배운 롤 사용", "Off · using the touch-learned roll");
  if (!d.available) return tr("모델 미설치 · 터치로 배운 롤 사용", "Model not installed · using the touch-learned roll");
  if (d.applied && d.deg != null) return tr(`적용 중 · 롤 ${d.deg.toFixed(1)}° (a ${d.a?.toFixed(0) ?? "-"}px)`, `Applied · roll ${d.deg.toFixed(1)}° (a ${d.a?.toFixed(0) ?? "-"} px)`);
  return tr(`측정 중 (${d.n}/3) · 그동안 터치로 배운 롤 사용`, `Measuring (${d.n}/3) · touch-learned roll meanwhile`);
}

/** 펜 바닥 기울기에 쓰는 깊이 모델(Depth Anything V2 Small, Core ML) 한 줄 설정 (개발자 모드).
 *  기본으로 켜져 있고, 가중치가 설치돼 있을 때만 작동한다. 가중치는 사용자가 확인한 뒤에만 내려받는다. */
export function DepthCompareView({ id, info }: { id: number; info?: DepthRollInfo | null }) {
  const [dl, setDl] = useState<DepthModelStatus | null>(null);
  const [data, setData] = useState<DepthCompareData | null>(null);
  const [showCmp, setShowCmp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  // 내려받는 동안에만 진행 상황을 읽는다
  useEffect(() => {
    if (!dl?.downloading) return;
    const timer = window.setInterval(() => {
      getDepthModel().then((s) => { if (alive.current) setDl(s); }, () => undefined);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [dl?.downloading]);

  const fail = (e: unknown) => { if (alive.current) setErr(String((e as Error)?.message ?? e)); };

  const download = async () => {
    let s: DepthModelStatus | null = null;
    try { s = await getDepthModel(); } catch (e) { fail(e); return; }
    const ok = window.confirm(tr(
      `깊이 모델 가중치(약 ${s.size_mb}MB, ${s.license})를 ${s.source} 에서 내려받아 이 컴퓨터에 저장합니다.\n영상이나 설정은 전송되지 않습니다. 계속할까요?`,
      `Download the depth model weights (~${s.size_mb} MB, ${s.license}) from ${s.source} and store them on this computer.\nNo video or settings are sent. Continue?`));
    if (!ok) return;
    downloadDepthModel().then((r) => { if (alive.current) { setDl(r); setErr(null); } }, fail);
  };

  const compare = () => {
    setBusy(true);
    getDepthCompare(id).then((d) => { if (alive.current) { setData(d); setErr(null); } }, fail)
      .finally(() => { if (alive.current) setBusy(false); });
  };

  const installed = info?.available ?? false;
  return (
    <section className="depth-compare" aria-label={tr("깊이 모델 기울기", "Depth-model tilt")}>
      <p className="small" role="status">
        {tr("깊이 모델 기울기", "Depth-model tilt")}: <b>{statusText(info)}</b>
        <Info>{tr("Depth Anything V2 Small로 책상 평면의 좌우 기울기(롤)를 2초마다 재서 바닥 모델에 적용합니다. 접촉 판정 자체에는 깊이 값을 쓰지 않습니다. 모델이 없거나 끄면 터치로 배운 롤을 씁니다.",
          "Depth Anything V2 Small measures the desk plane's sideways tilt (roll) every 2 s and feeds it to the floor model. Depth values themselves are not used for contact. Without the model, or when off, the touch-learned roll is used.")}</Info>
      </p>
      {err && <p className="small warn" role="alert">{err}</p>}
      {info?.error && <p className="small warn">{info.error}</p>}
      {!installed && !dl?.downloading && (
        <button type="button" className="dev-btn small" onClick={() => { void download(); }}>{tr("깊이 모델 내려받기", "Download depth model")}</button>
      )}
      {dl?.downloading && <p className="small muted">{tr(`내려받는 중… ${dl.downloaded_mb}/${dl.size_mb}MB`, `Downloading… ${dl.downloaded_mb}/${dl.size_mb} MB`)}</p>}
      {dl?.error && <p className="small warn">{dl.error}</p>}
      {installed && (
        <button type="button" className="dev-btn small" aria-expanded={showCmp}
          onClick={() => { const next = !showCmp; setShowCmp(next); if (next) compare(); }}>
          {tr("비교 이미지", "Comparison images")}
        </button>
      )}
      {installed && showCmp && (
        <div className="depth-body">
          <button type="button" className="dev-btn small" disabled={busy} onClick={compare}>
            {busy ? tr("계산 중…", "Computing…") : tr("지금 프레임으로 다시", "Redo on the current frame")}
          </button>
          {data && !data.ready && <p className="small muted" role="status">{REASON(data.reason)}</p>}
          {data?.ready && (
            <>
              <div className="depth-imgs">
                {([["depth_image", tr("깊이 모델 출력", "Depth model output")],
                   ["fit_image", tr("깊이 평면 맞춤", "Depth plane fit")],
                   ["touch_image", tr("터치로 배운 평면", "Touch-learned plane")]] as const).map(([key, label]) => data[key] && (
                  <figure key={key}><img src={data[key]} alt={label} /><figcaption className="small muted">{label}</figcaption></figure>
                ))}
              </div>
              <p className="small muted">
                {tr(`상관 ${data.corr ?? "-"} · 기울기 차이 ${data.angle_deg ?? "-"}° · 롤 깊이 ${data.roll_depth_deg ?? "-"}° / 터치 ${data.roll_touch_deg ?? "-"}° · 평면 잔차 ${data.plane_rms ?? "-"} · 내점 ${data.inlier_frac ?? "-"} · ${data.ms ?? "-"}ms`,
                  `corr ${data.corr ?? "-"} · tilt diff ${data.angle_deg ?? "-"}° · roll depth ${data.roll_depth_deg ?? "-"}° / touch ${data.roll_touch_deg ?? "-"}° · plane residual ${data.plane_rms ?? "-"} · inliers ${data.inlier_frac ?? "-"} · ${data.ms ?? "-"} ms`)}
              </p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
