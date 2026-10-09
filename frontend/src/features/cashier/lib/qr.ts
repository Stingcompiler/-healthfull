/**
 * Minimal QR Code encoder (ISO/IEC 18004) for receipt verification codes (FEATURES 6.9):
 * byte mode, error correction level M, versions 1-10, mask chosen by the standard penalty
 * rules. Bundled on purpose: the app never loads code from the internet (ARCHITECTURE 8).
 * Follows the structure of Project Nayuki's public-domain-style reference algorithm.
 */

const MAX_VERSION = 10;
/** Level M: error correction codewords per block, by version (index 0 unused). */
const ECC_PER_BLOCK = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26] as const;
/** Level M: error correction blocks, by version (index 0 unused). */
const ECC_BLOCKS = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5] as const;
/** Format bits of level M. */
const ECC_FORMAT_M = 0;

export interface QrMatrix {
  size: number;
  version: number;
  mask: number;
  /** modules[y][x], true = dark. */
  modules: boolean[][];
}

function bit(value: number, i: number): boolean {
  return ((value >>> i) & 1) !== 0;
}

export function rawDataModules(ver: number): number {
  let result = (16 * ver + 128) * ver + 64;
  if (ver >= 2) {
    const align = Math.floor(ver / 7) + 2;
    result -= (25 * align - 10) * align - 55;
    if (ver >= 7) result -= 36;
  }
  return result;
}

export function dataCodewords(ver: number): number {
  return Math.floor(rawDataModules(ver) / 8) - (ECC_PER_BLOCK[ver] ?? 0) * (ECC_BLOCKS[ver] ?? 0);
}

/** GF(2^8) multiplication modulo x^8 + x^4 + x^3 + x^2 + 1. */
export function gfMultiply(x: number, y: number): number {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z & 0xff;
}

export function rsDivisor(degree: number): number[] {
  const result = new Array<number>(degree).fill(0);
  result[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < result.length; j++) {
      result[j] = gfMultiply(result[j] ?? 0, root);
      if (j + 1 < result.length) result[j] = (result[j] ?? 0) ^ (result[j + 1] ?? 0);
    }
    root = gfMultiply(root, 0x02);
  }
  return result;
}

export function rsRemainder(data: readonly number[], divisor: readonly number[]): number[] {
  const result = new Array<number>(divisor.length).fill(0);
  for (const b of data) {
    const factor = b ^ (result.shift() ?? 0);
    result.push(0);
    divisor.forEach((coef, i) => {
      result[i] = (result[i] ?? 0) ^ gfMultiply(coef, factor);
    });
  }
  return result;
}

/** The 15 format bits (level M) for `mask`. */
export function formatBits(mask: number): number {
  const data = (ECC_FORMAT_M << 3) | mask;
  let rem = data;
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
  return ((data << 10) | rem) ^ 0x5412;
}

function alignmentPositions(ver: number, size: number): number[] {
  if (ver === 1) return [];
  const count = Math.floor(ver / 7) + 2;
  const step = Math.ceil((ver * 4 + 4) / (count * 2 - 2)) * 2;
  const result = [6];
  for (let pos = size - 7; result.length < count; pos -= step) result.splice(1, 0, pos);
  return result;
}

function utf8(text: string): number[] {
  return Array.from(new TextEncoder().encode(text));
}

function encodeData(bytes: readonly number[], ver: number): number[] {
  const bits: number[] = [];
  const push = (value: number, length: number) => {
    for (let i = length - 1; i >= 0; i--) bits.push((value >>> i) & 1);
  };
  push(0b0100, 4);
  push(bytes.length, ver <= 9 ? 8 : 16);
  for (const b of bytes) push(b, 8);
  const capacity = dataCodewords(ver) * 8;
  push(0, Math.min(4, capacity - bits.length));
  push(0, (8 - (bits.length % 8)) % 8);
  const out: number[] = [];
  for (let i = 0; i < bits.length; i += 8) {
    let byte = 0;
    for (let j = 0; j < 8; j++) byte = (byte << 1) | (bits[i + j] ?? 0);
    out.push(byte);
  }
  for (let pad = 0xec; out.length < dataCodewords(ver); pad ^= 0xec ^ 0x11) out.push(pad);
  return out;
}

