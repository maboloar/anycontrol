import { useEffect, useState } from "react";

const PALETTE: Record<string, string> = {
  B: "#6ea8fe", // 머리 (단색)
  S: "#3f5f9e", // 받침
  K: "#1b1f27", // 렌즈
  W: "#ffffff", // 렌즈 반짝임
  R: "#ff4d6d", // 녹화 불빛
};

/** 11×12 단색 픽셀 웹캠: 동그란 머리 한가운데 큰 렌즈 눈, 위 녹화 불빛, 목과 받침. 한 글자 = 한 픽셀 ('.' = 투명) */
const BODY = [
  "...BBBBB...",
  "..BBBBBRB..",
  ".BBBKKKBBB.",
  ".BBKWKKKBB.",
  ".BBKKKKKBB.",
  ".BBKKKKKBB.",
  ".BBBKKKBBB.",
  "..BBBBBBB..",
  "...BBBBB...",
  ".....S.....",
  "....SSS....",
  "..SSSSSSS..",
];
/** 이 줄부터는 받침 (머리만 두리번거린다) */
const STAND_FROM = 9;

/** 눈 깜박임 = 셔터가 닫히듯 렌즈가 가운데 한 줄만 남는다 */
const BLINK: Record<number, string> = {
  2: ".BBBBBBBBB.",
  3: ".BBBBBBBBB.",
  5: ".BBBBBBBBB.",
  6: ".BBBBBBBBB.",
};

export const BUDDY_W = BODY[0]!.length;
export const BUDDY_H = BODY.length;

export function buddyPixels(blink: boolean): { x: number; y: number; c: string }[] {
  const out: { x: number; y: number; c: string }[] = [];
  BODY.forEach((row, y) => {
    [...((blink && BLINK[y]) || row)].forEach((ch, x) => {
      if (ch !== ".") out.push({ x, y, c: PALETTE[ch]! });
    });
  });
  return out;
}

/** 튜토리얼 캐릭터: 아주 단순한 픽셀 웹캠. 머리를 좌우로 두리번거리고, 가끔 깜박이고, 녹화 불빛이 켜졌다 꺼진다. */
export function CameraBuddy({ size = 44, blinkMin = 2500, blinkMax = 5000, wink = 0 }: {
  size?: number;
  /** 혼자 깜박이는 간격 (ms, 이 사이 무작위) */
  blinkMin?: number;
  blinkMax?: number;
  /** 값이 바뀔 때마다 바로 두 번 깜박인다 (클릭 반응용) */
  wink?: number;
}) {
  const [blink, setBlink] = useState(false);
  useEffect(() => {
    let t = 0;
    const loop = () => {
      t = window.setTimeout(() => {
        setBlink(true);
        t = window.setTimeout(() => { setBlink(false); loop(); }, 150);
      }, blinkMin + Math.random() * (blinkMax - blinkMin));
    };
    loop();
    return () => window.clearTimeout(t);
  }, [blinkMin, blinkMax]);
  useEffect(() => {
    if (!wink) return;
    const ts = [0, 160, 320, 480].map((d, i) => window.setTimeout(() => setBlink(i % 2 === 0), d));
    return () => ts.forEach((t) => window.clearTimeout(t));
  }, [wink]);
  const px = buddyPixels(blink);
  const rect = ({ x, y, c }: { x: number; y: number; c: string }) => (
    <rect key={`${x},${y}`} x={x} y={y} width={1.02} height={1.02} fill={c}
      className={c === PALETTE.R ? "buddy-rec" : undefined} />
  );
  return (
    <svg className="buddy" viewBox={`-1 0 ${BUDDY_W + 2} ${BUDDY_H}`} width={size} height={(size * BUDDY_H) / (BUDDY_W + 2)}
      shapeRendering="crispEdges" aria-hidden="true">
      <g className="buddy-head">{px.filter((p) => p.y < STAND_FROM).map(rect)}</g>
      {px.filter((p) => p.y >= STAND_FROM).map(rect)}
    </svg>
  );
}

/** 상단 제목 옆 작은 캐릭터. 가끔 혼자 깜박이고, 누르면 통통 뛰며 두리번거린다. */
export function HeaderBuddy() {
  const [play, setPlay] = useState(0);
  useEffect(() => {
    if (!play) return;
    const t = window.setTimeout(() => setPlay(0), 1300);
    return () => window.clearTimeout(t);
  }, [play]);
  return (
    <button type="button" className={`header-buddy ${play ? "playing" : ""}`}
      aria-label="AnyControl 캐릭터 (누르면 인사합니다)" title="안녕하세요!"
      onClick={() => {
        // 재생 중에 다시 누르면 처음부터 (클래스를 한 프레임 뗐다 붙인다. 버튼은 그대로라 포커스 유지)
        setPlay(0);
        requestAnimationFrame(() => setPlay(Date.now()));
      }}>
      <CameraBuddy size={22} blinkMin={3000} blinkMax={8000} wink={play} />
    </button>
  );
}
