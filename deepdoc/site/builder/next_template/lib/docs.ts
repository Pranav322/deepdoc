import fs from 'node:fs';
import path from 'node:path';
import matter from 'gray-matter';
import { getConfig } from './config';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkRehype from 'remark-rehype';
import rehypeRaw from 'rehype-raw';
import rehypeSlug from 'rehype-slug';
import rehypeShiki from '@shikijs/rehype';
import { visit } from 'unist-util-visit';
import type { Root as HastRoot, Element } from 'hast';

// The builder writes DEEPDOC_DOCS_DIR into .env.local. Keep docs and site
// roots independently configurable so DeepDoc never collides with authored
// repository documentation.
const DOCS_DIR = path.resolve(
  process.cwd(),
  process.env.DEEPDOC_DOCS_DIR || '../deepdoc-docs',
);

export interface TocItem {
  id: string;
  title: string;
  depth: number;
  url: string;
}

export interface DocPage {
  slug: string[];
  title: string;
  description: string;
  html: string;
  toc: TocItem[];
}

// ── remark/rehype pipeline ────────────────────────────────────────────────────

// Transform "> [!NOTE]" / "> [!WARNING]" etc. blockquotes into callout divs.
function rehypeGitHubAlerts() {
  const ALERT_RE = /^\[!(NOTE|TIP|WARNING|DANGER|INFO)\]\n?/;
  const LABEL: Record<string, string> = {
    NOTE: 'Note', TIP: 'Tip', WARNING: 'Warning', DANGER: 'Danger', INFO: 'Info',
  };
  return (tree: HastRoot) => {
    visit(tree, 'element', (node: Element) => {
      if (node.tagName !== 'blockquote') return;
      const firstP = node.children.find(
        (c): c is Element => c.type === 'element' && c.tagName === 'p',
      );
      if (!firstP) return;
      const firstText = firstP.children[0];
      if (firstText?.type !== 'text') return;
      const m = ALERT_RE.exec(firstText.value);
      if (!m) return;

      const type = m[1].toLowerCase();
      firstText.value = firstText.value.slice(m[0].length);
      if (!firstText.value) firstP.children.shift();

      node.tagName = 'div';
      node.properties = { className: [`dd-callout`, `dd-callout-${type}`] };
      node.children.unshift({
        type: 'element',
        tagName: 'p',
        properties: { className: ['dd-callout-title'] },
        children: [{ type: 'text', value: LABEL[m[1]] ?? m[1] }],
      });
    });
  };
}

// Root-absolute internal doc links (e.g. "/getting-started") are emitted by
// the generator assuming the site is served at domain root. Next.js only
// auto-prefixes `basePath` for its own <Link>/router navigation — never a
// literal href baked into rendered Markdown content — so when a site is
// served under a basePath (hosted generation serves each site at
// /<owner>/<repo>/), these links 404 unless rewritten here at render time.
const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || '';

function rehypeBasePath() {
  return (tree: HastRoot) => {
    if (!BASE_PATH) return;
    visit(tree, 'element', (node: Element) => {
      if (node.tagName !== 'a') return;
      const href = node.properties?.href;
      if (typeof href !== 'string') return;
      if (!href.startsWith('/') || href === BASE_PATH || href.startsWith(BASE_PATH + '/')) return;
      node.properties.href = BASE_PATH + href;
    });
  };
}

// Wrap ```mermaid fences for client-side rendering via mermaid.js
function rehypeMermaid() {
  return (tree: HastRoot) => {
    visit(tree, 'element', (node: Element) => {
      if (node.tagName !== 'pre') return;
      const code = node.children.find(
        (c): c is Element => c.type === 'element' && c.tagName === 'code',
      );
      if (!code) return;
      const cls = (code.properties?.className as string[]) ?? [];
      if (!cls.includes('language-mermaid')) return;
      const text = code.children.find(c => c.type === 'text');
      if (!text || text.type !== 'text') return;
      node.tagName = 'div';
      node.properties = { className: ['mermaid'] };
      node.children = [{ type: 'text', value: text.value }];
    });
  };
}

// Cache the fully-built processor (including rehype-stringify) as a Promise so
// concurrent calls share the same init work and the processor is only frozen once.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let _processorPromise: Promise<any> | null = null;

