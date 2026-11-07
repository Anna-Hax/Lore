/* Shared display helpers for the explorer and workspace. No DOM access, no network. */

function toBig(value) {
  if (typeof value === 'bigint') return value;
  if (typeof value === 'number') return Number.isFinite(value) ? BigInt(Math.round(value)) : null;
  if (typeof value === 'string' && /^-?\d+$/.test(value.trim())) return BigInt(value.trim());
  return null;
}

/* Integer base units (wei, or token units) to a readable amount: "0.02 0G", "1,250.5 0G".
   BigInt throughout, never scientific notation. At most `digits` decimals once the amount
   reaches 1, otherwise `digits` significant digits. */
export function formatUnits(value, { decimals = 18, unit = '0G', digits = 4 } = {}) {
  let v = toBig(value);
  if (v === null) return '—';
  const sign = v < 0n ? '-' : '';
  if (v < 0n) v = -v;
  const suffix = unit ? ` ${unit}` : '';
  if (v === 0n) return `0${suffix}`;
  const base = 10n ** BigInt(decimals);
  let places = digits;
  if (v < base) {
    const lead = (v % base).toString().padStart(decimals, '0').search(/[1-9]/);
    if (lead >= 8) return `${sign}< 0.00000001${suffix}`;
    places = lead + digits;
  }
  places = Math.min(places, decimals);
  const scale = 10n ** BigInt(decimals - places);
  const rounded = (v + scale / 2n) / scale;
  const unitScale = 10n ** BigInt(places);
  const whole = rounded / unitScale;
  const fraction = places ? (rounded % unitScale).toString().padStart(places, '0').replace(/0+$/, '') : '';
  return `${sign}${whole.toLocaleString('en-US')}${fraction ? `.${fraction}` : ''}${suffix}`;
}
export const format0G = value => formatUnits(value);
export const formatTokens = value => formatUnits(value, { unit: 'tokens' });

/* "1 node", "3 nodes", "1 person", "2 people". */
export function plural(n, one, many = `${one}s`) {
  const count = typeof n === 'number' && Number.isFinite(n) ? n : 0;
  return `${count.toLocaleString('en-US')} ${count === 1 ? one : many}`;
}

/* Gateway tool errors arrive as "Error executing tool lore_x: message". Keep only the message. */
export function cleanError(error) {
  let text = String((error && error.message) || error || 'Something went wrong.');
  text = text.replace(/^Error executing tool [\w.-]+:\s*/i, '').replace(/^(Lore)?Error:\s*/, '').trim();
  return text ? text[0].toUpperCase() + text.slice(1) : 'Something went wrong.';
}

/* Unix seconds (or milliseconds) to "in 12 days" / "3 hours ago". */
export function relativeTime(ts, now = Date.now()) {
  if (typeof ts !== 'number' || !Number.isFinite(ts)) return '';
  const ms = ts > 1e12 ? ts : ts * 1000;
  const diff = Math.round((ms - now) / 1000), abs = Math.abs(diff);
  if (abs < 60) return 'just now';
  const [size, name] = abs >= 86400 ? [86400, 'day'] : abs >= 3600 ? [3600, 'hour'] : [60, 'minute'];
  const label = plural(Math.floor(abs / size), name);
  return diff > 0 ? `in ${label}` : `${label} ago`;
}
export function absoluteTime(ts) {
  if (typeof ts !== 'number' || !Number.isFinite(ts)) return '';
  return new Date(ts > 1e12 ? ts : ts * 1000).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' });
}
