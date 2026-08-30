import type { MetadataRoute } from 'next';
import { source } from '@/lib/source';

// Static export needs this to be prerendered.
export const dynamic = 'force-static';

export default function sitemap(): MetadataRoute.Sitemap {
  const site = 'https://www.deepdoc.tech';
  return source.getPages().map(page => ({
    url: `${site}/docs${page.url === '/' ? '' : page.url}`,
    lastModified: new Date(),
    changeFrequency: 'weekly' as const,
    priority: page.url === '/' ? 1 : 0.7,
  }));
}
