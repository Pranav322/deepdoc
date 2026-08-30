// Our own config stops Next's PostCSS loader searching upward and picking up
// an ancestor project's Tailwind config — the failure fixed in eef8106.
export default { plugins: { '@tailwindcss/postcss': {} } };
