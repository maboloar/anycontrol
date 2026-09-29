import { useEffect, useRef, useState, type ReactNode } from "react";
import { useApp } from "../store";
import { placeCard, unionBox, type Box, type Side } from "../tutorial";
import { CameraBuddy } from "./CameraBuddy";

interface Step {
  id: string;
  /** 가리킬 요소의 data-tour 이름들 (여러 개면 모두 감싼다). 비우면 가운데 카드만 */
  targets: string[];
  title: string;
  body: ReactNode;
}

/** 튜토리얼 단계. 짧게, 한 번에 한 곳만 비춘다. 캐릭터가 말풍선으로 설명한다. */
export const STEPS: Step[] = [
  {
    id: "hello", targets: [], title: "안녕하세요, AnyControl 이에요",
    body: <>카메라로 책상 위 <b>물체·펜·맨손</b>의 움직임을 읽어서 마우스·키보드·게임패드 입력으로 바꿔 드려요.
      어디서 무엇을 하면 되는지 하나씩 짚어 볼게요. 금방 끝나요.</>,
  },
  {
    id: "caution", targets: [], title: "먼저 알아 두세요",
    body: (
      <ul>
        <li><b>macOS 전용</b>이에요 (Apple Silicon 기준).</li>
        <li><b>iPhone 연속성 카메라</b>가 가장 잘 돼요. USB 유선 연결을 추천해요. 내장 카메라·웹캠도 되지만 정확도가 떨어져요.</li>
        <li>macOS가 묻는 <b>카메라·손쉬운 사용 권한</b>은 허용해 주세요.</li>
        <li>처음엔 <b>앱 안의 가상 입력</b>으로만 움직여요. 실제 마우스·키보드는 직접 켜야 전송돼요.</li>
        <li>깊이와 접촉은 영상으로 <b>추정</b>한 값이에요. 자동 보정으로 내 환경에 맞춰 주세요.</li>
        <li>문제가 생기면 <b>ESC</b>. 모든 출력이 바로 멈춰요.</li>
      </ul>
    ),
  },
  {
    id: "camera", targets: ["source"], title: "카메라 세팅",
    body: <>여기서 카메라를 골라요. iPhone은 <b>책상 옆에 수평으로</b> 세워 두거나, Mac 위에 걸고 <b>Desk View</b>(위에서 본
      책상)로 써요. 연결한 카메라를 목록에서 선택해 주세요.</>,
  },
  {
    id: "object", targets: ["camera", "select-object"], title: "물체 등록",
    body: <>영상에서 물체를 <b>드래그로 감싸거나 클릭</b>하면 추적을 시작해요. 컵, 지우개, 지갑처럼 모양이 잘 안 변하는 물건이 좋아요.
      등록할 때 <b>모양을 기억</b>해 두었다가 가려지거나 화면 밖에 나갔다 와도 다시 찾아요.
      엉뚱하게 잡히면 물체 패널의 <b>[다시 선택]</b>을 눌러 주세요.</>,
  },
  {
    id: "pen", targets: ["select-pen"], title: "펜",
    body: <><b>[펜 (두 점)]</b>을 누르고 <b>펜촉 → 반대쪽 끝</b> 순서로 두 점을 찍어요.
      펜촉이 책상에 닿아 있는 동안 <b>[펜·맨손 그리기]</b> 탭에 그림이 그려져요.</>,
  },
  {
    id: "hand", targets: ["mouse"], title: "맨손·물체 마우스",
    body: (
      <>
        여기서 <b>맨손</b>이나 등록한 <b>물체</b>를 커서로 써요. 좌우로 움직이면 좌우, 카메라 쪽으로 다가가면 위로 가요.
        <ul>
          <li>엄지+검지 집기 = 왼쪽 클릭</li>
          <li>엄지+중지 집기 = 오른쪽 클릭</li>
          <li>검지·중지 펴고 움직이기 = 스크롤</li>
        </ul>
        <b>[자동 보정]</b>을 따라 하면 범위·민감도가 알아서 맞춰져요. 상하·좌우 <b>감도와 반전</b>도 여기서 바꿔요.
      </>
    ),
  },
  {
    id: "paper", targets: ["select-calib"], title: "종이로 원근 보정",
    body: <>화면 가장자리에서 커서가 비스듬히 움직이면 <b>A4 종이</b>를 손·물체 움직일 자리에 놓고
      <b> [📄 종이 선택]</b>을 누른 뒤 영상에서 종이 <b>네 모서리</b>를 찍어 주세요. 그 종이가 반듯한 마우스 패드가 돼요.
      종이는 찍고 나서 치워도 괜찮아요.</>,
  },
  {
    id: "demos", targets: ["demos"], title: "매핑과 데모",
    body: <><b>[매핑·게임패드]</b>에서 물체 움직임을 게임패드 축·버튼·키에 연결하고, <b>레이싱·좀비</b> 게임으로 바로 확인해 봐요.
      그림판과 가상 데스크톱도 있어요.</>,
  },
  {
    id: "real", targets: ["real"], title: "실제 입력",
    body: <>다른 앱까지 조작하려면 여기서 <b>실제 OS 입력</b>을 켜요. 손쉬운 사용 권한이 필요하고, 켜면 3초 뒤에 시작해요.
      언제든 <b>ESC</b>로 멈출 수 있어요.</>,
  },
  {
    id: "bye", targets: ["help"], title: "끝내는 법",
    body: (
      <>
        다 쓰셨으면 <b>브라우저 창(탭)을 닫으면 끝</b>이에요. 터미널은 <b>몇 초만 기다리면</b> 카메라·입력을 정리하고 알아서 꺼져요.
        <p><span className="info static" aria-hidden="true">i</span> 아이콘에 마우스를 올리면 짧은 설명이 나와요.
          이 안내는 위쪽 <b>[? 안내]</b> 버튼으로 언제든 다시 볼 수 있어요.</p>
      </>
    ),
  },
];

