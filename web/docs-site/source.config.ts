import { defineDocs, defineConfig } from 'fumadocs-mdx/config';

// Keep the combined collection — `toFumadocsSource()` only exists on this
// shape. Destructuring into { docs, meta } yields two plain arrays and that
// helper disappears (and `createMDXSource` does not exist in v11).
export const docs = defineDocs({ dir: 'content/docs' });

export default defineConfig({
  mdxOptions: {
    rehypeCodeOptions: { themes: { light: 'github-light', dark: 'github-dark' } },
  },
});
