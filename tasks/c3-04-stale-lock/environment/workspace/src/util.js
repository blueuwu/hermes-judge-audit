// Small helpers shared by every module.
export const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
export const fmt = (cents) => (cents / 100).toFixed(2);
