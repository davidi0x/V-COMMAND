export function finalPrice(net: number, discountPct: number, taxPct: number): number {
  const taxed = net * (1 + taxPct / 100);
  return Math.round((taxed - net * discountPct / 100) * 100) / 100;
}
