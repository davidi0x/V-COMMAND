import { lineTotal } from "./pricing.ts";

export interface MemberLine { price: number; quantity: number }

export function membersTotal(lines: MemberLine[]): number {
  return lines.reduce((sum, l) => sum + lineTotal(l.price, l.quantity), 0);
}
