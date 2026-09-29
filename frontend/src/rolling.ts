/** 최근 N개 값의 분위수 (브라우저 쪽 지연 측정용). */
export class Rolling {
  private buf: number[] = [];
  constructor(private readonly size = 120) {}

  add(v: number): void {
    if (!Number.isFinite(v)) return;
    this.buf.push(v);
    if (this.buf.length > this.size) this.buf.shift();
  }

  get length(): number {
    return this.buf.length;
  }

  quantile(q: number): number | null {
    if (this.buf.length === 0) return null;
    const s = [...this.buf].sort((a, b) => a - b);
    // numpy 기본(linear) 과 같은 보간
    const pos = (s.length - 1) * Math.min(Math.max(q, 0), 1);
    const lo = Math.floor(pos);
    const hi = Math.ceil(pos);
    return s[lo]! + (s[hi]! - s[lo]!) * (pos - lo);
  }
}
