import { countBy } from "./group.ts";

export function paymentsPerCategory(xs: { id: string; category: string }[]): Record<string, number> {
  return countBy(xs);
}
