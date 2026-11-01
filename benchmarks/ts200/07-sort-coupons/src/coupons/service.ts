import { newestFirst } from "./order.ts";

export function recentCoupons(xs: { id: number; at: number }[]): number[] {
  return newestFirst(xs).map((x) => x.id);
}
