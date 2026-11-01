import { truncate } from "./truncate.ts";

export function sessionsPreview(text: string): string {
  return truncate(text, 14);
}
