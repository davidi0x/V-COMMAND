import { lineTotal } from "./pricing.ts";

export interface SessionLine { price: number; quantity: number }

export function sessionsTotal(lines: SessionLine[]): number {
  return lines.reduce((sum, l) => sum + lineTotal(l.price, l.quantity), 0);
}
