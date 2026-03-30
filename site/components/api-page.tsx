import client from './api-page.client';
import { openapi } from '@/lib/openapi';
import { createAPIPage } from 'fumadocs-openapi/ui';

function EmptyAPIPage() {
  return null;
}

export const APIPage = openapi
  ? createAPIPage(openapi, { client })
  : EmptyAPIPage;
