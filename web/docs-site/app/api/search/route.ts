import { createFromSource } from 'fumadocs-core/search/server';
import { source } from '@/lib/source';

// `staticGET` exports the whole index as a static asset and the browser
// filters it. The site builds with `output: 'export'`, so there is no server
// at runtime to answer a query.
export const revalidate = false;
export const dynamic = 'force-static';

export const { staticGET: GET } = createFromSource(source);
