// Entry point; loaded last.
import { setQty } from "./state.js";
import { checkout } from "./api.js";
window.shop = { setQty, checkout };