const PAD = 6; // 비추는 구멍 여백

interface Layout {
  box: Box | null;
  card: { left: number; top: number; side: Side };
}

/**
 * 처음 열면 뜨는 단계별 안내. 작은 픽셀 웹캠 캐릭터가 말풍선으로 한 곳씩 밝게 비추며 설명한다.
 * ←/→ 로 넘기고 ESC 로 닫는다 (ESC 는 원래대로 긴급 정지도 함께 한다).
 */
export function Tutorial() {
  const open = useApp((s) => s.tourOpen);
  const setTour = useApp((s) => s.setTour);
  const [idx, setIdx] = useState(0);
  const [layout, setLayout] = useState<Layout | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const step = STEPS[Math.min(idx, STEPS.length - 1)]!;
  const last = idx >= STEPS.length - 1;

  useEffect(() => {
    if (open) setIdx(0);
  }, [open]);

  const targetsOf = (s: Step) =>
    s.targets.flatMap((t) => Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${t}"]`)));

  // 단계가 바뀌면 가리킬 곳을 화면 가운데로 스크롤
  useEffect(() => {
    if (!open) return;
    targetsOf(step)[0]?.scrollIntoView?.({ behavior: "smooth", block: "center" });
    nextRef.current?.focus({ preventScroll: true });
  }, [open, step]);

  // 매 프레임 위치를 다시 잰다 (스크롤·크기 변경·패널 접기를 따라가게). 바뀔 때만 상태를 갱신한다.
  useEffect(() => {
    if (!open) return;
    let raf = 0;
    let lastKey = "";
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const box = unionBox(targetsOf(step).map((e) => e.getBoundingClientRect()));
      const c = cardRef.current?.getBoundingClientRect();
      const hole = box && { left: box.left - PAD, top: box.top - PAD, width: box.width + PAD * 2, height: box.height + PAD * 2 };
      const card = placeCard(hole, { width: c?.width || 420, height: c?.height || 220 },
        { width: window.innerWidth, height: window.innerHeight });
      const key = JSON.stringify([hole, card].map((v) => v && Object.values(v).map((n) => (typeof n === "number" ? Math.round(n) : n))));
      if (key !== lastKey) {
        lastKey = key;
        setLayout({ box: hole, card });
      }
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [open, step]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") setIdx((i) => Math.min(i + 1, STEPS.length - 1));
      else if (e.key === "ArrowLeft") setIdx((i) => Math.max(i - 1, 0));
      else if (e.key === "Escape") setTour(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setTour]);

  if (!open) return null;
  const box = layout?.box ?? null;
  const card = layout?.card;
  return (
    <div className="tour" role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-text">
      <div className={`tour-block ${box ? "" : "dim"}`} />
      {box && <div className="tour-hole" style={{ left: box.left, top: box.top, width: box.width, height: box.height }} />}
      <div ref={cardRef} className={`tour-card side-${card?.side ?? "center"}`}
        style={card ? { left: card.left, top: card.top } : { visibility: "hidden" }}>
        <div className="tour-buddy"><CameraBuddy size={52} /></div>
        <div className="tour-bubble">
          <h2 id="tour-title">{step.title}</h2>
          <div id="tour-text" className="tour-text">{step.body}</div>
          <div className="tour-nav">
            <span className="muted small">{idx + 1} / {STEPS.length}</span>
            <button type="button" className="tour-skip" onClick={() => setTour(false)}>건너뛰기</button>
            {idx > 0 && <button type="button" onClick={() => setIdx(idx - 1)}>← 이전</button>}
            <button ref={nextRef} type="button" className="active"
              onClick={() => (last ? setTour(false) : setIdx(idx + 1))}>{last ? "시작하기" : "다음 →"}</button>
          </div>
        </div>
      </div>
    </div>
  );
}
