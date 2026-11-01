import { finalPrice } from "./tax.ts";

export function invoicesGross(net: number): number {
  return finalPrice(net, 10, 21);
}