function addEccAndInterleave(data: readonly number[], ver: number): number[] {
  const blocks = ECC_BLOCKS[ver] ?? 1;
  const eccLen = ECC_PER_BLOCK[ver] ?? 0;
  const raw = Math.floor(rawDataModules(ver) / 8);
  const shortBlocks = blocks - (raw % blocks);
  const shortLen = Math.floor(raw / blocks);
  const divisor = rsDivisor(eccLen);
  const all: number[][] = [];
  for (let i = 0, k = 0; i < blocks; i++) {
    const len = shortLen - eccLen + (i < shortBlocks ? 0 : 1);
    const dat = data.slice(k, k + len);
    k += len;
    const ecc = rsRemainder(dat, divisor);
    if (i < shortBlocks) dat.push(0);
    all.push([...dat, ...ecc]);
  }
  const result: number[] = [];
  const width = all[0]?.length ?? 0;
  for (let i = 0; i < width; i++) {
    all.forEach((block, j) => {
      if (i !== shortLen - eccLen || j >= shortBlocks) result.push(block[i] ?? 0);
    });
  }
  return result;
}

class Grid {
  readonly modules: boolean[][];
  readonly isFunction: boolean[][];
  readonly size: number;

  constructor(size: number) {
    this.size = size;
    this.modules = Array.from({ length: size }, () => new Array<boolean>(size).fill(false));
    this.isFunction = Array.from({ length: size }, () => new Array<boolean>(size).fill(false));
  }

  setFunction(x: number, y: number, dark: boolean): void {
    const row = this.modules[y];
    const fn = this.isFunction[y];
    if (!row || !fn) return;
    row[x] = dark;
    fn[x] = true;
  }
}

function drawFunctionPatterns(g: Grid, ver: number): void {
  const size = g.size;
  for (let i = 0; i < size; i++) {
    g.setFunction(6, i, i % 2 === 0);
    g.setFunction(i, 6, i % 2 === 0);
  }
  for (const [cx, cy] of [
    [3, 3],
    [size - 4, 3],
    [3, size - 4],
  ] as const) {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const dist = Math.max(Math.abs(dx), Math.abs(dy));
        const x = cx + dx;
        const y = cy + dy;
        if (x >= 0 && x < size && y >= 0 && y < size) g.setFunction(x, y, dist !== 2 && dist !== 4);
      }
    }
  }
  const align = alignmentPositions(ver, size);
  const last = align.length - 1;
  align.forEach((ay, i) => {
    align.forEach((ax, j) => {
      if ((i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)) return;
      for (let dy = -2; dy <= 2; dy++) {
        for (let dx = -2; dx <= 2; dx++) g.setFunction(ax + dx, ay + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
      }
    });
  });
  drawFormat(g, 0);
  if (ver >= 7) {
    let rem = ver;
    for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
    const bits = (ver << 12) | rem;
    for (let i = 0; i < 18; i++) {
      const dark = bit(bits, i);
      const a = size - 11 + (i % 3);
      const b = Math.floor(i / 3);
      g.setFunction(a, b, dark);
      g.setFunction(b, a, dark);
    }
  }
}

function drawFormat(g: Grid, mask: number): void {
  const bits = formatBits(mask);
  const size = g.size;
  for (let i = 0; i <= 5; i++) g.setFunction(8, i, bit(bits, i));
  g.setFunction(8, 7, bit(bits, 6));
  g.setFunction(8, 8, bit(bits, 7));
  g.setFunction(7, 8, bit(bits, 8));
  for (let i = 9; i < 15; i++) g.setFunction(14 - i, 8, bit(bits, i));
  for (let i = 0; i < 8; i++) g.setFunction(size - 1 - i, 8, bit(bits, i));
  for (let i = 8; i < 15; i++) g.setFunction(8, size - 15 + i, bit(bits, i));
  g.setFunction(8, size - 8, true);
}

