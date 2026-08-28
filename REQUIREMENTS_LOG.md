# Requirements Log

## CLQ-001 — Standalone Camera Linearity Qualification

- Requested: 2026-08-28
- Scope: `tools/camera_linearity_qualification/` and standalone root launcher only.
- Acceptance: Existing CameraController/CameraCaptureBridge MONO16 stream; guided Light/Dark capture;
  fixed ROI; versioned criteria; RAW/dark/exposure/gain/repeatability/compression/transition/HDR analysis;
  PASS/CONDITIONAL PASS/FAIL; gated camera profile; reports; fake/synthetic automated tests.
- Production boundaries: no Recipe, SMU, Relay, EL Matrix runner, or production output integration.
- Status: Implemented in software; real RisingCam + stable flat-field acceptance remains required.
