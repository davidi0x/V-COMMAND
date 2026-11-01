import { finalPrice } from "./tax.ts";

export function shipmentsGross(net: number): number {
  return finalPrice(net, 10, 24);
}
