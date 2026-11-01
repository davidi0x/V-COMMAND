import { chunk } from "./batch.ts";

export function reportsBatches(ids: number[]): number[][] {
  return chunk(ids, 3);
}
