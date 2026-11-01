import { lineTotal } from "./pricing.ts";

export interface OrderLine { price: number; quantity: number }

export function ordersTotal(lines: OrderLine[]): number {
  return lines.reduce((sum, l) => sum + lineTotal(l.price, l.quantity), 0);
}
