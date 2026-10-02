// Rendering; depends on util and state.
import { fmt } from "./util.js";
import { cart } from "./state.js";
export function total(prices) {
  let t = 0;
  for (const [sku, qty] of cart) t += (prices[sku] ?? 0) * qty;
  return fmt(t);
}
