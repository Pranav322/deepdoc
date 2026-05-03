/// <reference types="vite/client" />

declare module "virtual:changelog-data" {
  type Category = "Added" | "Changed" | "Fixed" | "Maintenance";
  interface ReleaseEntry {
    version: string;
    date: string;
    summary: string;
    isLatest?: boolean;
    isPatch?: boolean;
    githubUrl: string;
    sections: { category: Category; items: string[] }[];
  }
  const releases: ReleaseEntry[];
  export default releases;
}
