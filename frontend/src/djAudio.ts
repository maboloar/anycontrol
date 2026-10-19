// DJ 데모 소리: 음원 파일 없이 WebAudio 로 만든다. 덱 A = 드럼 루프, 덱 B = 베이스·신스 아르페지오.
// 크로스페이더(등전력) → 필터(가운데 = 원음, 왼쪽 = 저역 통과, 오른쪽 = 고역 통과) → 에코 → 출력.
export interface DjControls {
  playA: boolean; playB: boolean; volA: number; volB: number; cross: number; filter: number; echo: boolean; tempo: number;
  /** 채널 EQ: -1..1 → ±12dB (저음·고음) */
  lowA: number; highA: number; lowB: number; highB: number;
}
export const DEFAULT_DJ: DjControls = { playA: false, playB: false, volA: 0.9, volB: 0.8, cross: 0, filter: 0, echo: false, tempo: 124,
  lowA: 0, highA: 0, lowB: 0, highB: 0 };

const BASS = [45, 45, 41, 41, 48, 48, 43, 43];             // 마디마다 베이스 (MIDI)
const ARP = [0, 7, 12, 7, 3, 7, 10, 7];
const midi = (n: number) => 440 * 2 ** ((n - 69) / 12);

export class DjEngine {
  ctx: AudioContext;
  private gainA: GainNode; private gainB: GainNode;
  private srcA: GainNode; private srcB: GainNode;
  private eq: { lowA: BiquadFilterNode; highA: BiquadFilterNode; lowB: BiquadFilterNode; highB: BiquadFilterNode };
  /** 채널별 레벨 측정 (VU 미터·파형 화면) */
  analyserA: AnalyserNode; analyserB: AnalyserNode; analyserMaster: AnalyserNode; private filter: BiquadFilterNode; private wet: GainNode; private master: GainNode;
  private noise: AudioBuffer;
  private step = 0; private nextTime = 0; private timer: number | undefined;
  c: DjControls = { ...DEFAULT_DJ };
  /** 지금 울린 박자 (화면 표시용) */
  beat = 0;

  constructor() {
    const ctx = new AudioContext();
    this.ctx = ctx;
    this.master = ctx.createGain(); this.master.gain.value = 0.8;
    this.filter = ctx.createBiquadFilter(); this.filter.type = "allpass";
    const delay = ctx.createDelay(1); delay.delayTime.value = 0.375;
    const fb = ctx.createGain(); fb.gain.value = 0.42;
    this.wet = ctx.createGain(); this.wet.gain.value = 0;
    this.gainA = ctx.createGain(); this.gainB = ctx.createGain();
    // 소리 → (srcA/B) → 저음 셸프 → 고음 셸프 → 측정 → 채널 게인(볼륨·크로스페이더) → 필터
    this.srcA = ctx.createGain(); this.srcB = ctx.createGain();
    const shelf = (type: BiquadFilterType, f: number) => { const b = ctx.createBiquadFilter(); b.type = type; b.frequency.value = f; return b; };
    this.eq = { lowA: shelf("lowshelf", 220), highA: shelf("highshelf", 3200), lowB: shelf("lowshelf", 220), highB: shelf("highshelf", 3200) };
    this.analyserA = ctx.createAnalyser(); this.analyserB = ctx.createAnalyser(); this.analyserMaster = ctx.createAnalyser();
    for (const a of [this.analyserA, this.analyserB, this.analyserMaster]) { a.fftSize = 1024; a.smoothingTimeConstant = 0.6; }
    this.srcA.connect(this.eq.lowA); this.eq.lowA.connect(this.eq.highA); this.eq.highA.connect(this.analyserA); this.analyserA.connect(this.gainA);
    this.srcB.connect(this.eq.lowB); this.eq.lowB.connect(this.eq.highB); this.eq.highB.connect(this.analyserB); this.analyserB.connect(this.gainB);
    this.gainA.connect(this.filter); this.gainB.connect(this.filter);
    this.filter.connect(this.master);
    this.master.connect(this.analyserMaster);
    this.filter.connect(delay); delay.connect(fb); fb.connect(delay); delay.connect(this.wet); this.wet.connect(this.master);
    this.master.connect(ctx.destination);
    this.noise = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
    const d = this.noise.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  }

