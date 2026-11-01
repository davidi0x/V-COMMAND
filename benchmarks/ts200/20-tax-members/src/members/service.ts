import { finalPrice } from "./tax.ts";

export function membersGross(net: number): number {
  return finalPrice(net, 10, 29);
}
