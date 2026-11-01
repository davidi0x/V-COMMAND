import { ratio } from "./ratio.ts";

export function membersConversionRate(won: number, seen: number): number {
  return ratio(won, seen);
}
