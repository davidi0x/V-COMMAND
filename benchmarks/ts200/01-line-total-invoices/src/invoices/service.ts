import { lineTotal } from "./pricing.ts";

export interface InvoiceLine { price: number; quantity: number }

export function invoicesTotal(lines: InvoiceLine[]): number {
  return lines.reduce((sum, l) => sum + lineTotal(l.price, l.quantity), 0);
}
