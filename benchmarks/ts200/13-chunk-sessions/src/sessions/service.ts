import { chunk } from "./batch.ts";

export function sessionsBatches(ids: number[]): number[][] {
  return chunk(ids, 2);
}
