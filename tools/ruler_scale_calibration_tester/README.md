# Standalone Ruler Scale Calibration Tester

## 1. Purpose and scope

This engineering tester validates the reusable pipeline:

```text
camera/file image
→ ruler candidate
→ orientation and rectification
→ minor/medium/major ticks
→ numeric OCR
→ OCR/geometry cross-validation
→ robust multi-tick scale fit
→ pixels/mm and µm/pixel
→ scale-bar preview and debug evidence
```

It does **not** modify Recipe execution, polarity checks, SMU output, relay safety,
formal JPG footer generation, or TIFF output. The tester UI calls
`core.calibration.CalibrationService`; future production code must call the same
service rather than copying the algorithms from this tool.

Software implementation and synthetic regression are provided, but real camera
recognition performance still requires the manual acceptance campaign below.

## 2. Installation and launch

The project uses Python 3.11/3.12 and the repository `.venv`.

1. Run the repository `setup_and_run.bat` once to create `.venv` and install
   `requirements.txt`.
2. If OCR is required, explicitly install the optional Python wrapper with
   `.venv\Scripts\python.exe -m pip install -r tools\ruler_scale_calibration_tester\requirements-ocr.txt`.
3. Install the Windows Tesseract executable separately, put `tesseract.exe` on
   `PATH`, then restart the tester. Nothing is downloaded automatically.
4. Close the production Luminescence_System application so only one process owns
   the physical camera.
5. From the repository root, double-click `run_ruler_scale_calibration_tester.bat`.

OpenCV is required by reusable calibration core and remains in root
`requirements.txt`. The launcher never changes system Python and never runs pip automatically. It
keeps the console open on failure.

Command-line alternatives:

```powershell
.\.venv\Scripts\python.exe -m tools.ruler_scale_calibration_tester.main
.\.venv\Scripts\python.exe -m tools.ruler_scale_calibration_tester.batch path\to\images
```

## 3. Camera mode

The tester reuses `gui.camera_controller.CameraController`, including the formal
RisingCam MONO16 pull-mode stream. It does not load `nncam` directly and does not
create a second SDK wrapper.

1. Select **Refresh Cameras**.
2. Select the camera and press **Connect Camera**.
3. Wait for Live View and place the ruler in the sample plane.
4. Press **Capture & Analyze**.
5. Press **Disconnect**, or close the window. Both paths call `close_camera()`.

Camera enumeration/open/read errors are shown as diagnostics and do not terminate
Image File mode. The tester uses the latest independent `uint16 H×W` scientific
frame for analysis. The grayscale QImage is only the preview.

Each camera capture also freezes the controller readbacks available at that time:
Exposure Time, Gain, SDK Auto Exposure state/mode/target, sensor bit depth, raw
alignment, EffectiveDNMax, temperature, and timestamp. An unavailable readback is
stored as JSON `null` with an explicit availability flag; it is never invented.

Every camera **Capture & Analyze** is persisted automatically before calibration
starts. The worker freezes an independent scientific frame, writes its exact TIFF
and a visualization-only PNG, then runs calibration and saves PASS, FAIL, or
exception evidence. Image File mode is not duplicated into this history.

```text
local/ruler_capture_history/
├─ manifest.csv
└─ YYYYMMDD/
   └─ YYYYMMDD_HHMMSS_mmm_frame_004821[_counter]/
      ├─ raw_input.tiff
      ├─ preview.png
      ├─ result.json
      └─ available detector/tick/OCR overlays
```

`raw_input.tiff` is written before the algorithm is called and round-trips camera
`uint16 H×W` values exactly. `result.json` initially records `analysis_pending`,
then is atomically replaced with the complete result. Unexpected exceptions are
recorded as `analysis_exception`; raw and preview remain available. The UI reports
the capture ID, history count, disk use, and folder. History is local-only and is
never deleted automatically.

### Ruler calibration Auto Exposure

Enable **Ruler Auto Exposure** before **Capture & Analyze** to use the standalone
calibration-specific acquisition controller. It reuses the existing
`CameraController` and pull-mode stream; it does not start another SDK stream and
does not change Recipe acquisition.

The controller first freezes the original Exposure, Gain, and SDK Auto Exposure
mode. It then uses manual Exposure at minimum hardware Gain, analyzes each raw
MONO16 frame through the existing `CalibrationService`, and records every attempt
before continuing. The UI shows current Exposure/Gain, attempt number, ruler/tick
saturation, Michelson contrast, and the decision. **Cancel Ruler AE**, window
close, PASS, FAIL, timeout, and exceptions all restore the original camera state.