async function getProcessor() {
  if (!_processorPromise) {
    _processorPromise = import('rehype-stringify').then(({ default: rehypeStringify }) =>
      unified()
        .use(remarkParse)
        .use(remarkGfm)
        .use(remarkRehype, { allowDangerousHtml: true })
        .use(rehypeRaw)
        .use(rehypeGitHubAlerts)
        .use(rehypeMermaid)
        .use(rehypeBasePath)
        .use(rehypeShiki, {
          // Configurable via site.theme.code_theme in .deepdoc.yaml.
          themes: {
            light: getConfig().theme?.code_theme?.light || 'github-light',
            dark: getConfig().theme?.code_theme?.dark || 'github-dark',
          },
          fallbackLanguage: 'text',
        })
        .use(rehypeSlug)
        .use(rehypeStringify)
    );
  }
  return _processorPromise;
}

// ── TOC extraction ─────────────────────────────────────────────────────────────

function extractToc(html: string): TocItem[] {
  const toc: TocItem[] = [];
  const re = /<h([2-3])\s[^>]*id="([^"]+)"[^>]*>([\s\S]*?)<\/h[2-3]>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html)) !== null) {
    const depth = parseInt(m[1], 10);
    const id = m[2];
    const title = m[3].replace(/<[^>]+>/g, '').trim();
    toc.push({ id, title, depth, url: `#${id}` });
  }
  return toc;
}

// ── Public API ─────────────────────────────────────────────────────────────────

export function getAllSlugs(): string[][] {
  if (!fs.existsSync(DOCS_DIR)) return [];
  return fs
    .readdirSync(DOCS_DIR)
    .filter(f => f.endsWith('.md'))
    .map(f => (f === 'index.md' ? [] : [f.replace(/\.md$/, '')]));
}

export interface SearchIndex {
  title: string;
  description?: string;
  content: string;
  url: string;
}

// The whole index is downloaded by the browser on first search, and Orama's
// serialized form grows fast with token positions. Uncapped, a 48-page repo
// produced a ~3 MB download. Cap the prose per page: what people search for
// lives in the title and the opening sections, not paragraph 40.
const MAX_INDEXED_CHARS = 2000;

/** Strip Markdown down to prose for indexing.
 *
 * Fenced code is dropped: it is mostly punctuation and identifiers that swamp
 * the ranking without helping anyone find a page.
 */
function toPlainText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!\[[^\]]*]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s{0,3}>\s?/gm, '')
    .replace(/[*_~|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Build the search index from the generated Markdown.
 *
 * Read straight off disk rather than through a content source, because this
 * template renders plain .md at runtime and has no fumadocs source adapter.
 */
export function getSearchIndexes(): SearchIndex[] {
  if (!fs.existsSync(DOCS_DIR)) return [];
  const indexes: SearchIndex[] = [];

  for (const slug of getAllSlugs()) {
    const filename = slug.length === 0 ? 'index.md' : `${slug.join('/')}.md`;
    const filepath = path.join(DOCS_DIR, filename);
    let raw: string;
    try {
      raw = fs.readFileSync(filepath, 'utf-8');
    } catch {
      continue;
    }
    const { data: fm, content } = matter(raw);
    const h1 = /^\s{0,3}#\s+(.+)$/m.exec(content);
    indexes.push({
      title:
        (fm.title as string | undefined) ||
        h1?.[1].trim() ||
        slug[slug.length - 1] ||
        'Untitled',
      description: (fm.description as string | undefined) ?? '',
      content: toPlainText(content).slice(0, MAX_INDEXED_CHARS),
      url: slug.length === 0 ? '/' : `/${slug.join('/')}`,
    });
  }
  return indexes;
}

export async function getPage(slug: string[]): Promise<DocPage | null> {
  const filename = slug.length === 0 ? 'index.md' : `${slug.join('/')}.md`;
  const filepath = path.join(DOCS_DIR, filename);
  if (!fs.existsSync(filepath)) return null;

  const raw = fs.readFileSync(filepath, 'utf-8');
  const { data: fm, content } = matter(raw);

  const processor = await getProcessor();
  const result = await processor.process(content);
  const html = String(result);

  // First h1 or frontmatter title
  const h1Match = /<h1[^>]*>([\s\S]*?)<\/h1>/.exec(html);
  const title =
    (fm.title as string | undefined) ||
    h1Match?.[1].replace(/<[^>]+>/g, '').trim() ||
    slug[slug.length - 1] ||
    'Untitled';

  return {
    slug,
    title,
    description: (fm.description as string | undefined) ?? '',
    html,
    toc: extractToc(html),
  };
}