function drawCodewords(g: Grid, data: readonly number[]): void {
  const size = g.size;
  let i = 0;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < size; vert++) {
      for (let j = 0; j < 2; j++) {
        const x = right - j;
        const upward = ((right + 1) & 2) === 0;
        const y = upward ? size - 1 - vert : vert;
        const row = g.modules[y];
        if (row && !g.isFunction[y]?.[x] && i < data.length * 8) {
          row[x] = bit(data[i >>> 3] ?? 0, 7 - (i & 7));
          i++;
        }
      }
    }
  }
}

function maskHit(mask: number, x: number, y: number): boolean {
  switch (mask) {
    case 0:
      return (x + y) % 2 === 0;
    case 1:
      return y % 2 === 0;
    case 2:
      return x % 3 === 0;
    case 3:
      return (x + y) % 3 === 0;
    case 4:
      return (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0;
    case 5:
      return ((x * y) % 2) + ((x * y) % 3) === 0;
    case 6:
      return (((x * y) % 2) + ((x * y) % 3)) % 2 === 0;
    default:
      return (((x + y) % 2) + ((x * y) % 3)) % 2 === 0;
  }
}

function applyMask(g: Grid, mask: number): void {
  for (let y = 0; y < g.size; y++) {
    const row = g.modules[y];
    if (!row) continue;
    for (let x = 0; x < g.size; x++) {
      if (!g.isFunction[y]?.[x] && maskHit(mask, x, y)) row[x] = !row[x];
    }
  }
}

const FINDER_LIKE = [/10111010000/g, /00001011101/g];

function linePenalty(line: readonly boolean[]): number {
  let score = 0;
  let run = 1;
  for (let i = 1; i <= line.length; i++) {
    if (i < line.length && line[i] === line[i - 1]) {
      run++;
    } else {
      if (run >= 5) score += 3 + (run - 5);
      run = 1;
    }
  }
  const text = line.map((d) => (d ? "1" : "0")).join("");
  for (const pattern of FINDER_LIKE) score += 40 * (text.match(pattern)?.length ?? 0);
  return score;
}

export function penalty(modules: readonly (readonly boolean[])[]): number {
  const size = modules.length;
  let score = 0;
  let dark = 0;
  for (let y = 0; y < size; y++) {
    const row = modules[y] ?? [];
    score += linePenalty(row);
    score += linePenalty(modules.map((r) => r[y] ?? false));
    for (let x = 0; x < size; x++) {
      if (row[x]) dark++;
      if (y + 1 < size && x + 1 < size) {
        const c = row[x];
        if (c === row[x + 1] && c === modules[y + 1]?.[x] && c === modules[y + 1]?.[x + 1]) score += 3;
      }
    }
  }
  const total = size * size;
  const k = Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1;
  return score + Math.max(0, k) * 10;
}

/**
 * Encodes `text` (UTF-8, byte mode, level M) in the smallest version that fits.
 *
 * @throws RangeError when the text does not fit version 10 (213 bytes).
 */
export function encodeQr(text: string, options: { mask?: number } = {}): QrMatrix {
  const bytes = utf8(text);
  let ver = 1;
  for (; ver <= MAX_VERSION; ver++) {
    const countBits = ver <= 9 ? 8 : 16;
    if (4 + countBits + bytes.length * 8 <= dataCodewords(ver) * 8) break;
  }
  if (ver > MAX_VERSION) throw new RangeError("QR payload too long");
  const size = ver * 4 + 17;
  const codewords = addEccAndInterleave(encodeData(bytes, ver), ver);

  let best: QrMatrix | null = null;
  let bestScore = Infinity;
  const masks = options.mask === undefined ? [0, 1, 2, 3, 4, 5, 6, 7] : [options.mask];
  for (const mask of masks) {
    const g = new Grid(size);
    drawFunctionPatterns(g, ver);
    drawCodewords(g, codewords);
    applyMask(g, mask);
    drawFormat(g, mask);
    const score = penalty(g.modules);
    if (score < bestScore) {
      bestScore = score;
      best = { size, version: ver, mask, modules: g.modules };
    }
  }
  if (!best) throw new Error("QR encoding failed");
  return best;
}
