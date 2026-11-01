import { orDefault } from "./defaults.ts";

export function shipmentsLimit(configured?: number): number {
  return orDefault(configured, 54);
}
