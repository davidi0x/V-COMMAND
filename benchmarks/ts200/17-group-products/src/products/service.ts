import { countBy } from "./group.ts";

export function productsPerCategory(xs: { id: string; category: string }[]): Record<string, number> {
  return countBy(xs);
}
