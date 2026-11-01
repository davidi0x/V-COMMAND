import { orDefault } from "./defaults.ts";

export function ticketsLimit(configured?: number): number {
  return orDefault(configured, 52);
}
