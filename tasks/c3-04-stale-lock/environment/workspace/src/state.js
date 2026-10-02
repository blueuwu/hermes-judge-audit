// Cart state; depends on util.
import { clamp } from "./util.js";
export const cart = new Map();
export function setQty(sku, qty) { cart.set(sku, clamp(qty, 0, 99)); }
