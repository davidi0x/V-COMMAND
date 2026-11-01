import { onlyActive } from "./filters.ts";

export function activeSessionCount(xs: { active: boolean }[]): number {
  return onlyActive(xs).length;
}
