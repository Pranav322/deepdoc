/** @type {import('next').NextConfig} */
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';
const isProd = process.env.NODE_ENV === 'production';

const config = {
  // Static export only for production builds — dev mode needs dynamic rendering
  ...(isProd ? { output: 'export' } : {}),
  basePath,
  assetPrefix: basePath || undefined,
  images: { unoptimized: true },
  trailingSlash: true,
};

export default config;
