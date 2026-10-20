import { describe, expect, it } from "vitest";
import { generateKey, hashKey, keyPrefix } from "./keys";

// The API server (Python, retrack_server.api_keys) must accept keys made here, so the
// prefix and hash must match it exactly. Vector computed with hash_key(secret, "test-pepper").
const SECRET = "rtk_live_" + "0123456789abcdef".repeat(3);

describe("API keys", () => {
  it("hashes exactly like the API server", () => {
    expect(hashKey(SECRET, "test-pepper")).toBe(
      "a194a576b8998e1cfedac0d979dd8f08ad35f9863fd372b5d33b9a6c67eaf1f2",
    );
  });

  it("uses the same prefix as the API server", () => {
    expect(keyPrefix(SECRET)).toBe("rtk_live_01234567");
  });

  it("generates well-formed, unique live keys", () => {
    const a = generateKey();
    const b = generateKey();
    expect(a.secret).toMatch(/^rtk_live_[0-9a-f]{48}$/);
    expect(a.prefix).toBe(a.secret.slice(0, 17));
    expect(a.secret).not.toBe(b.secret);
  });

  it("refuses an empty pepper and malformed secrets", () => {
    expect(() => hashKey(SECRET, "")).toThrow();
    expect(() => keyPrefix("rtk_live_short")).toThrow();
  });
});
