/** Logical gameplay coordinates stay fixed; backing pixels follow CSS size and display density. */
export function gameCanvas(canvas: HTMLCanvasElement | null, width: number, height: number): CanvasRenderingContext2D | null {
  if (!canvas) return null;
  const css = canvas.getBoundingClientRect().width || width;
  const dpr = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
  const scale = Math.min(Math.max(1, css * dpr / width), Math.sqrt(4_000_000 / (width * height)));
  const w = Math.round(width * scale), h = Math.round(height * scale);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const ratio = `${width} / ${height}`;
  if (canvas.style.aspectRatio !== ratio) canvas.style.aspectRatio = ratio;
  const g = canvas.getContext("2d");
  if (g) { g.setTransform(w / width, 0, 0, h / height, 0, 0); g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high"; }
  return g;
}
