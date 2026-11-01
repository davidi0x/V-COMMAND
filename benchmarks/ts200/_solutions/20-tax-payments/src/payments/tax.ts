export function finalPrice(net: number, discountPct: number, taxPct: number): number {
  const discounted = net * (1 - discountPct / 100);
  return Math.round(discounted * (1 + taxPct / 100) * 100) / 100;
}
