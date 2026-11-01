import { countBy } from "./group.ts";

export function membersPerCategory(xs: { id: string; category: string }[]): Record<string, number> {
  return countBy(xs);
}
