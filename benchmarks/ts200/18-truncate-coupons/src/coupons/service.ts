import { truncate } from "./truncate.ts";

export function couponsPreview(text: string): string {
  return truncate(text, 16);
}
