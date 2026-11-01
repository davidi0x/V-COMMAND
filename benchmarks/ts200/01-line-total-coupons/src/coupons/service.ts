import { lineTotal } from "./pricing.ts";

export interface CouponLine { price: number; quantity: number }

export function couponsTotal(lines: CouponLine[]): number {
  return lines.reduce((sum, l) => sum + lineTotal(l.price, l.quantity), 0);
}
