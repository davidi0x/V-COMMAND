import { truncate } from "./truncate.ts";

export function productsPreview(text: string): string {
  return truncate(text, 13);
}
