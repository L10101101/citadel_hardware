# Citadel Desktop Operations Runbook

## 1) Runtime Environment Variables

Optional secret overrides (used before keyring values):

- `CITADEL_LOCAL_DB_PASSWORD`
- `CITADEL_CLOUD_DB_PASSWORD`
- `CITADEL_SMTP_PASSWORD`
- `CITADEL_SMS_APP_API_KEY`
- `CITADEL_FERNET_KEY`

Face/recognition tuning:

- `FACE_VERIFY_SIM_THRESHOLD` (default from code)
- `FACE_IDENTIFY_SIM_THRESHOLD` (default from code)
- `FACE_GALLERY_TTL_SECONDS` (default `300`)
- `FACE_PERF_LOG_EVERY` (default `0`, disabled)
- `FACE_RESULT_METRICS_LOG_EVERY` (default `0`, disabled)
- `FACE_LOCKOUT_TRIGGER_COUNT` (default `10`)
- `FACE_LOCKOUT_SECONDS` (default `1.5`)
- `FACE_LOCKOUT_NOTICE_INTERVAL` (default `0.6`)
- `FACE_JOB_INTERVAL_S` (default `0.05`)
- `CAMERA_DISPLAY_FRAME_INTERVAL_S` (default `0.04`)

Logging format:

- `CITADEL_LOG_FORMAT=text|json` (default `text`)

## 2) Startup Validation Behavior

At desktop startup, runtime config validation checks:

- Local DB name/user/host/password
- Cloud DB name/user/host/password
- Fernet key presence and format

If invalid, app exits with a clear "Configuration Required" dialog.

## 3) Threshold Calibration Workflow

1. Collect genuine and impostor similarity scores into CSV files (one score per row).
2. Run:

```bash
python calibrate_face_threshold.py --genuine genuine.csv --impostor impostor.csv --target-far 0.01
```

3. Set suggested values for:

- `FACE_VERIFY_SIM_THRESHOLD`
- `FACE_IDENTIFY_SIM_THRESHOLD`

4. Restart app and monitor real-world reject/accept behavior.

## 4) Test Commands

Run unit tests:

```bash
python -m unittest discover -s .\tests -p "test_*.py" -v
```

Run pre-release automated checks (compile + tests):

```bash
python pre_release_check.py
```

Current coverage includes:

- Face quality + threshold helper logic
- Runtime config validation
- Sync retry/persist behavior

## 5) Release Checklist

1. Run tests.
2. Verify startup passes config validation.
3. Confirm model files exist and load on target machine.
4. Run a smoke flow:
   - QR -> face verification success
   - failure reasons surface on status label
   - sync queue still uploads
5. Validate logs are generated (text/json as configured).

## 6) Rollback Checklist

1. Keep last known-good executable/build artifacts.
2. Keep previous env var set (thresholds/log format).
3. If new thresholds degrade UX:
   - restore previous `FACE_VERIFY_SIM_THRESHOLD`
   - restore previous `FACE_IDENTIFY_SIM_THRESHOLD`
4. If runtime regressions appear:
   - deploy previous desktop build
   - keep database unchanged
5. Re-run smoke flow and tests after rollback.