The first-stage targets are deliberately centralized and marked provisional:

- ruler ROI and tick-band exact-DN clipping: at most 15%;
- median accepted-tick Michelson contrast: at least 0.50;
- normalized accepted-tick contrast: at least 0.14 of EffectiveDNMax;
- two consecutive acceptable frames, with metric change at most 5%, angle change
  at most 2°, and polygon displacement at most 3%;
- at most six Exposure/Gain adjustments, two unchanged-exposure candidate retries,
  and twelve total attempts.

Exposure is the primary control. Gain starts at the camera minimum and is raised
only when Exposure has reached its maximum, tick contrast remains weak, and local
clipping is at most 2%. Clipping always reduces Exposure and never raises Gain.
An unreliable ruler candidate is rejected before brightness metrics can drive the
controller. Good contrast without verified tick hierarchy still FAILs; Auto
Exposure never relaxes the physical scale solver's
`tick_hierarchy_verified`/`ocr_verified` requirement.

These values came from the first ten local real MONO16 captures (five PASS and
five FAIL) and are not final acceptance specifications. The read-only regression
kept all five existing PASS candidates reliable, treated the valid but clipped
frame 32 candidate as reliable, and rejected the known wrong candidates in frames
172, 393, 423, and 453 before AE decisions.

For a repeatable diagnostic-only sweep, close the main application and run:

```powershell
.\.venv\Scripts\python.exe -m tools.ruler_scale_calibration_tester.exposure_sweep_main
```

The sweep uses minimum Gain, nine clamped exposures from 0.25× to 4× the starting
readback, three captures per exposure, and one settling frame. Exact raw frames,
metadata, result JSON, CSV metrics, and a summary are written only below
`local/generated/ruler_exposure_sweeps/`. The original camera state is restored;
the sweep does not tune production thresholds automatically.

## 4. Image File mode

Press **Load Image…** and select PNG, JPEG, TIFF, or TIFF variants supported by
the installed Pillow/tifffile versions. One image is required; unsupported
stacks or dimensions are rejected explicitly. **Analyze Again** repeats the
current input without reloading it.

TIFF normally uses `tifffile`. If an LZW-compressed single image needs the
optional `imagecodecs` package and that package is absent, Image File mode falls
back to Pillow's decoder. It does not install a codec or change system Python.

## 5. Ruler placement

- Use a metal ruler with visible 1 mm ticks and cm numbers.
- The ruler may be horizontal, vertical, rotated, 180° inverted, partially
  visible, or have mild perspective.
- Prefer 20–30 mm or more visible scale. The configured hard minimum is 10 usable
  intervals and a 10 mm span.
- Avoid severe glare, blur, total saturation, deep shadow, and tick occlusion.
- Keep the full calibration span in focus.

**The ruler marking surface must be at the same Z height as the future sample
emission surface.** A different Z height changes optical magnification and causes
a systematic scale error even when the image fit is numerically excellent.

## 6. Coordinate convention

Original image coordinates use `x` rightward and `y` downward. Rectified ruler
coordinates use `u` along the long ruler axis and `v` across the ruler.

Rectification has no arbitrary post-warp resize. It is used for tick/OCR
detection. Every accepted tick center is inverse-transformed through the stored
homography to the original frame, projected onto the detected original ruler
axis, and fitted there. Therefore the reported `pixels/mm` corresponds to the
original stored image plane, not a resized preview or an unexplained rectified
pixel grid.

With real perspective, local original-image magnification can vary along the
ruler. The single reported value is a robust average across the accepted span;
the fit residual and overlay reveal unacceptable variation.

Definitions:

```text
pixels_per_mm = fitted original-image axis pixels per physical millimetre
um_per_pixel  = 1000 / pixels_per_mm
```

Do not resize an overlaid image after drawing its scale bar. If an output size
changes, recompute the scale and bar length for that image plane.

## 7. Algorithm and overlay

Ruler detection combines contour, bright-body, long parallel edge-pair, and
tick-comb candidates with rectangularity, long-edge support, occupied area,
contrast, and a local tick-periodicity cue. A border-touching partial ruler may use a lower visible
aspect ratio only when its area, rectangularity, and tick evidence all pass. A
single Hough line is never treated as sufficient evidence. The independently
estimated tick-comb axis and its disagreement with the selected long axis are
recorded in diagnostics. The candidate overlay labels Top-3 hypotheses and the
selected item; JSON keeps Top-N method, score, aspect, area, rectangularity,
periodicity, contrast, border, edge, and tick-comb evidence. Otsu and percentile
threshold levels/fractions are recorded for multi-scale threshold audit.

