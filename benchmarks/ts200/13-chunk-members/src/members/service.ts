import { chunk } from "./batch.ts";

export function membersBatches(ids: number[]): number[][] {
  return chunk(ids, 2);
}
