import { notFound } from 'next/navigation';
import { DocsBody, DocsPage } from 'fumadocs-ui/page';
import { docsSource } from '@/lib/source';
import { getMDXComponents } from '@/mdx-components';

export function generateStaticParams() {
  return docsSource.generateParams();
}

export default async function Page(props: {
  params: Promise<{ slug?: string[] }>;
}) {
  const params = await props.params;
  const page = docsSource.getPage(params.slug ?? []);
  if (!page) notFound();

  const MDX = page.data.body;

  return (
    <DocsPage toc={page.data.toc}>
      <DocsBody>
        <MDX components={getMDXComponents()} />
      </DocsBody>
    </DocsPage>
  );
}
