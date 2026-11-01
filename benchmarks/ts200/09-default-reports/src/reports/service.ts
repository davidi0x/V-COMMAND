import { orDefault } from "./defaults.ts";

export function reportsLimit(configured?: number): number {
  return orDefault(configured, 57);
}
