export function managementUrl(locationHref: string, configured?: string): string {
  try {
    const fallback = new URL(locationHref);
    fallback.port = '5173';
    fallback.pathname = '/';
    fallback.search = '';
    fallback.hash = '';
    const url = new URL(configured?.trim() || fallback.href, locationHref);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password
      ? url.href
      : '';
  } catch {
    return '';
  }
}
