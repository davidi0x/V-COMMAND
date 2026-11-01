export interface Line { sku: string; price: number; quantity: number }

export function total(lines: Line[]): number {
  return lines.reduce((sum, line) => sum + line.price, 0);
}

export function count(lines: Line[]): number {
  return lines.reduce((n, line) => n + line.quantity, 0);
}
