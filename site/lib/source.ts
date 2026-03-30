import { resolveFiles } from 'fumadocs-mdx';
import { loader } from 'fumadocs-core/source';
import { docs, meta } from '@/.source';

export const docsSource = loader({
  baseUrl: '/',
  source: {
    files: resolveFiles({ docs, meta }),
  },
});
