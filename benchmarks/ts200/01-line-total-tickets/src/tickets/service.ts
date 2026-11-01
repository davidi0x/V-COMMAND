import { lineTotal } from "./pricing.ts";

export interface TicketLine { price: number; quantity: number }

export function ticketsTotal(lines: TicketLine[]): number {
  return lines.reduce((sum, l) => sum + lineTotal(l.price, l.quantity), 0);
}
