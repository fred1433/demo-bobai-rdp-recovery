// Serves site/ under https://theaipipe.com/demos/rdp-recovery/ (static files only).
// The route is more specific than the galerie-presell route theaipipe.com/demos/*, so it wins.
// Byte ranges are answered here so the page's chapter buttons can seek inside the videos.
const BASE = '/demos/rdp-recovery';
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === BASE) return Response.redirect(`${url.origin}${BASE}/`, 308);
    if (!url.pathname.startsWith(BASE + '/')) return new Response('Not found', { status: 404 });
    const path = url.pathname.slice(BASE.length) || '/';
    const res = await env.ASSETS.fetch(new Request(new URL(path, url.origin), request));
    const range = request.headers.get('Range');
    const m = range && /^bytes=(\d*)-(\d*)$/.exec(range.trim());
    if (m && res.status === 200 && (m[1] || m[2])) {
      const buf = await res.arrayBuffer();
      const size = buf.byteLength;
      let start, end;
      if (m[1]) { start = +m[1]; end = m[2] ? Math.min(+m[2], size - 1) : size - 1; }
      else { start = Math.max(0, size - +m[2]); end = size - 1; }
      if (start >= size || start > end) {
        return new Response(null, { status: 416, headers: { 'Content-Range': `bytes */${size}` } });
      }
      const h = new Headers(res.headers);
      h.set('Content-Range', `bytes ${start}-${end}/${size}`);
      h.set('Content-Length', String(end - start + 1));
      h.set('Accept-Ranges', 'bytes');
      h.set('X-Robots-Tag', 'noindex, nofollow');
      return new Response(buf.slice(start, end + 1), { status: 206, headers: h });
    }
    const out = new Response(res.body, res);
    const loc = out.headers.get('Location');
    if (loc && loc.startsWith('/')) out.headers.set('Location', BASE + loc);
    out.headers.set('X-Robots-Tag', 'noindex, nofollow');
    if (path.endsWith('.mp4')) out.headers.set('Accept-Ranges', 'bytes');
    return out;
  },
};
