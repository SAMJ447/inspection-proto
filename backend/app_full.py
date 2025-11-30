import os
import json
import uuid
import base64
from io import BytesIO
from typing import Any, Dict, List, Optional

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Body,
    Form,
    Query,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    JSONResponse,
    Response,
    HTMLResponse,
    StreamingResponse,
)
from pydantic import BaseModel
from openai import OpenAI
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.utils import ImageReader
from docx import Document

# ===================== Paths / Directories =====================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.getenv("DATA_ROOT", BASE_DIR)

UPLOAD_DIR = os.path.join(DATA_ROOT, "uploads")
ANNOTATION_DIR = os.path.join(DATA_ROOT, "annotations")
TEMPLATE_DIR = os.path.join(DATA_ROOT, "templates")
TRADE_CONFIG_PATH = os.path.join(DATA_ROOT, "trade_configs.json")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ANNOTATION_DIR, exist_ok=True)
os.makedirs(TEMPLATE_DIR, exist_ok=True)

# ===================== FastAPI app & CORS =====================

app = FastAPI(title="Inspection Report Backend")

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://localhost:3000",
    "https://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================== OpenAI client =====================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("WARNING: OPENAI_API_KEY is not set. AI endpoints will fail.")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ===================== Trade config =====================

DEFAULT_TRADE_CONFIG: Dict[str, Dict[str, str]] = {
    "welding": {
        "system_prompt": (
            "You are a NYC special inspector for WELDING. "
            "Write concise, professional inspection reports that reference AWS D1.1, "
            "NYC DOB special inspection style, and project drawings by gridline and detail. "
            "Focus on what was inspected, acceptance/rejection, and any deficiencies."
        ),
        "checklist_template": (
            "- Verify weld sizes and locations match the referenced detail.\n"
            "- Confirm welds are continuous where required and free of visible defects "
            "(cracks, porosity, undercut, slag inclusions).\n"
            "- Confirm base metal and electrodes match project specifications.\n"
            "- Note any deficiencies and required corrective actions."
        ),
    },
    "bolting": {
        "system_prompt": (
            "You are a NYC special inspector for STRUCTURAL STEEL BOLTING (HSB). "
            "Write professional reports referencing RCSC and NYC DOB style. "
            "Focus on bolt type, size, installation method (snug-tight / pretensioned), "
            "and connection locations by gridline and detail."
        ),
        "checklist_template": (
            "- Verify bolt type, diameter, and grade match the referenced detail.\n"
            "- Confirm installation method (snug-tight / pretensioned) and inspection procedure.\n"
            "- Check that all required bolts are installed and properly tensioned.\n"
            "- Note any missing bolts, improper installation, or corrective actions."
        ),
    },
    "detail": {
        "system_prompt": (
            "You are a NYC special inspector reviewing steel DETAILING / LAYOUT "
            "against structural drawings. Verify member sizes, locations by grid, "
            "support conditions, and connection details."
        ),
        "checklist_template": (
            "- Verify member sizes (W-, L-, PL- sections) match drawings.\n"
            "- Confirm locations by gridline, level, and orientation.\n"
            "- Check that clip angles, plates, and support details match referenced details.\n"
            "- Note any deviations or required corrections."
        ),
    },
}


