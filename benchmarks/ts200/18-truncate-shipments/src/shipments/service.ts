import { truncate } from "./truncate.ts";

export function shipmentsPreview(text: string): string {
  return truncate(text, 12);
}
