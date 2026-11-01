import { truncate } from "./truncate.ts";

export function ordersPreview(text: string): string {
  return truncate(text, 8);
}
