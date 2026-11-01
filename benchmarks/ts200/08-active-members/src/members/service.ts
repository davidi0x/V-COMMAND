import { onlyActive } from "./filters.ts";

export function activeMemberCount(xs: { active: boolean }[]): number {
  return onlyActive(xs).length;
}
