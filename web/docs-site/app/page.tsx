import { redirect } from 'next/navigation';

// basePath is /docs, so "/" here is deepdoc.tech/docs.
export default function Home() {
  redirect('/docs');
}
