import { orDefault } from "./defaults.ts";

export function paymentsLimit(configured?: number): number {
  return orDefault(configured, 53);
}
