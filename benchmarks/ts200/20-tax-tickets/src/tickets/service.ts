import { finalPrice } from "./tax.ts";

export function ticketsGross(net: number): number {
  return finalPrice(net, 10, 22);
}
