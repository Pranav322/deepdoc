import { notFound } from 'next/navigation';
import { DocsBody, DocsPage } from 'fumadocs-ui/page';
import { APIPage } from '@/components/api-page';
import { apiSource } from '@/lib/openapi';

export function generateStaticParams() {
  return apiSource ? apiSource.generateParams() : [];
}

export default async function Page(props: {
  params: Promise<{ slug?: string[] }>;
}) {
  const params = await props.params;
  if (!apiSource) notFound();

  const page = apiSource.getPage(params.slug ?? []);
  if (!page || page.data.type !== 'openapi') notFound();

  return (
    <DocsPage full>
      <DocsBody>
        <APIPage {...page.data.getAPIPageProps()} />
      </DocsBody>
    </DocsPage>
  );
}
