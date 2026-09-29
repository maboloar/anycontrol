export type Stroke = [number, number][];

/** 카메라의 검지 좌표를 고정된 영역에 표시한다. 획이 늘어나도 그림이 확대·이동하지 않는다. */
export function mapHandStrokes(strokes: Stroke[], w: number, h: number, pad: number, aspect: number, invertY = false, mirrorX = false): Stroke[] {
  const width = Math.min(w - 2 * pad, (h - 2 * pad) * aspect);
  const height = width / aspect;
  const ox = (w - width) / 2, oy = (h - height) / 2;
  return strokes.map((stroke) => stroke.map(([x, y]) =>
    [ox + (mirrorX ? 1 - x : x) * width, oy + (invertY ? 1 - y : y) * height] as [number, number]));
}

/**
 * 책상 좌표(X 오른쪽, Z 카메라에서 먼 쪽)의 획들을 캔버스에 맞춘다.
 * 가로·세로 같은 배율(모양 보존), Z 가 클수록(멀수록) 캔버스 위쪽.
 */
export function fitStrokes(strokes: Stroke[], w: number, h: number, pad: number, nearUp = false): Stroke[] {
  const pts = strokes.flat();
  if (pts.length === 0) return [];
  let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
  for (const [x, z] of pts) {
    if (x < x0) x0 = x;
    if (x > x1) x1 = x;
    if (z < z0) z0 = z;
    if (z > z1) z1 = z;
  }
  const sx = x1 - x0 || 1e-9;
  const sz = z1 - z0 || 1e-9;
  const k = Math.min((w - 2 * pad) / sx, (h - 2 * pad) / sz);
  const ox = (w - sx * k) / 2;
  const oy = (h - sz * k) / 2;
  return strokes.map((s) => s.map(([x, z]) => [ox + (x - x0) * k,
    nearUp ? oy + (z - z0) * k : h - (oy + (z - z0) * k)] as [number, number]));
}

/** 획만으로 배율을 정하므로 떠 있는 펜촉을 움직여도 그림 크기가 변하지 않는다. */
export function drawingView(strokes: Stroke[], anchor: [number, number], w: number, h: number, nearUp: boolean, mirror: boolean) {
  let x0 = anchor[0] - .5, x1 = anchor[0] + .5, y0 = anchor[1] - .5, y1 = anchor[1] + .5;
  if (strokes.some(s => s.length)) {
    x0 = y0 = Infinity; x1 = y1 = -Infinity;
    for (const stroke of strokes) for (const [x, y] of stroke) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const dx = Math.max(x1 - x0, .3), dy = Math.max(y1 - y0, .3);
    x0 = cx - dx / 2; x1 = cx + dx / 2; y0 = cy - dy / 2; y1 = cy + dy / 2;
  }
  const k = Math.min((w - 48) / (x1 - x0), (h - 48) / (y1 - y0));
  return ([x, y]: [number, number]): [number, number] => {
    const px = w / 2 + (x - (x0 + x1) / 2) * k;
    return [mirror ? w - px : px, h / 2 + (y - (y0 + y1) / 2) * k * (nearUp ? 1 : -1)];
  };
}
