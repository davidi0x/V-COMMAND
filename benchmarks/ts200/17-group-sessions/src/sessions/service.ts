import { countBy } from "./group.ts";

export function sessionsPerCategory(xs: { id: string; category: string }[]): Record<string, number> {
  return countBy(xs);
}
