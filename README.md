# Disaster OS

A web service that takes a before and after pair of aerial or satellite images of a place, sends both to a Gemini vision model, and returns an annotated image plus a structured damage report: probable cause, affected structures, resource estimates and a phased recovery outline.

After a typhoon or an earthquake in Taiwan, the imagery of a hit area usually exists before anyone has read it. The idea here was to see how much of that first reading a vision model can do: give it the same scene before and after, ask it what changed and what that implies for a response, and force the answer into a fixed JSON schema so a UI can render it. The satellite imagery can be pulled automatically by place name or by clicking a map, so a report can be produced without having any files on hand.

Everything this service outputs is model-generated inference, not measurement. Damage percentages, cost estimates and resource quantities are text a language model produced from two pictures; none of it is verified against ground truth, official assessments, or sensor data. This is a student project for exploring vision models applied to disaster imagery, and it must not be used to make real emergency or resource decisions.

## Project family

This repository sits alongside four fall detection repositories. It shares the emergency-response theme and one technique, and shares no code with them.

| Repo | Role |
| --- | --- |
| **Disaster-OS** (this repo) | Post-disaster aerial image analysis. FastAPI service plus a single-page frontend, deployable to Render. |
| [FD-Online](https://github.com/AriesHongHuanWu/FD-Online) | Browser fall detection, [live](https://arieshonghuanwu.github.io/FD-Online/). The pattern used here, sending an image to a vision model and rendering the structured answer, was first tried there on fall snapshots. |
| [FD-PD](https://github.com/AriesHongHuanWu/FD-PD) | Browser fall detection rebuilt as modules, with pose telemetry and a Kalman-filtered skeleton. |
| [falldetection](https://github.com/AriesHongHuanWu/falldetection) | Desktop Python fall detector using YOLOv8. The original implementation of that line. |
| [FDdemo](https://github.com/AriesHongHuanWu/FDdemo) | The desktop detector repackaged to run offline. |

The fall detection projects watch one room in real time. This one looks at one place, once, after the fact. The common thread is turning imagery into something a responder could act on.

## How it works

Two files carry the application: `main.py` (195 lines, FastAPI) and `index.html` (390 lines, no framework).

### Backend

| Route | Behaviour |
| --- | --- |
| `GET /` | Serves `index.html` with no-cache headers |
| `GET /api/health` | Liveness probe, wired to `healthCheckPath` in `render.yaml` |
| `POST /api/segment` | The analysis endpoint |

`segment_image()` accepts a multipart form with `file` (the current image), an optional `file_before` (the historical baseline), and free-text `location` and `coordinates`. If only a before image arrives it is promoted to the current one, so a single-image request still works.

Both images are opened with Pillow and placed into the prompt in order, each labelled, so the model is told which is which. The prompt pins an exact JSON schema and asks for Traditional Chinese values:

```
disaster_probabilities     cause plus percentage
live_disaster_verification status plus a summary
estimated_cost             string
bounding_boxes             label, severity, colour, shape_type, box
infrastructure_analysis    affected structures
rescue_innovations         drone drop points, shelters, medical stations
recovery_plan              phased steps
resource_estimating        item, quantity, urgency
secondary_disasters        warning plus probability
```

The response is stripped of any markdown fence with a regex, then parsed by `json.loads`. A parse failure falls through to a labelled placeholder object rather than a 500, so the frontend always has something renderable.

The boxes come back in Gemini's normalized `[ymin, xmin, ymax, xmax]` convention on a 0 to 1000 scale, and the drawing step rescales them to pixels. Rendering happens twice on purpose: a translucent fill is drawn onto a separate RGBA overlay, and a solid outline onto the source image, then `Image.alpha_composite()` merges them. That keeps the outline crisp while the fill stays see-through. Regions marked `shape_type: "line"` are drawn as thick lines instead, for things like a severed road. The composite is JPEG encoded, base64 encoded, and returned inside the JSON as a data URI, so the client needs one request and no static file storage.

There is a deliberate quota path: if the Gemini call fails with a 429, the handler returns a complete mock report whose text says, in the payload itself, that it is simulated demonstration data. That keeps a live demo from dying mid-presentation without ever passing fake output off as real analysis.

### Frontend

Three pages behind a sidebar, all in `index.html`, all in Traditional Chinese.

- **Analysis.** Two upload slots, before and after. `autoFetchSatellite()` can fill either one without a local file: it geocodes the typed place name through Nominatim, then requests an 800x800 JPEG from the ArcGIS World Imagery export endpoint for a small bounding box around the result. Results render into tabs for infrastructure, secondary risks, rescue, resources and recovery plan.
- **Satellite view.** A Leaflet map on Esri World Imagery tiles. Clicking anywhere offers to carry those coordinates back to the analysis page.
- **Saved analyses.** Reports are kept in `localStorage` under `disaster_history` with the annotated image inlined, so they survive a reload on the same browser.

## Tech stack

From `requirements.txt`: FastAPI 0.104.1, Uvicorn 0.24.0, `python-multipart`, Pillow 10.4.0, NumPy 1.26.4, `google-generativeai`. The frontend uses Leaflet 1.9.4 and Google Material Symbols from CDNs. `runtime.txt` pins Python 3.11.9.

## Getting started

```bash
git clone https://github.com/AriesHongHuanWu/Disaster-OS.git
cd Disaster-OS
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

A Google AI Studio API key is required. The service reads it from the environment and has no fallback:

```bash
export GOOGLE_API_KEY=...     # Windows: set GOOGLE_API_KEY=...
python main.py                # serves on http://localhost:8005
```

`main.py` binds port 8005 when run directly. `Procfile` and `render.yaml` use `uvicorn main:app --host 0.0.0.0 --port $PORT` instead, which is what a platform such as Render needs. `render.yaml` describes a free-plan web service in the Singapore region with `/api/health` as the health check; deploying is a matter of pointing Render at the repo and setting `GOOGLE_API_KEY` in its environment.

## Status and limitations

A working prototype, six commits between May 11 and 13, 2026. The full path from image upload to annotated report runs end to end. What it is not:

- **Not a measurement system.** Cost figures, damage percentages and resource quantities are model output. There is no ground truth anywhere in this repository, no evaluation, and therefore no accuracy claim.
- **`live_disaster_verification` does not verify anything.** The field asks the model to state whether a disaster occurred at that location, from its own training data and the image. It is not connected to news, to an official feed, or to any live source, and it can be confidently wrong.
- **Localization quality varies.** Gemini's bounding boxes are approximate, and the rescale from the 0 to 1000 grid assumes the model respects that convention. Boxes that fail to parse are skipped silently.
- **Model id is pinned in code** as `gemini-3-flash-preview` in `main.py`. Preview model names change.
- **No authentication, no rate limiting, no request size cap.** Any caller can spend the deployment's Gemini quota.
- **Server-side state is nil.** Nothing is stored on the backend; history lives only in the visitor's browser.
- **Auto-fetched satellite imagery is current imagery.** The before slot is filled from the same live tile service as the after slot, so real before-and-after comparison needs a genuine historical image supplied by hand.
- **Not implemented:** user accounts, PDF or report export, any GIS integration, any official data feed.

## License

MIT. See [LICENSE](LICENSE).
