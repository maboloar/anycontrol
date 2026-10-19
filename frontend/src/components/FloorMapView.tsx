import { useEffect } from "react";
import { getFloorMap } from "../api";
import { t as tr } from "../i18n";
import { useApp } from "../store";
import { DepthCompareView } from "./DepthCompareView";
import { Info } from "./Info";

const REASON = (reason: string | undefined, learning: number | undefined) => {
  switch (reason) {
    case "contact_method":
      return tr("‘바닥 기하 접촉 판정 (실험)’을 켜면 바닥 맵이 만들어집니다 (펜·맨손 그리기 탭).", "Turn on ‘Floor-geometry contact detection’ to build the floor map (Pen & Hand Drawing tab).");
    case "learning":
      return tr(`책상 면 학습 중 (${learning ?? 0}/40) · 펜을 책상에 대고 가까운 곳과 먼 곳, 좌우로 움직여 주세요`,
        `Learning the desk (${learning ?? 0}/40) · slide the pen on the desk near, far, left and right`);
    case "no_table_color": return tr("책상 색을 아직 모릅니다. 책상이 화면 아래쪽에 보이게 해 주세요.", "Desk color unknown yet. Keep the desk visible at the bottom of the frame.");
    case "no_floor": return tr("바닥 영역을 찾지 못했습니다.", "No floor region found.");
    default: return tr("영상을 기다리는 중…", "Waiting for video…");
  }
};

/** 바닥 그라데이션 맵 보기 (개발자 모드). 펜이 바닥에 닿았을 때의 예상 굵기를 가까움=밝음, 멈=어둠으로 보여 준다. */
export function FloorMapView({ id }: { id: number }) {
  const map = useApp((s) => s.floorMap);
  const overlay = useApp((s) => s.floorOverlay);
  const mirror = useApp((s) => s.previewMirror);
  useEffect(() => {
    let alive = true;
    const load = () => getFloorMap(id).then(m => { if (alive) useApp.getState().setFloorMap(m); },
      () => { if (alive) useApp.getState().setFloorMap(null); });
    void load();
    const timer = window.setInterval(load, 600);
    return () => { alive = false; window.clearInterval(timer); useApp.getState().setFloorMap(null); };
  }, [id]);

  if (!map) return <p className="small muted">{tr("바닥 맵 불러오는 중…", "Loading floor map…")}</p>;
  const tip = map.tip;
  const tipX = tip ? (mirror ? 1 - tip[0] : tip[0]) * 100 : null;
  return (
    <section className="floor-map" aria-label={tr("바닥 그라데이션 맵", "Floor gradient map")}>
      {!map.ready || !map.image ? (
        <p className="small muted" role="status">{REASON(map.reason, map.learning ?? map.samples)}</p>
      ) : (
        <>
          <div className="floor-map-img" style={{ aspectRatio: map.size ? `${map.size[0]} / ${map.size[1]}` : undefined }}>
            <img src={map.image} alt={tr("바닥 맵: 가까울수록 밝음", "Floor map: brighter is nearer")}
              style={mirror ? { transform: "scaleX(-1)" } : undefined} />
            {tipX !== null && tip && <span className={`floor-tip ${map.contact ? "on" : ""}`} aria-hidden="true"
              style={{ left: `${tipX}%`, top: `${tip[1] * 100}%` }} />}
          </div>
          <div className="floor-map-legend" aria-hidden="true"><span>{tr("먼 곳 (어두움)", "far (dark)")}</span><i /><span>{tr("가까운 곳 (밝음)", "near (bright)")}</span></div>
        </>
      )}
      <p className="small muted">
        {map.k != null && tr(`평면 k ${map.k.toFixed(2)} · 좌우 기울기 ${map.roll_deg ?? 0}° · σ ${map.sigma == null ? "-" : map.sigma.toFixed(2)}D · 표본 ${map.samples ?? 0}${map.anchors ? ` · 터치 보정 ${map.anchors}점` : ""}`,
          `plane k ${map.k.toFixed(2)} · roll ${map.roll_deg ?? 0}° · σ ${map.sigma == null ? "-" : map.sigma.toFixed(2)}D · samples ${map.samples ?? 0}${map.anchors ? ` · ${map.anchors} touch pts` : ""}`)}
        {map.hover != null && tr(` · 높이 ${map.hover.toFixed(2)}D${map.contact ? " · 접촉" : ""}`, ` · height ${map.hover.toFixed(2)}D${map.contact ? " · contact" : ""}`)}
        <Info>{tr("접촉한 펜의 굵기는 위치마다 정해져 있습니다(가까울수록 굵음, 카메라가 기울면 좌우로도 달라짐). 이 맵은 그 예상 굵기를 바닥 영역에 흑백으로 그린 것이고, 어두운 선은 8단계 경계입니다. 실제 펜 굵기가 맵 값과 같으면 닿은 것으로 봅니다.",
          "A touching pen has a width fixed by position (wider nearer; also varies sideways if the camera is tilted). This draws that expected width over the floor; dark lines are 8 level steps. When the real pen width matches the map value it is touching.")}</Info>
      </p>
      <label className="check small dev-check">
        <input type="checkbox" checked={overlay} disabled={!map.overlay}
          onChange={(e) => useApp.getState().setFloorOverlay(e.target.checked)} />
        {tr("카메라 영상 위에 겹쳐 보기", "Overlay on the camera view")}
      </label>
      <DepthCompareView id={id} info={map.depth_roll} />
    </section>
  );
}
