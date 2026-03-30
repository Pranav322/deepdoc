import defaultMdxComponents from 'fumadocs-ui/mdx';
import * as AccordionComponents from 'fumadocs-ui/components/accordion';
import * as StepsComponents from 'fumadocs-ui/components/steps';
import * as TabsComponents from 'fumadocs-ui/components/tabs';
import { APIPage } from '@/components/api-page';
import { Mermaid } from '@/components/mdx/mermaid';
import type { MDXComponents } from 'mdx/types';

export function getMDXComponents(components?: MDXComponents): MDXComponents {
  return {
    ...defaultMdxComponents,
    ...AccordionComponents,
    ...StepsComponents,
    ...TabsComponents,
    APIPage,
    Mermaid,
    ...components,
  };
}

export const useMDXComponents = getMDXComponents;