def load_trade_config() -> Dict[str, Dict[str, str]]:
    if os.path.exists(TRADE_CONFIG_PATH):
        try:
            with open(TRADE_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = DEFAULT_TRADE_CONFIG.copy()
            merged.update(data or {})
            return merged
        except Exception as exc:
            print(f"Failed to load trade_configs.json: {exc}")
            return DEFAULT_TRADE_CONFIG.copy()
    return DEFAULT_TRADE_CONFIG.copy()


def save_trade_config(config: Dict[str, Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(TRADE_CONFIG_PATH), exist_ok=True)
    with open(TRADE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


TRADE_CONFIG = load_trade_config()

# ===================== Models =====================

class AnnotationPayload(BaseModel):
    drawing_id: str
    page: int
    annotations: List[Dict[str, Any]]


class OCRCropPayload(BaseModel):
    drawing_id: str
    page: int
    crop: Dict[str, Any]


class ImageReportRequest(BaseModel):
    project_name: str
    inspection_date: str
    trade: str
    area_inspected: Optional[str] = ""
    reference_drawing: Optional[str] = ""
    reference_detail: Optional[str] = ""
    reference_details: Optional[str] = ""
    inspector_notes: Optional[str] = ""


class ImageReportData(BaseModel):
    project_name: str
    inspection_date: str
    trade: str
    area_inspected: str
    reference_details: Optional[str] = ""
    reference_drawing: Optional[str] = ""
    reference_detail: Optional[str] = ""
    overall_summary: str
    detailed_findings: List[Dict[str, Any]]
    conclusion: str
    inspector_notes: Optional[str] = ""
    previous_deficiencies_resolved: Optional[str] = ""


# ===================== Utility: DOCX placeholder helpers =====================

def _replace_placeholders_in_paragraph(paragraph, mapping: Dict[str, str]) -> None:
    if not paragraph.text:
        return
    for key, value in mapping.items():
        if key in paragraph.text:
            for run in paragraph.runs:
                if key in run.text:
                    run.text = run.text.replace(key, value)


def _replace_placeholders_in_table(table, mapping: Dict[str, str]) -> None:
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                _replace_placeholders_in_paragraph(paragraph, mapping)


def _fill_detailed_findings_table(doc: Document, findings: List[Dict[str, Any]]) -> None:
    """
    Look for a table row that contains placeholders like:
    {{ITEM}}, {{OBSERVATION}}, {{CODE_OR_DETAIL_REF}}, {{STATUS}}, {{REMARKS}}
    Then duplicate/fill rows for each item in findings.
    """
    if not findings:
        return

    for table in doc.tables:
        template_row_idx = None
        for row_idx, row in enumerate(table.rows):
            row_text = " ".join(cell.text for cell in row.cells)
            if "{{ITEM}}" in row_text and "{{OBSERVATION}}" in row_text:
                template_row_idx = row_idx
                break

        if template_row_idx is None:
            continue

        needed = len(findings)
        existing_after = len(table.rows) - template_row_idx
        while existing_after < needed:
            table.add_row()
            existing_after += 1

        for i, item in enumerate(findings):
            row = table.rows[template_row_idx + i]
            row_mapping = {
                "{{ITEM}}": item.get("item", ""),
                "{{OBSERVATION}}": item.get("observation", ""),
                "{{CODE_OR_DETAIL_REF}}": item.get("code_or_detail_ref", ""),
                "{{STATUS}}": item.get("status", ""),
                "{{REMARKS}}": item.get("remarks", ""),
            }
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    _replace_placeholders_in_paragraph(paragraph, row_mapping)

        return  # only fill first matching table


def fill_docx_template_from_report(doc: Document, report_data: Dict[str, Any]) -> None:
    """
    Replace simple placeholders and fill findings table.

    Expected placeholders in your DOCX (you can adjust your template):
      {{PROJECT_NAME}}
      {{INSPECTION_DATE}}
      {{TRADE}}
      {{AREA_INSPECTED}}
      {{REFERENCE_DRAWING}}
      {{REFERENCE_DETAIL}}
      {{REFERENCE_DETAILS}}
      {{OVERALL_SUMMARY}}
      {{CONCLUSION}}
      {{INSPECTOR_NOTES}}
      {{PREVIOUS_DEFICIENCIES_RESOLVED}}

    For the findings table, one row should contain:
      {{ITEM}}  {{OBSERVATION}}  {{CODE_OR_DETAIL_REF}}  {{STATUS}}  {{REMARKS}}
    """
    mapping = {
        "{{PROJECT_NAME}}": report_data.get("project_name", ""),
        "{{INSPECTION_DATE}}": report_data.get("inspection_date", ""),
        "{{TRADE}}": report_data.get("trade", ""),
        "{{AREA_INSPECTED}}": report_data.get("area_inspected", ""),
        "{{REFERENCE_DRAWING}}": report_data.get("reference_drawing", ""),
        "{{REFERENCE_DETAIL}}": report_data.get("reference_detail", ""),
        "{{REFERENCE_DETAILS}}": report_data.get("reference_details", ""),
        "{{OVERALL_SUMMARY}}": report_data.get("overall_summary", ""),
        "{{CONCLUSION}}": report_data.get("conclusion", ""),
        "{{INSPECTOR_NOTES}}": report_data.get("inspector_notes", ""),
        "{{PREVIOUS_DEFICIENCIES_RESOLVED}}": report_data.get(
            "previous_deficiencies_resolved", ""
        ),
    }

    for paragraph in doc.paragraphs:
        _replace_placeholders_in_paragraph(paragraph, mapping)

    for table in doc.tables:
        _replace_placeholders_in_table(table, mapping)

    findings = report_data.get("detailed_findings") or []
    if isinstance(findings, list):
        _fill_detailed_findings_table(doc, findings)


# ===================== Routes: Trade config =====================

@app.get("/get-trade-config")
def get_trade_config(trade: str = Query(..., description="Trade key, e.g. welding")):
    cfg = TRADE_CONFIG.get(trade)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Trade '{trade}' not found")
    return cfg


@app.post("/save-trade-config")
def save_trade_config_endpoint(payload: Dict[str, Any] = Body(...)):
    trade = payload.get("trade")
    if not trade:
        raise HTTPException(status_code=400, detail="'trade' is required")

    system_prompt = payload.get("system_prompt", "").strip()
    checklist_template = payload.get("checklist_template", "").strip()

    TRADE_CONFIG[trade] = {
        "system_prompt": system_prompt,
        "checklist_template": checklist_template,
    }
    save_trade_config(TRADE_CONFIG)
    return {"ok": True, "trade": trade}


# ===================== Routes: Annotations (PDF/image) =====================

@app.post("/save-annotations")
def save_annotations(payload: AnnotationPayload):
    drawing_id = payload.drawing_id
    page = payload.page
    annotations = payload.annotations

    if not drawing_id:
        raise HTTPException(status_code=400, detail="drawing_id is required")

    out_path = os.path.join(ANNOTATION_DIR, f"{drawing_id}_page_{page}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"annotations": annotations}, f, indent=2)

    return {"ok": True, "drawing_id": drawing_id, "page": page}


@app.get("/load-annotations")
def load_annotations(drawing_id: str, page: int):
    path = os.path.join(ANNOTATION_DIR, f"{drawing_id}_page_{page}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No annotations for this page")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


# ===================== Routes: OCR stub =====================

@app.post("/ocr-crop")
def ocr_crop(payload: OCRCropPayload):
    crop = payload.crop or {}
    text = (
        f"[OCR stub] Drawing: {payload.drawing_id}, page {payload.page}, "
        f"crop box: x={crop.get('x')}, y={crop.get('y')}, "
        f"w={crop.get('w')}, h={crop.get('h')}"
    )
    return {"text": text}


# ===================== Routes: Export annotated PDF =====================

@app.post("/export-pdf")
def export_pdf(payload: Dict[str, Any] = Body(...)):
    """
    Expect payload:
    {
      "pages": ["data:image/png;base64,...", ...]
    }
    """
    pages = payload.get("pages") or []
    if not pages:
        raise HTTPException(status_code=400, detail="No pages provided")

    buffer = BytesIO()
    pdf = pdf_canvas.Canvas(buffer)

    for encoded in pages:
        if not encoded.startswith("data:image"):
            continue
        header, b64data = encoded.split(",", 1)
        img_bytes = BytesIO(base64.b64decode(b64data))
        img = ImageReader(img_bytes)
        width, height = img.getSize()
        pdf.setPageSize((width, height))
        pdf.drawImage(img, 0, 0, width=width, height=height)
        pdf.showPage()

    pdf.save()
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="annotated.pdf"'},
    )


# ===================== Routes: AI report from annotations (PDF flow) =====================

@app.post("/generate-report")
def generate_report(payload: Dict[str, Any] = Body(...)):
    if not client:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured on the server.",
        )

    trade = payload.get("trade_type") or payload.get("trade") or "welding"
    trade_cfg = TRADE_CONFIG.get(trade, DEFAULT_TRADE_CONFIG["welding"])

    system_prompt = (
        "You are a NYC construction special inspector. "
        "Write clear, professional inspection text based on the provided context. "
        "Use NYC DOB style, reference gridlines and details where possible.\n\n"
        f"TRADE-SPECIFIC INSTRUCTIONS:\n{trade_cfg.get('system_prompt','')}"
    )

    user_context = {
        "trade_type": trade,
        "project_info": payload.get("project_info", ""),
        "page": payload.get("page", 1),
        "annotations": payload.get("annotations", []),
        "ocr_crop": payload.get("ocr_crop", {}),
        "ocr_text": payload.get("ocr_text", ""),
        "checklist_template": payload.get("checklist_template", ""),
    }

    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "instruction": "Return a pure JSON object with keys: "
                                           "report_text, checklist_text, json_items.",
                            "context": user_context,
                        }
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception as exc:
        print(f"/generate-report OpenAI error: {exc}")
        report_text = (
            "Inspection report could not be generated by AI due to an error. "
            "Please draft manually based on project info and annotations."
        )
        checklist_text = payload.get("checklist_template", "")
        return {
            "report_text": report_text,
            "checklist_text": checklist_text,
            "json_items": [],
        }

    return {
        "report_text": data.get("report_text", ""),
        "checklist_text": data.get("checklist_text", ""),
        "json_items": data.get("json_items", []),
    }


# ===================== Routes: Image-based report UI & API =====================

IMAGE_REPORT_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Image-based Inspection Report</title>
  <style>
    body { font-family: sans-serif; margin: 16px; }
    .row { display: flex; gap: 16px; }
    .col { flex: 1; }
    label { display: block; margin-top: 8px; font-weight: 600; }
    input[type="text"], input[type="date"], textarea, select {
      width: 100%; padding: 4px; margin-top: 4px;
    }
    textarea { min-height: 60px; }
    #canvas-container {
      border: 1px solid #ccc;
      width: 100%;
      height: 400px;
      position: relative;
      margin-top: 8px;
    }
    canvas {
      border: 1px solid #aaa;
      width: 100%;
      height: 100%;
      cursor: crosshair;
    }
    .tools button { margin-right: 4px; margin-top: 4px; }
    .output-box {
      white-space: pre-wrap;
      border: 1px solid #ddd;
      padding: 8px;
      min-height: 100px;
      background: #fafafa;
    }
  </style>
