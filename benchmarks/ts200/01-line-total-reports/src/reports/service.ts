import { lineTotal } from "./pricing.ts";

export interface ReportLine { price: number; quantity: number }

export function reportsTotal(lines: ReportLine[]): number {
  return lines.reduce((sum, l) => sum + lineTotal(l.price, l.quantity), 0);
}
