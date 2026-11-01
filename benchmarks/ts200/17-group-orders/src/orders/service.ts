import { countBy } from "./group.ts";

export function ordersPerCategory(xs: { id: string; category: string }[]): Record<string, number> {
  return countBy(xs);
}
