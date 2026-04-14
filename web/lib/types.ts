/**
 * Core types for the yt-to-site web frontend.
 * Content types and locale definitions are configured per-project.
 */

export type RawItem = {
  id: string | number;
  title?: string;
  full_title?: string;
  description?: string;
  content?: string;
  content_type?: string;
  youtube_id?: string;
  thumbnail_url?: string;
  is_series?: boolean;
  is_active?: boolean;
  parent_id?: string | number | null;
  episode_number?: number;
  authored_date?: string;
  summary?: string;
  source_language?: string;
  [k: string]: any;
};

export type Locale = string;

export type SiteConfig = {
  siteName: string;
  siteDescription: string;
  defaultLocale: string;
  supportedLocales: string[];
  contentTypes: string[];
  domain?: string;
};
