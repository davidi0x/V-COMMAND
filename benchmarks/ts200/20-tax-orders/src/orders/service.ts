import { finalPrice } from "./tax.ts";

export function ordersGross(net: number): number {
  return finalPrice(net, 10, 20);
}
