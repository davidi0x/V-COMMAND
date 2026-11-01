import { finalPrice } from "./tax.ts";

export function reportsGross(net: number): number {
  return finalPrice(net, 10, 27);
}
