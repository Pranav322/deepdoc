import { notFound } from 'next/navigation';
import type { Metadata } from 'next';
import { DocsPage, DocsBody } from 'fumadocs-ui/page';
import { getAllSlugs, getPage } from '@/lib/docs';
import { getConfig } from '@/lib/config';

interface Props {
  params: Promise<{ slug?: string[] }>;
}

export async function generateStaticParams() {
  const slugs = getAllSlugs();
  return slugs.map(slug => ({ slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const page = await getPage(slug ?? []);
  if (!page) return {};
  return { title: page.title, description: page.description };
}

export default async function DocPage({ params }: Props) {
  const { slug } = await params;
  const page = await getPage(slug ?? []);
  if (!page) return notFound();

  const cfg = getConfig();
  const chrome = cfg.chrome;
  const repo = cfg.repo;

  // Only offer "edit this page" when we know where the source lives; without
  // an owner/name the link would be dead.
  const editOnGithub =
    chrome.edit_link && repo?.owner && repo?.name
      ? {
          owner: repo.owner,
          repo: repo.name,
          sha: repo.branch || 'main',
          path: `${repo.path_prefix}${slug?.length ? slug.join('/') : 'index'}.md`,
        }
      : undefined;

  return (
    <DocsPage
      toc={page.toc}
      tableOfContent={{ enabled: chrome.toc, style: chrome.toc_style }}
      breadcrumb={{ enabled: chrome.breadcrumb }}
      footer={{ enabled: chrome.page_footer }}
      editOnGithub={editOnGithub}
      lastUpdate={chrome.last_update && cfg.generated_at ? cfg.generated_at : undefined}
    >
      <DocsBody>
        <div
          className="dd-prose"
          dangerouslySetInnerHTML={{ __html: page.html }}
        />
      </DocsBody>
    </DocsPage>
  );
}
