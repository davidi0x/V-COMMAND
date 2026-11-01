import { countBy } from "./group.ts";

export function invoicesPerCategory(xs: { id: string; category: string }[]): Record<string, number> {
  return countBy(xs);
}
