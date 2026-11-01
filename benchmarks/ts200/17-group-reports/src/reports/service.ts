import { countBy } from "./group.ts";

export function reportsPerCategory(xs: { id: string; category: string }[]): Record<string, number> {
  return countBy(xs);
}
