import fs from 'node:fs';
import path from 'node:path';
import { loader } from 'fumadocs-core/source';
import { createOpenAPI, openapiPlugin, openapiSource } from 'fumadocs-openapi/server';

const schemaDir = path.join(process.cwd(), 'openapi');
const schemaFiles = fs.existsSync(schemaDir)
  ? fs
      .readdirSync(schemaDir)
      .filter((file) => /\.(json|ya?ml)$/i.test(file))
      .map((file) => `./openapi/${file}`)
  : [];

export const openapi =
  schemaFiles.length > 0
    ? createOpenAPI({
        input: schemaFiles,
      })
    : null;

export const apiSource = openapi
  ? loader({
      baseUrl: '/api',
      source: await openapiSource(openapi, {
        baseDir: '',
      }),
      plugins: [openapiPlugin()],
    })
  : null;