</head>
<body>
  <h2>Image-based Inspection Report (Prototype)</h2>
  <div class="row">
    <div class="col">
      <h3>1. Report Inputs</h3>
      <label>Project Name</label>
      <input id="project_name" type="text" />

      <label>Inspection Date</label>
      <input id="inspection_date" type="date" />

      <label>Trade</label>
      <select id="trade">
        <option value="welding">Welding</option>
        <option value="bolting">Bolting / HSB</option>
        <option value="detail">Detail</option>
      </select>

      <label>Area Inspected</label>
      <input id="area_inspected" type="text" placeholder="e.g. 10th Floor, grid D/11-12" />

      <label>Reference Drawing #</label>
      <input id="reference_drawing" type="text" placeholder="e.g. S3.1" />

      <label>Reference Detail #</label>
      <input id="reference_detail" type="text" placeholder="e.g. 5/S3.1" />

      <label>Additional Reference Details (optional)</label>
      <textarea id="reference_details"></textarea>

      <label>Inspector Notes / Special Focus</label>
      <textarea id="inspector_notes"></textarea>

      <h3>2. Upload Images</h3>
      <label>Main Location Image (required)</label>
      <input id="main_image" type="file" accept="image/*" />

      <label>Detail Images (optional)</label>
      <input id="detail_images" type="file" accept="image/*" multiple />
    </div>

    <div class="col">
      <h3>3. Mark-up (Simple Pen)</h3>
      <div class="tools">
        <button onclick="clearCanvas()">Clear</button>
      </div>
      <div id="canvas-container">
        <canvas id="annot_canvas"></canvas>
      </div>

      <h3>4. Actions</h3>
      <button onclick="generateReport()">Generate AI Report</button>
      <button onclick="exportDocx()">Export DOCX</button>

      <h3>AI Overall Summary</h3>
      <div id="overall_summary" class="output-box"></div>

      <h3>AI Detailed Findings JSON</h3>
      <div id="detailed_findings" class="output-box"></div>

      <h3>Conclusion</h3>
      <div id="conclusion" class="output-box"></div>
    </div>
  </div>

