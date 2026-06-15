import { notFound } from 'next/navigation';
import type { Metadata } from 'next';
import { DocsPage, DocsBody } from 'fumadocs-ui/page';
import { getAllSlugs, getPage } from '@/lib/docs';

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

  return (
    <DocsPage toc={page.toc} tableOfContent={{ style: 'clerk' }}>
      <DocsBody>
        <div
          className="dd-prose"
          dangerouslySetInnerHTML={{ __html: page.html }}
        />
      </DocsBody>
    </DocsPage>
  );
}