The polygon is perspective-warped into a horizontal ROI. Tick detection examines
both edge bands, removes the long ruler border, collects many perpendicular marks,
and classifies their relative lengths. The solver first estimates an image-only
`periodic_pitch_px`, then evaluates 1/2/5/10 mm physical-pitch hypotheses using
position, length hierarchy, periodicity, and OCR. It rejects duplicate/false marks,
tolerates missing marks, and fits the longest usable span using robust residual
rejection. A periodic grid alone is `geometry_periodic_only` and always FAIL;
only `tick_hierarchy_verified` or `ocr_verified` can PASS.

Overlay colors:

- Yellow polygon: selected ruler boundary.
- Magenta line: detected long axis.
- Green points/lines: accepted minor or medium ticks.
- Red points: accepted major ticks.
- Gray crosses: rejected ticks.
- Green OCR boxes: accepted numbers.
- Red OCR boxes: rejected raw OCR; any geometry-derived correction is written as
  `raw → corrected`, never silently substituted.

The `quality_score` is an engineering score, not a probability. Its documented
0–100 composition is ruler detection 25, usable ticks 20, span 15, fit residual
20, grid occupancy 10, and OCR agreement 10. PASS still requires the independent
geometry gates; merely producing a number is insufficient.

## 8. OCR backend

The runtime backend is `pytesseract` with a restricted `0–9` whitelist. Both 0°
and 180° rectified orientations are evaluated, and sequence continuity helps
select an orientation. Multi-character tokens are not limited to 15.

`pytesseract` is a small Python wrapper, but Windows also needs the separately
installed Tesseract executable. This choice avoids automatically downloading
large EasyOCR/PaddleOCR models, large startup costs, and hidden model caches.

If either component is missing, the UI says **OCR unavailable** with the exact
reason. Geometry continues for diagnostic purposes and adds the warning
`ocr_unavailable`; no fake OCR values are generated. OCR is never the sole scale
source. Recognized numbers are associated with major ticks and validated against
10 minor intervals per centimetre. Sequence outliers are rejected and any
suggested correction remains visible in JSON and overlays.

Known OCR limitations include reflective glare, stylized/engraved fonts,
overlapping labels, severe perspective, blur, and digits cropped at the ROI edge.
Real images will determine whether a future bundled, licensed ONNX digit model is
worth the deployment cost.

Deployment comparison used for the first-stage choice:

| Option | Windows setup / offline | Size, CPU, startup | Packaging and project burden | First-stage decision |
| --- | --- | --- | --- | --- |
| OpenCV preprocessing + pytesseract | Small Python wrapper, but explicit external Tesseract install; fully offline afterward | Moderate CPU/startup | Executable discovery must be diagnosed; Apache-2.0 components | Selected as optional, fail-visible backend |
| EasyOCR | Usually pulls PyTorch and model files; model availability must be managed | Large runtime/model and slower cold start | High burden for this Qt desktop package | Not selected |
| PaddleOCR | Large framework/model deployment and model-cache management | Large runtime/model; CPU cost depends on selected pipeline | Highest first-stage packaging burden | Not selected |
| Lightweight ONNX digit OCR | Can be small and fully offline if a licensed model is bundled | Potentially fastest/smallest | Requires model training/provenance, versioning, license, accuracy campaign, and ONNX Runtime | Candidate after real dataset collection |
| Restricted templates/classifier | No external OCR executable and very small | Fast | Brittle across fonts, engraving, glare, focus and cameras; requires representative templates | Useful only as a future secondary hypothesis, not current OCR claim |

All options still require OpenCV-style normalization/segmentation and geometry
validation; changing the OCR backend does not change the public service result.

## 9. Result and scale bar

The panel reports angle, raw/corrected OCR, accepted/rejected ticks, pixels/mm,
µm/pixel, span, RMSE, fit error percent, quality, warnings, and PASS/FAIL reasons.

The scale bar uses the `1 / 2 / 5 × 10^n` series and targets about 20% of the
original width, constrained to 15–25% when a series value exists in that range.
Both physical label and exact rendered pixel length are displayed.

## 10. Debug package

Press **Save Debug Package** after any analysis. The default local convention is:

