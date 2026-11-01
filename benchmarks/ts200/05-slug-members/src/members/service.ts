import { slug } from "./text.ts";

export function membersUrl(title: string, id: number): string {
  return `/members/${id}-${slug(title)}`;
}