<script>
  const API_BASE = "";

  const canvas = document.getElementById("annot_canvas");
  const ctx = canvas.getContext("2d");
  function resizeCanvas() {
    const rect = document.getElementById("canvas-container").getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    ctx.lineWidth = 3;
  }
  window.addEventListener("resize", resizeCanvas);
  resizeCanvas();

  let drawing = false;
  canvas.addEventListener("mousedown", () => { drawing = true; ctx.beginPath(); });
  canvas.addEventListener("mouseup", () => { drawing = false; });
  canvas.addEventListener("mouseleave", () => { drawing = false; });
  canvas.addEventListener("mousemove", (e) => {
    if (!drawing) return;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    ctx.lineTo(x, y);
    ctx.stroke();
  });

  function clearCanvas() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  function getFormDataForReport() {
    const fd = new FormData();
    fd.append("project_name", document.getElementById("project_name").value || "");
    fd.append("inspection_date", document.getElementById("inspection_date").value || "");
    fd.append("trade", document.getElementById("trade").value || "welding");
    fd.append("area_inspected", document.getElementById("area_inspected").value || "");
    fd.append("reference_drawing", document.getElementById("reference_drawing").value || "");
    fd.append("reference_detail", document.getElementById("reference_detail").value || "");
    fd.append("reference_details", document.getElementById("reference_details").value || "");
    fd.append("inspector_notes", document.getElementById("inspector_notes").value || "");

    const mainFile = document.getElementById("main_image").files[0];
    if (mainFile) {
      fd.append("main_image", mainFile);
    }

    const detailList = document.getElementById("detail_images").files;
    for (let i = 0; i < detailList.length; i++) {
      fd.append("detail_images", detailList[i]);
    }

    return fd;
  }

  async function generateReport() {
    const fd = getFormDataForReport();

    try {
      const resp = await fetch(API_BASE + "/generate-report-from-images", {
        method: "POST",
        body: fd
      });
      if (!resp.ok) {
        const txt = await resp.text();
        alert("Error from server: " + txt);
        return;
      }
      const data = await resp.json();
      document.getElementById("overall_summary").textContent = data.overall_summary || "";
      document.getElementById("detailed_findings").textContent = JSON.stringify(
        data.detailed_findings || [],
        null,
        2
      );
      document.getElementById("conclusion").textContent = data.conclusion || "";
    } catch (err) {
      console.error(err);
      alert("Request failed: " + err);
    }
  }

  async function exportDocx() {
    const project_name = document.getElementById("project_name").value || "";
    const inspection_date = document.getElementById("inspection_date").value || "";
    const trade = document.getElementById("trade").value || "welding";
    const area_inspected = document.getElementById("area_inspected").value || "";
    const reference_drawing = document.getElementById("reference_drawing").value || "";
    const reference_detail = document.getElementById("reference_detail").value || "";
    const reference_details = document.getElementById("reference_details").value || "";
    const inspector_notes = document.getElementById("inspector_notes").value || "";

    let detailed_findings = [];
    try {
      detailed_findings = JSON.parse(
        document.getElementById("detailed_findings").textContent || "[]"
      );
    } catch (e) {
      console.warn("Detailed findings JSON parse error", e);
    }

    const payload = {
      project_name,
      inspection_date,
      trade,
      area_inspected,
      reference_drawing,
      reference_detail,
      reference_details,
      inspector_notes,
      overall_summary: document.getElementById("overall_summary").textContent || "",
      detailed_findings: detailed_findings,
      conclusion: document.getElementById("conclusion").textContent || "",
      previous_deficiencies_resolved: ""
    };

    try {
      const resp = await fetch(API_BASE + "/export-report-docx", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!resp.ok) {
        const txt = await resp.text();
        alert("Export error: " + txt);
        return;
      }
      const blob = await resp.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "inspection_report.docx";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
      alert("Export failed: " + err);
    }
  }
