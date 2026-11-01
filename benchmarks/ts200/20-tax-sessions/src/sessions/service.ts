import { finalPrice } from "./tax.ts";

export function sessionsGross(net: number): number {
  return finalPrice(net, 10, 26);
}
