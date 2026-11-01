import { lineTotal } from "./pricing.ts";

export interface ProductLine { price: number; quantity: number }

export function productsTotal(lines: ProductLine[]): number {
  return lines.reduce((sum, l) => sum + lineTotal(l.price, l.quantity), 0);
}
