// Server calls; depends on state.
import { cart } from "./state.js";
export async function checkout() {
  return fetch("/api/checkout", { method: "POST", body: JSON.stringify([...cart]) });
}
