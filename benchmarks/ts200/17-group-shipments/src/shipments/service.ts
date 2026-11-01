import { countBy } from "./group.ts";

export function shipmentsPerCategory(xs: { id: string; category: string }[]): Record<string, number> {
  return countBy(xs);
}
