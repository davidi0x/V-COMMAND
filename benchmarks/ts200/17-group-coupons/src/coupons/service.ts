import { countBy } from "./group.ts";

export function couponsPerCategory(xs: { id: string; category: string }[]): Record<string, number> {
  return countBy(xs);
}
