import { truncate } from "./truncate.ts";

export function invoicesPreview(text: string): string {
  return truncate(text, 9);
}
