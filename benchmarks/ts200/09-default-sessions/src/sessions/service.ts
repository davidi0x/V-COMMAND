import { orDefault } from "./defaults.ts";

export function sessionsLimit(configured?: number): number {
  return orDefault(configured, 56);
}
