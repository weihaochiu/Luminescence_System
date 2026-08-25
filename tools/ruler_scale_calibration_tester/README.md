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
2. Install the Windows Tesseract executable separately if OCR is required.
3. Put `tesseract.exe` on `PATH`, then restart the tester.
4. Close the production Luminescence_System application so only one process owns
   the physical camera.
5. Double-click `run_ruler_scale_tester.bat`.

The launcher never changes system Python and never runs pip automatically. It
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

## 4. Image File mode

Press **Load Image…** and select PNG, JPEG, TIFF, or TIFF variants supported by
the installed Pillow/tifffile versions. One image is required; unsupported
stacks or dimensions are rejected explicitly. **Analyze Again** repeats the
current input without reloading it.

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

Ruler detection combines elongated contour geometry, rectangularity, long-edge
support, occupied area, contrast, and a local tick-periodicity cue. A single
Hough line is never treated as sufficient evidence.

The polygon is perspective-warped into a horizontal ROI. Tick detection examines
both edge bands, removes the long ruler border, collects many perpendicular marks,
and classifies their relative lengths. The solver estimates the fundamental 1 mm
grid, rejects duplicate/false marks, tolerates missing marks, and fits the longest
usable span using robust residual rejection.

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
├─ original.png
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

`result.json` includes timestamp, resolution, algorithm version, coordinate
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

## 12. Repeatability mode

Every successful GUI analysis is appended as Run 01, Run 02, and so on. The panel
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
