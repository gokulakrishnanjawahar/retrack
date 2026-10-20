// Per-project API keys, made exactly like the API server's (server/src/retrack_server/api_keys.py):
// `rtk_live_<48 hex>`, found by a 17-character prefix, stored only as HMAC-SHA256(pepper, secret).
// Server-side only: the pepper never reaches the browser.
import { createHmac, randomBytes } from "node:crypto";

const KEY_RE = /^rtk_(live|test)_[0-9a-f]{48}$/;
const PREFIX_LENGTH = "rtk_live_".length + 8;

export type GeneratedKey = { secret: string; prefix: string };

export function generateKey(env: "live" | "test" = "live"): GeneratedKey {
  const secret = `rtk_${env}_${randomBytes(24).toString("hex")}`;
  return { secret, prefix: keyPrefix(secret) };
}

export function keyPrefix(secret: string): string {
  if (!KEY_RE.test(secret)) throw new Error("not a Retrack API key");
  return secret.slice(0, PREFIX_LENGTH);
}

export function hashKey(secret: string, pepper: string): string {
  if (!pepper) throw new Error("pepper must not be empty");
  return createHmac("sha256", pepper).update(secret).digest("hex");
}