  start(): void {
    void this.ctx.resume();
    if (this.timer !== undefined) return;
    this.nextTime = this.ctx.currentTime + 0.05;
    this.timer = window.setInterval(() => this.schedule(), 25);
  }
  stop(): void { window.clearInterval(this.timer); this.timer = undefined; void this.ctx.close(); }

  set(c: DjControls): void {
    this.c = c;
    const t = this.ctx.currentTime;
    const x = (c.cross + 1) / 2;   // 0 = A 만, 1 = B 만 (등전력)
    this.gainA.gain.setTargetAtTime(c.volA * Math.cos(x * Math.PI / 2), t, 0.03);
    this.gainB.gain.setTargetAtTime(c.volB * Math.sin(x * Math.PI / 2), t, 0.03);
    const f = c.filter;
    if (Math.abs(f) < 0.06) this.filter.type = "allpass";
    else if (f < 0) { this.filter.type = "lowpass"; this.filter.frequency.setTargetAtTime(18000 * 10 ** (f * 2.2), t, 0.03); this.filter.Q.value = 6; }
    else { this.filter.type = "highpass"; this.filter.frequency.setTargetAtTime(30 * 10 ** (f * 2.4), t, 0.03); this.filter.Q.value = 6; }
    this.wet.gain.setTargetAtTime(c.echo ? 0.55 : 0, t, 0.05);
    this.eq.lowA.gain.setTargetAtTime(c.lowA * 12, t, 0.03); this.eq.highA.gain.setTargetAtTime(c.highA * 12, t, 0.03);
    this.eq.lowB.gain.setTargetAtTime(c.lowB * 12, t, 0.03); this.eq.highB.gain.setTargetAtTime(c.highB * 12, t, 0.03);
  }

