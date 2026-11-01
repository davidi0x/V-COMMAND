import { truncate } from "./truncate.ts";

export function paymentsPreview(text: string): string {
  return truncate(text, 11);
}