</script>
</body>
</html>
"""

@app.get("/image-report-ui", response_class=HTMLResponse)
def image_report_ui():
    return HTMLResponse(content=IMAGE_REPORT_HTML)


# ===================== Routes: AI from images =====================

@app.post("/generate-report-from-images")
async def generate_report_from_images(
    project_name: str = Form(...),
    inspection_date: str = Form(...),
    trade: str = Form("welding"),
    area_inspected: str = Form(""),
    reference_drawing: str = Form(""),
    reference_detail: str = Form(""),
    reference_details: str = Form(""),
    inspector_notes: str = Form(""),
    main_image: UploadFile = File(...),
    detail_images: List[UploadFile] = File([]),
):
    """
    Generate a welding/bolting/detail style report using images and inputs.
    For now, we do not actually send image bytes to OpenAI (prototype),
    but we include filenames and inspector text in the prompt.
    """
    if not client:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured on the server.",
        )

    image_ids: List[str] = []
    for f in [main_image, *detail_images]:
        if not f:
            continue
        ext = os.path.splitext(f.filename or "")[1].lower()
        img_id = f"{uuid.uuid4().hex}{ext or '.jpg'}"
        dest_path = os.path.join(UPLOAD_DIR, img_id)
        content = await f.read()
        with open(dest_path, "wb") as out:
            out.write(content)
        image_ids.append(img_id)

    trade_key = trade or "welding"
    trade_cfg = TRADE_CONFIG.get(trade_key, DEFAULT_TRADE_CONFIG.get("welding"))

    system_prompt = (
        "You are a NYC special inspector writing a concise inspection report.\n"
        "Use professional NYC DOB special inspection style, referencing:\n"
        "- Project name and location\n"
        "- Trade (welding / bolting / detail)\n"
        "- Area inspected, gridlines, and drawing/detail references\n"
        "- Observations and acceptance/rejection\n"
        "- Conclusion summarizing status.\n\n"
        f"TRADE-SPECIFIC INSTRUCTIONS:\n{trade_cfg.get('system_prompt','')}"
    )

    user_payload = {
        "project_name": project_name,
        "inspection_date": inspection_date,
        "trade": trade_key,
        "area_inspected": area_inspected,
        "reference_drawing": reference_drawing,
        "reference_detail": reference_detail,
        "reference_details": reference_details,
        "inspector_notes": inspector_notes,
        "saved_image_ids": image_ids,
        "note": "Images are referenced by filename only in this prototype. "
                "You may infer reasonable welding/bolting/detail conditions based on the text.",
    }

    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "instruction": (
                                "Return a JSON object with keys: "
                                "project_name, inspection_date, trade, area_inspected, "
                                "reference_drawing, reference_detail, reference_details, "
                                "overall_summary, detailed_findings, conclusion, "
                                "inspector_notes, previous_deficiencies_resolved."
                            ),
                            "context": user_payload,
                        }
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception as exc:
        print(f"/generate-report-from-images OpenAI error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    data.setdefault("project_name", project_name)
    data.setdefault("inspection_date", inspection_date)
    data.setdefault("trade", trade_key)
    data.setdefault("area_inspected", area_inspected)
    data.setdefault("reference_drawing", reference_drawing)
    data.setdefault("reference_detail", reference_detail)
    data.setdefault("reference_details", reference_details)
    data.setdefault("inspector_notes", inspector_notes)
    data.setdefault("overall_summary", "")
    data.setdefault("detailed_findings", [])
    data.setdefault("conclusion", "")
    data.setdefault("previous_deficiencies_resolved", "")

    return data


# ===================== Routes: Export DOCX from image-based report =====================

@app.post("/export-report-docx")
def export_report_docx(report: ImageReportData):
    """
    Map the JSON report into a DOCX template.

    Template path (for now):
      templates/<trade>_report_template.docx

    For example:
      templates/welding_report_template.docx
      templates/bolting_report_template.docx
      templates/detail_report_template.docx
    """
    trade_key = (report.trade or "welding").lower()
    template_filename = f"{trade_key}_report_template.docx"
    template_path = os.path.join(TEMPLATE_DIR, template_filename)

    if not os.path.exists(template_path):
        raise HTTPException(
            status_code=404,
            detail=(
                f"No DOCX template found at {template_path}. "
                f"Place a template named {template_filename} in the templates folder."
            ),
        )

    doc = Document(template_path)
    report_dict = report.model_dump()
    fill_docx_template_from_report(doc, report_dict)

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)

    safe_project = (report.project_name or "inspection_report").replace(" ", "_")
    filename = f"{safe_project}_{trade_key}.docx"

    return StreamingResponse(
        buf,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
