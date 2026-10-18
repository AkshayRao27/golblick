/**
 * The coast after a drag is let go: how far and how long, from how fast.
 *
 * A port of the desktop viewer's model (src/golblick/fling.py in the library),
 * with the same constants, so a flick feels the same in both. It is Android's
 * fling model (OverScroller in the Android Open Source Project, Apache-2.0):
 * the coast grows as speed to the power D/(D-1), about 1.74, so a slow drag
 * barely carries on and a quick flick keeps turning. fling.py explains the
 * formulas.
 */

/** Android's DECELERATION_RATE, ln 0.78 / ln 0.9. */
const DECELERATION = Math.log(0.78) / Math.log(0.9);
/** Android's INFLEXION. */
const INFLEXION = 0.35;
/** 1.5 times Android's default scroll friction, as in fling.py. */
const FRICTION = 0.0225;
/** Faster releases are treated as this fast, in pixels a second. */
const MAX_SPEED = 3000;
/** Below this a release is a stop, not a fling. */
const MIN_SPEED = 250;
/** How much of the drag's end the release speed is read from, in seconds. */
const WINDOW = 0.08;
/** CSS pixels are 96 to the inch. */
const DPI = 96;

/** Android's physical deceleration, in pixels a second squared. */
const deceleration = 9.80665 * 39.37 * DPI * 0.84;

/** Pixels a second in x and y, from [seconds, x, y] pointer samples ending at the release. */
export function releaseVelocity(samples: Array<[number, number, number]>): [number, number] {
  if (samples.length === 0) return [0, 0];
  const end = samples[samples.length - 1][0];
  const recent = samples.filter((s) => end - s[0] <= WINDOW);
  if (recent.length < 2) return [0, 0];
  const meanT = recent.reduce((sum, s) => sum + s[0], 0) / recent.length;
  const spread = recent.reduce((sum, s) => sum + (s[0] - meanT) ** 2, 0);
  if (spread <= 0) return [0, 0];
  const slope = (axis: 1 | 2) => {
    const mean = recent.reduce((sum, s) => sum + s[axis], 0) / recent.length;
    return recent.reduce((sum, s) => sum + (s[0] - meanT) * (s[axis] - mean), 0) / spread;
  };
  return [slope(1), slope(2)];
}

/** One coast along a straight line, in pixels; offset(t) is how far it has gone at t seconds. */
export class Fling {
  readonly distance: number;
  readonly duration: number;
  private readonly direction: [number, number];

  constructor(vx: number, vy: number) {
    // Only the main direction carries on, so a sideways flick doesn't tip the horizon.
    if (Math.abs(vx) >= Math.abs(vy)) vy = 0;
    else vx = 0;
    const speed = Math.min(Math.hypot(vx, vy), MAX_SPEED);
    this.direction = [Math.sign(vx), Math.sign(vy)];
    if (speed < MIN_SPEED) {
      this.distance = 0;
      this.duration = 0;
      return;
    }
    const k = FRICTION * deceleration;
    const r = Math.log((INFLEXION * speed) / k);
    this.duration = Math.exp(r / (DECELERATION - 1));
    this.distance = k * Math.exp((DECELERATION / (DECELERATION - 1)) * r);
  }

  offset(t: number): [number, number] {
    if (this.duration <= 0) return [0, 0];
    const share = 1 - (1 - Math.min(t, this.duration) / this.duration) ** (1 / INFLEXION);
    return [this.direction[0] * this.distance * share, this.direction[1] * this.distance * share];
  }

  done(t: number): boolean {
    return t >= this.duration;
  }
}
