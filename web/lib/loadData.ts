import fs from "node:fs";
import path from "node:path";
import { RawItem } from "./types";
import { generateSlug } from "./slug";

const DATA_DIR = process.env.DATA_DIR || path.resolve(process.cwd(), "..", "data");

const jsonlCache = new Map<string, { data: RawItem[]; mtime: number }>();

function readJsonl(filePath: string): RawItem[] {
  if (!fs.existsSync(filePath)) return [];

  const mtime = fs.statSync(filePath).mtimeMs;
  const cached = jsonlCache.get(filePath);
  if (cached && cached.mtime === mtime) return cached.data;

  const content = fs.readFileSync(filePath, "utf-8");
  const data = content
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line) as RawItem;
      } catch {
        return null;
      }
    })
    .filter((x): x is RawItem => !!x);

  jsonlCache.set(filePath, { data, mtime });
  return data;
}

export function dataFileFor(contentType: string, locale?: string) {
  const localeSuffix = locale ? `_${locale}` : "";
  return path.join(DATA_DIR, `${contentType}${localeSuffix}.jsonl`);
}

export async function loadType(contentType: string, locale?: string) {
  return readJsonl(dataFileFor(contentType, locale));
}

export async function findItemBySlug(contentType: string, slug: string, locale?: string): Promise<RawItem | null> {
  const items = await loadType(contentType, locale);
  return items.find((item) => {
    const title = item.title || item.full_title || "";
    return generateSlug(title) === slug;
  }) ?? null;
}

export async function findItemById(contentType: string, id: string | number, locale?: string): Promise<RawItem | null> {
  const items = await loadType(contentType, locale);
  return items.find((x) => String(x.id) === String(id)) ?? null;
}

export function loadTranscript(videoId: number | string, locale?: string): string | null {
  const localeSuffix = locale ? `_${locale}` : "";
  const transcriptPath = path.join(DATA_DIR, "transcripts", `${videoId}_formatted${localeSuffix}.md`);
  if (!fs.existsSync(transcriptPath)) return null;
  return fs.readFileSync(transcriptPath, "utf-8");
}

export async function countForType(contentType: string, locale?: string): Promise<number> {
  const items = await loadType(contentType, locale);
  return items.length;
}
