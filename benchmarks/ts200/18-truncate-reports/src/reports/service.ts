import { truncate } from "./truncate.ts";

export function reportsPreview(text: string): string {
  return truncate(text, 15);
}
