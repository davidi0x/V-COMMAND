import { chunk } from "./batch.ts";

export function ticketsBatches(ids: number[]): number[][] {
  return chunk(ids, 4);
}
