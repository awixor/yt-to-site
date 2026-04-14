/**
 * URL slug generation for yt-to-site.
 *
 * SYNC WARNING: Must stay in sync with yt_to_site/slug.py
 */

export function generateSlug(text: string | null | undefined, maxLength = 50): string {
  if (!text) return "";

  let slug = text.substring(0, maxLength + 1);
  slug = slug.toLowerCase().trim();

  // Remove diacritics
  slug = slug.normalize("NFD").replace(/[\u0300-\u036f]/g, "");

  // Keep only word chars, spaces, hyphens
  slug = slug.replace(/[^\w\s-]/g, "");

  // Replace whitespace with hyphens
  slug = slug.replace(/\s+/g, "-");

  // Collapse multiple hyphens
  slug = slug.replace(/-+/g, "-");

  // Remove trailing hyphen
  slug = slug.replace(/-$/, "");

  return slug;
}

export function slugifyHeading(text: string): string {
  let slug = text
    .normalize("NFD")
    .replace(/[\u0300-\u036f\u064B-\u065F\u0670]/g, "")
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  return slug || "heading";
}

export function extractHeadings(markdown: string): { id: string; text: string; level: number }[] {
  const headings: { id: string; text: string; level: number }[] = [];
  const counts = new Map<string, number>();
  const regex = /^(#{2,3})\s+(.+)$/gm;
  let match;

  while ((match = regex.exec(markdown)) !== null) {
    const level = match[1].length;
    const text = match[2].trim();
    let id = slugifyHeading(text);
    const count = counts.get(id) || 0;
    counts.set(id, count + 1);
    if (count > 0) id = `${id}-${count + 1}`;
    headings.push({ id, text, level });
  }

  return headings;
}
