# Citadel Desktop UAT Checklist

## 0) Pre-Run Setup

1. Confirm app launches with current build.
2. Confirm required env vars/config are set.
3. Optional: enable extra metrics/logging for this UAT session only.

## 1) Startup and Configuration

1. Launch app with valid config.
Expected:
- App starts normally.
- No configuration error dialog.

2. Launch with missing/invalid Fernet key (test environment only).
Expected:
- "Configuration Required" dialog appears.
- App exits safely.

## 2) Face Verification Success Path

1. Scan valid QR for enrolled student.
2. Present valid live face.
Expected:
- Face verifies.
- Entry is logged.
- UI updates student details.
- Status shows success.

## 3) Face Failure Guidance

1. Present low-light face.
Expected: status shows `Too dark`.

2. Present blurred face.
Expected: status shows `Too blurry`.

3. Present far/small face.
Expected: status shows `Face too small`.

4. Present invalid/no face.
Expected: status shows `No Face Detected` or `Unrecognized`.

## 4) Lockout Behavior

1. Trigger repeated failed face attempts in one session.
Expected:
- Temporary lockout guidance appears: `Hold still and center your face`.
- Verification resumes after short lockout window.

2. Reset flow (cancel/timeout/new QR).
Expected:
- Lockout and fail streak state reset.

## 5) Sync and Offline Resilience

1. Disconnect network and perform local log events.
Expected:
- App remains responsive.
- No crash during sync/upload attempts.

2. Reconnect network and wait for sync.
Expected:
- Pending uploads retry successfully.
- Logs indicate retry/upload cycle activity.

## 6) Gallery Cache Fallback

1. Force/observe DB connectivity issue while app has existing gallery cache.
Expected:
- Verification continues using stale cache.
- No hard failure due to temporary DB read issue.

## 7) Performance Sanity

1. Verify face flow latency is acceptable under normal lighting.
2. Optional: if enabled, inspect perf logs.
Expected:
- No noticeable lag regression compared with baseline.

## 8) Logging/Observability

1. Confirm app log file is created.
2. If `CITADEL_LOG_FORMAT=json` enabled, validate JSON entries.
3. If `FACE_RESULT_METRICS_LOG_EVERY` enabled, confirm periodic metrics entries.

## 9) Regression Checks

1. Fingerprint verification still works.
2. QR-only exit path still works.
3. Slideshow/idle behavior still works.
4. Emergency mode toggle still works.

## 10) Release Go/No-Go

Go if all are true:

1. Critical flows pass (startup, QR+face success, sync).
2. No crashes/hangs in UAT session.
3. Failure statuses are clear and actionable.
4. Logs are readable and sufficient for troubleshooting.
