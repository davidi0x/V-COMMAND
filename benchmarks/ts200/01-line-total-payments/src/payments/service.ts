import { lineTotal } from "./pricing.ts";

export interface PaymentLine { price: number; quantity: number }

export function paymentsTotal(lines: PaymentLine[]): number {
  return lines.reduce((sum, l) => sum + lineTotal(l.price, l.quantity), 0);
}
