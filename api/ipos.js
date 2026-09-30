// Vercel serverless function: scrapes IPO Watch's GMP table and returns JSON.
const SOURCE = 'https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/';

const strip = (s) =>
  s.replace(/<[^>]*>/g, ' ').replace(/&nbsp;|&#160;/g, ' ').replace(/&amp;/g, '&')
    .replace(/&#8377;|&#x20b9;/gi, '₹').replace(/&#8211;|&ndash;/g, '-').replace(/&#\d+;/g, '')
    .replace(/\s+/g, ' ').trim();

const num = (s) => {
  if (!s) return null;
  const m = String(s).replace(/,/g, '').match(/(-)?\s*₹?\s*(\d+(\.\d+)?)/);
  return m ? (m[1] ? -1 : 1) * parseFloat(m[2]) : null;
};

function parseTables(html) {
  const out = [];
  for (const t of html.match(/<table[\s\S]*?<\/table>/gi) || []) {
    const rows = (t.match(/<tr[\s\S]*?<\/tr>/gi) || []).map((r) =>
      (r.match(/<t[dh][\s\S]*?<\/t[dh]>/gi) || []).map((c) => ({
        text: strip(c),
        href: (c.match(/href="([^"]+)"/i) || [])[1] || null,
      }))
    );
    if (rows.length > 1) out.push(rows);
  }
  return out;
}

function toIpos(rows) {
  const head = rows[0].map((c) => c.text.toLowerCase());
  const find = (re) => head.findIndex((h) => re.test(h));
  const col = {
    name: find(/ipo|company|name/),
    gmp: find(/gmp|premium/),
    price: find(/price|band/),
    gain: find(/gain|est|%/),
    open: find(/open/),
    close: find(/close/),
    listing: find(/listing|list date/),
    size: find(/size|issue/),
    type: find(/type|category|board/),
  };
  if (col.name < 0 || col.gmp < 0) return [];
  const out = [];
  for (const r of rows.slice(1)) {
    const name = r[col.name]?.text;
    if (!name || r.length < 3) continue;
    const gmpCell = r[col.gmp]?.text || '';
    const price = col.price >= 0 ? r[col.price]?.text : '';
    const prices = (price.match(/\d[\d,]*(\.\d+)?/g) || []).map((x) => parseFloat(x.replace(/,/g, '')));
    const upper = prices.length ? Math.max(...prices) : null;
    const gmp = /^\s*(-|na|n\/a|--)?\s*$/i.test(gmpCell) ? null : num(gmpCell.replace(/\(.*?\)/, ''));
    let gain = null;
    const pct = gmpCell.match(/\(?\s*(-?\d+(\.\d+)?)\s*%/);
    if (col.gain >= 0 && r[col.gain] && col.gain !== col.gmp) gain = num(r[col.gain].text);
    if (gain == null && pct) gain = parseFloat(pct[1]);
    if (gain == null && gmp != null && upper) gain = +((gmp / upper) * 100).toFixed(2);
    const cell = (i) => (i >= 0 ? r[i]?.text || '' : '');
    const all = r.map((c) => c.text).join(' ');
    out.push({
      name: name.replace(/\b(IPO|GMP)\b/gi, '').replace(/\s+/g, ' ').trim() || name,
      sme: /sme/i.test(all),
      gmp,
      gain,
      price: upper,
      priceText: price,
      open: cell(col.open),
      close: cell(col.close),
      listing: cell(col.listing),
      size: cell(col.size),
      url: r[col.name]?.href || null,
    });
  }
  return out;
}

module.exports = async (req, res) => {
  try {
    const r = await fetch(SOURCE, {
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; easydime/1.0)', Accept: 'text/html' },
    });
    if (!r.ok) throw new Error('Source returned HTTP ' + r.status);
    const html = await r.text();
    const tables = parseTables(html);
    const ipos = tables.flatMap(toIpos);
    res.setHeader('Cache-Control', 's-maxage=900, stale-while-revalidate=3600');
    if (req.query && req.query.debug) {
      return res.status(200).json({ tables: tables.length, headers: tables.map((t) => t[0].map((c) => c.text)), sample: tables[0]?.slice(0, 4), ipos });
    }
    res.status(200).json({ updated: new Date().toISOString(), source: SOURCE, ipos });
  } catch (e) {
    res.status(502).json({ error: String(e.message || e) });
  }
};
module.exports.parse = (html) => parseTables(html).flatMap(toIpos);
