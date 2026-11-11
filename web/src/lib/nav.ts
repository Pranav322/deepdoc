// Single source for navigation: the site header, the docs sidebar, prev/next
// links and the footer all read from here.

export interface NavLink {
  label: string;
  href: string;
  external?: boolean;
  /** Dropped from the header on narrow screens. */
  optional?: boolean;
}

export const HOME = "https://deepdoc.tech";
export const CLOUD = "https://cloud.deepdoc.tech";
export const GITHUB = "https://github.com/Pranav322/deepdoc";
export const PYPI = "https://pypi.org/project/deepdoc/";

export const headerLinks: NavLink[] = [
  { label: "Docs", href: "/docs" },
  { label: "Changelog", href: "/changelog" },
  { label: "GitHub", href: GITHUB, external: true, optional: true },
];

export const footerLinks: NavLink[] = [
  { label: "Docs", href: "/docs" },
  { label: "Changelog", href: "/changelog" },
  { label: "Cloud", href: CLOUD, external: true },
  { label: "GitHub", href: GITHUB, external: true },
  { label: "PyPI", href: PYPI, external: true },
  { label: "License", href: `${GITHUB}/blob/main/LICENSE`, external: true },
];

export interface DocsSection {
  title: string;
  /** Doc ids (file path under src/content/docs, no extension), in reading order. */
  pages: string[];
}

/** The docs reading order. A page missing here is a build error, not a silent orphan. */
export const docsSections: DocsSection[] = [
  { title: "Get started", pages: ["index", "quickstart", "your-first-site"] },
  {
    title: "Use DeepDoc",
    pages: ["commands", "providers", "keeping-docs-fresh", "costs", "chatbot", "deploying", "cloud", "vscode"],
  },
  {
    title: "Customize",
    pages: ["theming/colours", "theming/logo-and-fonts", "theming/layout", "theming/navigation"],
  },
  { title: "Reference", pages: ["reference/configuration", "reference/how-it-works", "troubleshooting"] },
];

export const docsOrder = docsSections.flatMap((s) => s.pages);

export const docHref = (id: string) => (id === "index" ? "/docs" : `/docs/${id}`);
