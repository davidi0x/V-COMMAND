import { finalPrice } from "./tax.ts";

export function productsGross(net: number): number {
  return finalPrice(net, 10, 25);
}
