import fs from 'node:fs';
import path from 'node:path';
import matter from 'gray-matter';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkRehype from 'remark-rehype';
import rehypeRaw from 'rehype-raw';
import rehypeSlug from 'rehype-slug';
import rehypeShiki from '@shikijs/rehype';
import { visit } from 'unist-util-visit';
import type { Root as HastRoot, Element } from 'hast';

// docs/ lives one level above site/ (the Next.js project root)
const DOCS_DIR = path.resolve(process.cwd(), '..', 'docs');

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
        .use(rehypeShiki, {
          themes: { light: 'github-light', dark: 'github-dark' },
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
  const re = /<h([2-3])\s[^>]*id="([^"]+)"[^>]*>(.*?)<\/h[2-3]>/gs;
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
  const h1Match = /<h1[^>]*>(.*?)<\/h1>/s.exec(html);
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