  /** 채널 레벨 0..1 (RMS, 미터용으로 늘림). 채널 볼륨·크로스페이더를 반영한다. */
  level(deck: "A" | "B" | "M"): number {
    const a = deck === "A" ? this.analyserA : deck === "B" ? this.analyserB : this.analyserMaster;
    const buf = new Float32Array(a.fftSize);
    a.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) sum += v * v;
    const g = deck === "A" ? this.gainA.gain.value : deck === "B" ? this.gainB.gain.value : 1;
    return Math.min(1, Math.sqrt(sum / buf.length) * 3.2 * (deck === "M" ? 1 : Math.max(0.05, g)));
  }
  /** 파형 (시간 영역) */
  wave(deck: "A" | "B", out: Float32Array<ArrayBuffer>): void { (deck === "A" ? this.analyserA : this.analyserB).getFloatTimeDomainData(out); }

  private schedule(): void {
    const spb = 60 / this.c.tempo / 4;   // 16분음표
    while (this.nextTime < this.ctx.currentTime + 0.12) {
      const s = this.step % 16, bar = Math.floor(this.step / 16) % BASS.length, at = this.nextTime;
      // Original melodic-house loop: four-on-the-floor groove and an eight-bar chord progression.
      if (this.c.playA) {
        if (s % 4 === 0) this.kick(at);
        if (s === 4 || s === 12) this.snare(at);
        if (s % 2 === 0) this.hat(at, s % 4 === 2 ? 0.17 : 0.065);
        if (s === 3 || s === 11 || (bar % 4 === 3 && s === 15)) this.hat(at, .04);
      }
      if (this.c.playB) {
        if (s % 4 === 2) this.bass(at, midi(BASS[bar]!), spb * 1.65);
        if (s === 0 || s === 8) this.chord(at, midi(BASS[bar]! + 12), spb * 5.5, bar >= 2);
        if (s % 2 === 1) this.pluck(at, midi(BASS[bar]! + 24 + (ARP[(s >> 1) % ARP.length] === 3 && bar >= 2 ? 4 : ARP[(s >> 1) % ARP.length]!)), spb * 1.6);
      }
      if (s % 4 === 0) this.beat = this.step >> 2;
      this.step++; this.nextTime += spb;
    }
  }
  private env(g: GainNode, at: number, peak: number, decay: number) {
    g.gain.setValueAtTime(0.0001, at); g.gain.exponentialRampToValueAtTime(peak, at + 0.005); g.gain.exponentialRampToValueAtTime(0.0001, at + decay);
  }
  private kick(at: number) {
    const o = this.ctx.createOscillator(), g = this.ctx.createGain();
    o.frequency.setValueAtTime(150, at); o.frequency.exponentialRampToValueAtTime(42, at + 0.18);
    this.env(g, at, 1, 0.32); o.connect(g); g.connect(this.srcA); o.start(at); o.stop(at + 0.35);
  }
  private noiseHit(at: number, dest: AudioNode, type: BiquadFilterType, freq: number, peak: number, decay: number) {
    const n = this.ctx.createBufferSource(); n.buffer = this.noise;
    const f = this.ctx.createBiquadFilter(); f.type = type; f.frequency.value = freq;
    const g = this.ctx.createGain(); this.env(g, at, peak, decay);
    n.connect(f); f.connect(g); g.connect(dest); n.start(at, Math.random() * 0.5); n.stop(at + decay + 0.02);
  }
  private snare(at: number) { this.noiseHit(at, this.srcA, "bandpass", 1800, 0.6, 0.18); }
  private hat(at: number, v: number) { this.noiseHit(at, this.srcA, "highpass", 7000, v, 0.05); }
  private bass(at: number, f: number, dur: number) {
    const o = this.ctx.createOscillator(), lp = this.ctx.createBiquadFilter(), g = this.ctx.createGain();
    o.type = "sawtooth"; o.frequency.value = f; lp.type = "lowpass"; lp.frequency.setValueAtTime(900, at); lp.frequency.exponentialRampToValueAtTime(160, at + dur);
    this.env(g, at, 0.24, dur); o.connect(lp); lp.connect(g); g.connect(this.srcB); o.start(at); o.stop(at + dur + 0.05);
  }
  private pluck(at: number, f: number, dur: number) {
    const o = this.ctx.createOscillator(), g = this.ctx.createGain();
    o.type = "sine"; o.frequency.value = f; this.env(g, at, 0.065, dur); o.connect(g); g.connect(this.srcB); o.start(at); o.stop(at + dur + 0.05);
  }
  private chord(at: number, root: number, dur: number, bright: boolean): void {
    for (const interval of [0, bright ? 4 : 3, 7, 12]) {
      const o = this.ctx.createOscillator(), g = this.ctx.createGain();
      o.type = "triangle"; o.frequency.value = root * 2 ** (interval / 12);
      g.gain.setValueAtTime(.0001, at); g.gain.exponentialRampToValueAtTime(.027, at + .035);
      g.gain.exponentialRampToValueAtTime(.0001, at + dur);
      o.connect(g); g.connect(this.srcB); o.start(at); o.stop(at + dur + .03);
    }
  }
  /** 짧은 클랩: 겹친 잡음 타격과 낮은 잔향. 기존 dj.horn 잭 호환은 유지한다. */
  clap(): void {
    const at = this.ctx.currentTime;
    [0, .018, .036, .064].forEach((delay, i) => {
      const start = at + delay, n = this.ctx.createBufferSource(); n.buffer = this.noise;
      const f = this.ctx.createBiquadFilter(); f.type = "bandpass"; f.frequency.value = 1800; f.Q.value = .65;
      const g = this.ctx.createGain(), duration = i === 3 ? .16 : .035;
      g.gain.setValueAtTime(.0001, start); g.gain.exponentialRampToValueAtTime(i === 3 ? .09 : .14, start + .002);
      g.gain.exponentialRampToValueAtTime(.0001, start + duration);
      n.connect(f); f.connect(g); g.connect(this.master); n.start(start); n.stop(start + duration + .01);
    });
  }
  /** 스크래치: 띠 잡음의 음높이를 앞뒤로 흔든다 */
  scratch(): void {
    const at = this.ctx.currentTime;
    const n = this.ctx.createBufferSource(); n.buffer = this.noise;
    const f = this.ctx.createBiquadFilter(); f.type = "bandpass"; f.Q.value = 4;
    [800, 2600, 700, 2200, 900].forEach((v, i) => f.frequency.linearRampToValueAtTime(v, at + i * 0.06));
    const g = this.ctx.createGain(); g.gain.setValueAtTime(0.5, at); g.gain.exponentialRampToValueAtTime(0.0001, at + 0.3);
    n.connect(f); f.connect(g); g.connect(this.master); n.start(at); n.stop(at + 0.32);
  }
}
