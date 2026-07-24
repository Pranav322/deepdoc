// Next.js's postcss loader searches upward through parent directories for a
// config file. If the repo being documented is itself a JS project with its
// own postcss.config.js/tailwind.config.* at its root, Next would otherwise
// pick that up instead of this site's own (site/ sits inside that repo) —
// and fail with "Cannot find module 'tailwindcss'" since that plugin was
// never a dependency here. Providing our own config, however minimal, stops
// the upward search at this directory. No plugins needed — this template
// doesn't use Tailwind.
/** @type {import('postcss-load-config').Config} */
const config = { plugins: {} };

export default config;
