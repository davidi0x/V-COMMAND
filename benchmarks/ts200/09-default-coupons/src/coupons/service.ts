import { orDefault } from "./defaults.ts";

export function couponsLimit(configured?: number): number {
  return orDefault(configured, 58);
}
