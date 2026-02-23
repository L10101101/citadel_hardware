# Citadel Desktop Minimum Release Gate (10-Minute)

Pass all items before release.

## 1) Startup Gate

1. Launch app with production config.
Expected: app opens with no configuration error.

PASS

## 2) Core Verification Gate

1. Scan valid QR + verify live face.
Expected: success status and log entry.

PASS

2. Trigger one failure condition (e.g., dark/blurred).
Expected: specific actionable status (`Too dark` / `Too blurry` / etc.).

PASS

## 3) Stability Gate

1. Run repeated failed attempts briefly.
Expected: temporary lockout guidance appears, then recovers.

PASS

2. Ensure app remains responsive (no freeze/crash).

PASS

## 4) Sync Gate

1. Create at least one entry/exit event.
2. Confirm sync/upload cycle runs (or queues then retries if offline).
Expected: no sync crash; logs show upload/retry behavior.

PASS

## 5) Logging Gate

1. Confirm logs are written.
2. If JSON logging enabled, confirm valid JSON entries.

PASS

## Go / No-Go

Release only if all 5 gates pass.
