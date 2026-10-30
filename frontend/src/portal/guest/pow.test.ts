import { describe, expect, it } from "vitest";

import { leadingZeroBits, solve, solveRange, solves } from "./pow";
import { sha256, toHex } from "./sha256";
import { onMainThread } from "./solver";

const ascii = (text: string) => new TextEncoder().encode(text);

describe("sha256", () => {
  // Digests from Python's hashlib (FIPS 180-4 vectors and padding edges: 55, 56, 64, 119 bytes).
  it.each([
    ["", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
    ["abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"],
    ["a".repeat(55), "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318"],
    ["a".repeat(56), "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a"],
    ["a".repeat(64), "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb"],
    ["a".repeat(119), "31eba51c313a5c08226adf18d4a359cfdfd8d2e816b13f4af952f7ea6584dcfb"],
    ["مرحبا", "80eff1a750bb540045622ad23c148c8875790515e3f768c77d5dff8c1d221b49"],
  ])("hashes %j like hashlib", (text, digest) => {
    expect(toHex(sha256(ascii(text)))).toBe(digest);
  });
});

describe("proof of work (backend/domain/proof_of_work.py vectors)", () => {
  // Challenges issued by domain.proof_of_work.issue(b"k" * 32, ...) and the nonce its solve()
  // returns: the browser must find the very same one.
  const vectors = [
    {
      token: "0123456789abcdef.1893456000.8.3e439f488c7d8c6dd696da9da0b44048",
      bits: 8,
      nonce: "798",
      digest: "002196436c1625d691d1a4eb6ba99895f9b1091b69b4a55388cc66b1e3933377",
    },
    {
      token: "fedcba9876543210.1893456000.12.419819bb4dc90a1f77433c223803ea55",
      bits: 12,
      nonce: "7402",
      digest: "0001116d9ab910e2de6e12395ff9d24ebd76f94534963fc094c963e2efb643a5",
    },
    {
      token: "00112233aabbccdd.1893456000.16.a4788730394e8e1b0e823d33f5ae265b",
      bits: 16,
      nonce: "115782",
      digest: "00001825ebc9dbb37160019dfaea621e02788653cad7a161eb27779c0951416d",
    },
  ];

  it.each(vectors)("finds the backend's nonce for $bits bits", ({ token, bits, nonce, digest }) => {
    expect(solve(token, bits)).toBe(nonce);
    expect(toHex(sha256(ascii(token + nonce)))).toBe(digest);
    expect(solves(token, nonce, bits)).toBe(true);
  });

  it("a nonce below the answer does not solve", () => {
    const { token, bits, nonce } = vectors[1] ?? vectors[0]!;
    expect(solveRange(token, bits, 0, Number(nonce))).toBeNull();
    expect(solves(token, String(Number(nonce) - 1), bits)).toBe(false);
  });

  it("counts leading zero bits", () => {
    expect(leadingZeroBits(new Uint8Array([0, 0, 0x10, 0xff]))).toBe(19);
    expect(leadingZeroBits(new Uint8Array([0x80]))).toBe(0);
    expect(leadingZeroBits(new Uint8Array([0, 1]))).toBe(15);
    expect(leadingZeroBits(new Uint8Array([0, 0]))).toBe(16);
  });

  it("the main-thread fallback yields, reports progress and finds the same nonce", async () => {
    const { token, bits, nonce } = vectors[2]!;
    const seen: number[] = [];
    const found = await onMainThread({ token, bits }, { onProgress: (n) => seen.push(n) });
    expect(found).toBe(nonce);
    expect(seen.length).toBeGreaterThan(1);
    expect(seen.at(-1)).toBe(Number(nonce) + 1);
  });

  it("the search stops when aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(onMainThread({ token: vectors[2]!.token, bits: 30 }, { signal: controller.signal })).rejects.toThrow(
      /stopped/u,
    );
  });
});
