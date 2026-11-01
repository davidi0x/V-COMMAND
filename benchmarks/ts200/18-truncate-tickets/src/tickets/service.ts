import { truncate } from "./truncate.ts";

export function ticketsPreview(text: string): string {
  return truncate(text, 10);
}
