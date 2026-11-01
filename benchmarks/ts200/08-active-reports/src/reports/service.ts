import { onlyActive } from "./filters.ts";

export function activeReportCount(xs: { active: boolean }[]): number {
  return onlyActive(xs).length;
}
