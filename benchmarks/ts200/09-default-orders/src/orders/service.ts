import { orDefault } from "./defaults.ts";

export function ordersLimit(configured?: number): number {
  return orDefault(configured, 50);
}
