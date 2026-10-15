// Only generated report filenames are accepted by the private archive route.
export function validArtifactKey(key: string): boolean {
  return /^[a-f0-9]{16}\/(?:[A-Z0-9]{1,12}|top10|daily)-\d{4}-\d{2}-\d{2}(?:-chart)?\.(?:png|pdf)$/.test(key);
}
