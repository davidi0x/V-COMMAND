import { orDefault } from "./defaults.ts";

export function invoicesLimit(configured?: number): number {
  return orDefault(configured, 51);
}
