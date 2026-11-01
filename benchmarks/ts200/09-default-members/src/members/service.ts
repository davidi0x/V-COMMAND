import { orDefault } from "./defaults.ts";

export function membersLimit(configured?: number): number {
  return orDefault(configured, 59);
}
