import { lineTotal } from "./pricing.ts";

export interface ShipmentLine { price: number; quantity: number }

export function shipmentsTotal(lines: ShipmentLine[]): number {
  return lines.reduce((sum, l) => sum + lineTotal(l.price, l.quantity), 0);
}
