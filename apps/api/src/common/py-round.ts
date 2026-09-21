/**
 * CPython's `round(x, 2)`, exactly.
 *
 * Python rounds half-to-even against the double's TRUE binary value, not
 * against its printed decimal form. Those differ often enough to matter:
 * `round(2.675, 2)` is `2.67`, because the nearest double to 2.675 is
 * 2.67499999999999982236431605997495353221893310546875 — below the midpoint.
 * A scale-by-100-and-compare implementation reads that as a tie and returns
 * 2.68, which is a silent one-paisa error in a financial snapshot.
 *
 * So the decision is made in exact integer arithmetic. A double is exactly
 * `mant * 2^exp` for integers mant and exp, so `x * 100` is exactly
 * `(mant * 100) * 2^exp`, and rounding that to an integer is an exact BigInt
 * division with a remainder comparison. No floating point is involved until
 * the final divide by 100, which is a single correctly-rounded operation and
 * therefore lands on the same double Python produces.
 */
export function pyRound2(x: number): number {
  if (!Number.isFinite(x) || x === 0) return x;

  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const hi = view.getUint32(0);
  const lo = view.getUint32(4);

  const negative = (hi >>> 31) === 1;
  const expBits = (hi >>> 20) & 0x7ff;
  let mant = (BigInt(hi & 0xf_ffff) << 32n) | BigInt(lo);
  let exp: number;
  if (expBits === 0) {
    exp = -1074; // subnormal: no implicit leading bit
  } else {
    mant |= 1n << 52n; // restore the implicit bit
    exp = expBits - 1075;
  }

  // |x| * 100 == scaled * 2^exp, exactly.
  const scaled = mant * 100n;
  let q: bigint;
  if (exp >= 0) {
    q = scaled << BigInt(exp); // already an integer
  } else {
    const divisor = 1n << BigInt(-exp);
    q = scaled / divisor;
    const twiceRemainder = (scaled % divisor) * 2n;
    // half-to-even: round up when past the midpoint, or exactly at it and odd
    if (twiceRemainder > divisor || (twiceRemainder === divisor && (q & 1n) === 1n)) {
      q += 1n;
    }
  }

  // Money in this domain stays far below 2^53 paisa; Number() is exact here.
  const magnitude = Number(q) / 100;
  return negative ? -magnitude : magnitude;
}
