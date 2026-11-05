import { createHash, randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

const SCRYPT_N = 16384;
const SCRYPT_R = 8;
const SCRYPT_P = 1;
const KEY_LENGTH = 64;

export function hashPassword(password: string): string {
  const salt = randomBytes(16);
  const derived = scryptSync(password, salt, KEY_LENGTH, {
    N: SCRYPT_N,
    r: SCRYPT_R,
    p: SCRYPT_P,
    maxmem: 64 * 1024 * 1024,
  });
  return `scrypt$${SCRYPT_N}$${SCRYPT_R}$${SCRYPT_P}$${salt.toString("hex")}$${derived.toString("hex")}`;
}

export function verifyPassword(password: string, stored: string): boolean {
  const parts = stored.split("$");
  if (parts.length !== 6 || parts[0] !== "scrypt") return false;
  const [nText, rText, pText, saltText, digestText] = parts.slice(1);
  if (Number(nText) !== SCRYPT_N || Number(rText) !== SCRYPT_R || Number(pText) !== SCRYPT_P) return false;
  if (!/^[a-f0-9]{32}$/i.test(saltText) || !/^[a-f0-9]{128}$/i.test(digestText)) return false;
  const expected = Buffer.from(digestText, "hex");
  const actual = scryptSync(password, Buffer.from(saltText, "hex"), KEY_LENGTH, {
    N: SCRYPT_N,
    r: SCRYPT_R,
    p: SCRYPT_P,
    maxmem: 64 * 1024 * 1024,
  });
  return timingSafeEqual(expected, actual);
}

export function makeTemporaryPassword(): string {
  return randomBytes(18).toString("base64url");
}

export function makeSessionToken(): string {
  return randomBytes(32).toString("base64url");
}

export function hashSessionToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}
