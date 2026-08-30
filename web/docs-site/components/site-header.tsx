import { Logo } from '@/components/logo';
import siteNav from '../../shared/site-nav.json';

/**
 * The site header. The nav itself comes from web/shared/site-nav.json, the
 * same file web/src/components/Header.astro reads — so the marketing site and
 * the docs share one nav rather than two copies that drift apart.
 *
 * Fumadocs' DocsLayout offsets content by --fd-nav-height, which the docs
 * layout sets to SITE_HEADER_HEIGHT.
 */
export const SITE_HEADER_HEIGHT = '52px';

// Relative hrefs in the shared file are rooted at the marketing site; the docs
// are a separate static build, so they need absolute URLs.
function resolve(href: string): string {
  return href.startsWith('/') ? `${siteNav.home}${href}` : href;
}

export function SiteHeader() {
  return (
    <header className="dd-header">
      <div className="dd-header-inner">
        <a href={siteNav.home} className="dd-header-brand" aria-label="DeepDoc home">
          <Logo />
        </a>
        <nav className="dd-header-nav">
          {siteNav.items.map(item => {
            const current = item.href === '/docs';
            return (
              <a
                key={item.label}
                href={current ? '/docs' : resolve(item.href)}
                className={current ? 'dd-header-link is-current' : 'dd-header-link'}
                aria-current={current ? 'page' : undefined}
                {...('external' in item && item.external
                  ? { target: '_blank', rel: 'noreferrer' }
                  : {})}
              >
                {item.label}
              </a>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
