import { newestFirst } from "./order.ts";

export function recentOrders(xs: { id: number; at: number }[]): number[] {
  return newestFirst(xs).map((x) => x.id);
}
