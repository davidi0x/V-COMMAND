import { finalPrice } from "./tax.ts";

export function couponsGross(net: number): number {
  return finalPrice(net, 10, 28);
}
