import { orDefault } from "./defaults.ts";

export function productsLimit(configured?: number): number {
  return orDefault(configured, 55);
}
