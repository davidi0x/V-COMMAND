import { truncate } from "./truncate.ts";

export function membersPreview(text: string): string {
  return truncate(text, 17);
}
