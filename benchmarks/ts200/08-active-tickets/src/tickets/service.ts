import { onlyActive } from "./filters.ts";

export function activeTicketCount(xs: { active: boolean }[]): number {
  return onlyActive(xs).length;
}
