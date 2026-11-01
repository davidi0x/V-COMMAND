import { countBy } from "./group.ts";

export function ticketsPerCategory(xs: { id: string; category: string }[]): Record<string, number> {
  return countBy(xs);
}
