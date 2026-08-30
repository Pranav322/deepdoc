import { createSearchAPI } from 'fumadocs-core/search/server';
import { getSearchIndexes } from '@/lib/docs';

// `staticGET` exports the whole index as a static asset and the client filters
// it in the browser. The site is built with `output: 'export'`, so a dynamic
// search handler could not run — there is no server at runtime.
export const revalidate = false;
export const dynamic = 'force-static';

export const { staticGET: GET } = createSearchAPI('simple', {
  indexes: getSearchIndexes(),
});