```text
local/generated/debug/<timestamp>/
├─ raw_input.tiff
├─ original_preview.png
├─ normalized.png
├─ ruler_roi.png
├─ ruler_candidates.png
├─ rectified.png
├─ threshold.png
├─ edges.png
├─ ticks_overlay.png
├─ ocr_overlay.png
├─ final_overlay.png
└─ result.json
```

`raw_input.tiff` is an exact, non-tone-mapped copy of the input array; a MONO16
input reloads as the same `uint16` values. `result.json` includes timestamp,
dtype/min/max, source identity, periodic/physical pitch hypotheses, resolution, algorithm version, coordinate
convention, polygon/angle, raw and accepted OCR, corrections, accepted/rejected
ticks, fitted mm indices, scale, span, residuals, quality-score definition,
warnings, and failure reasons. Debug images, captures, datasets, and OCR caches
under `local/` are ignored by Git.

## 11. Batch offline regression

```powershell
.\.venv\Scripts\python.exe -m tools.ruler_scale_calibration_tester.batch dataset
.\.venv\Scripts\python.exe -m tools.ruler_scale_calibration_tester.batch dataset --json local\generated\batch.json
.\.venv\Scripts\python.exe -m tools.ruler_scale_calibration_tester.batch dataset --save-debug-failures
```

The command recursively finds PNG/JPEG/TIFF images and reports image count,
ruler detections, usable OCR, successful calibration, mean pixels/mm, sample SD,
CV, and categorized failure reasons. It returns nonzero when any image fails,
making it suitable for regression automation.

For a detailed local-only dataset audit, use:

```powershell
.\.venv\Scripts\python.exe -m tools.ruler_scale_calibration_tester.analyze_real_dataset dataset --output local\generated\ruler_real_dataset
```

This writes `results.csv`, `results.json`, `summary.txt`, a contact sheet, and
per-image debug artifacts. An optional `ground_truth.csv` beside the images may
contain `filename,roi_correct,roi_status,failure_category,false_pass,wrong_scale,notes`;
`roi_status` supports `correct`, `incorrect`, and `uncertain`. Its review prevents
a numerically successful but visibly wrong candidate from being counted as
correct. Reports also flag scale outliers and possible 0.5×/2×/5×/10× aliases,
but never auto-correct them.

The repository-local `/ruler/` directory is explicitly ignored. Real images,
sidecars, manual ground truth, generated overlays, crops, and reports must remain
under ignored `ruler/` or `local/generated/` paths and must never be staged,
committed, copied into tests, or embedded in source/documentation.

## 12. Repeatability mode

Analysis never appends a run automatically. After reviewing a physically verified
PASS, press **Add as Repeatability Run**. The same captured frame/file identity
cannot be added twice. **Export Repeatability CSV** writes UTF-8 per-run evidence
and summary statistics. The panel
reports N, mean pixels/mm, sample SD, CV %, min, max, and maximum deviation from
the mean. **This phase intentionally asserts no repeatability acceptance
threshold.** Use **Clear Repeatability Runs** before a new optical setup.

For a valid placement experiment, keep camera, lens, focus, resolution, and
working distance unchanged; remove and replace the ruler at a random XY position
and angle for every run.

## 13. Manual real-camera acceptance sheet

Record `Detected?`, OCR numbers, pixels/mm, µm/pixel, fit error, PASS/FAIL, and
failure reason for every item:

- [ ] ruler horizontal
- [ ] ruler vertical
- [ ] +30°
- [ ] -30°
- [ ] +45°
- [ ] +70°
- [ ] 180° upside down
- [ ] ruler at upper-left
- [ ] ruler at lower-right
- [ ] only partial ruler visible
- [ ] 2 cm visible
- [ ] 3+ cm visible
- [ ] mild glare
- [ ] different white-light brightness
- [ ] repeated random placement ×20

Suggested table:

| Run / condition | Detected? | OCR numbers | px/mm | µm/px | Fit error % | PASS/FAIL | Failure reason |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| 01 | | | | | | | |

Synthetic tests validate math and control logic only. They do not establish real
ruler recognition accuracy, and no accuracy percentage should be published until
this sheet is completed with representative camera data.

## 14. Future production integration (not implemented here)

The next phase may design:

```text
safe initialization
→ pause for ruler placement
→ white light
→ camera frame
→ CalibrationService
→ operator reviews overlay/result
→ operator accepts
→ pause for ruler removal
→ ruler removal check
→ polarity check
→ remaining Recipe
→ that run's calibration drives JPG footer scale bar
```

No part of that production sequence is implemented by this standalone tool.
