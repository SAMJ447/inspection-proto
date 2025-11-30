from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()  # 👈 name MUST be `router`


@router.get("/image-report-ui", response_class=HTMLResponse)
async def image_report_ui():
    """
    Simple HTML UI to:
    - enter project/inspection info
    - upload main image + detail images
    - call /generate-report-from-images
    - display structured report result
    """
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>Image-Based Inspection Report</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
        :root {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            color-scheme: light dark;
        }
        body {
            margin: 0;
            padding: 0;
            background: #0f172a;
            color: #e5e7eb;
        }
        .page {
            max-width: 1100px;
            margin: 0 auto;
            padding: 24px 16px 48px;
        }
        h1 {
            margin-top: 0;
            font-size: 1.8rem;
        }
        h2 {
            font-size: 1.3rem;
            margin-top: 1.5rem;
        }
        .card {
            background: #020617;
            border-radius: 12px;
            padding: 16px 20px;
            border: 1px solid #1e293b;
            box-shadow: 0 10px 35px rgba(15, 23, 42, 0.8);
        }
        .grid {
            display: grid;
            grid-template-columns: 1.2fr 1fr;
            gap: 18px;
        }
        .grid-2 {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
        }
        label {
            display: block;
            font-size: 0.85rem;
            margin-bottom: 4px;
            color: #cbd5f5;
        }
        input[type="text"],
        input[type="date"],
        select,
        textarea {
            width: 100%;
            padding: 8px 10px;
            border-radius: 8px;
            border: 1px solid #1f2937;
            background: #020617;
            color: #e5e7eb;
            font-size: 0.9rem;
            box-sizing: border-box;
        }
        textarea {
            resize: vertical;
            min-height: 80px;
        }
        input[type="file"] {
            width: 100%;
            border-radius: 8px;
            border: 1px dashed #334155;
            padding: 10px;
            background: #020617;
            color: #e5e7eb;
            font-size: 0.9rem;
            box-sizing: border-box;
        }
        .field {
            margin-bottom: 10px;
        }
        .btn-row {
            margin-top: 8px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        button {
            border-radius: 999px;
            border: none;
            padding: 8px 18px;
            background: #2563eb;
            color: #f9fafb;
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        button:disabled {
            opacity: 0.6;
            cursor: default;
        }
        button.secondary {
            background: transparent;
            border: 1px solid #4b5563;
        }
        .pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 3px 8px;
            border-radius: 999px;
            border: 1px solid #1f2937;
            font-size: 0.7rem;
            color: #9ca3af;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 999px;
        }
        .status-ACCEPTED { background: #22c55e; }
        .status-REJECTED { background: #ef4444; }
        .status-OPEN { background: #eab308; }
        .small {
            font-size: 0.8rem;
            color: #9ca3af;
        }
        .report-block {
            border-radius: 10px;
            border: 1px solid #1f2937;
            padding: 10px 12px;
            background: #020617;
            font-size: 0.9rem;
            white-space: pre-wrap;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
            margin-top: 4px;
        }
        th, td {
            border: 1px solid #1f2937;
            padding: 6px 8px;
            vertical-align: top;
        }
        th {
            background: #020617;
            font-weight: 500;
            text-align: left;
        }
        .badge {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            border-radius: 999px;
            padding: 2px 8px;
            font-size: 0.7rem;
            border: 1px solid #4b5563;
        }
        .fade {
            opacity: 0.6;
        }
        .error {
            color: #fecaca;
            font-size: 0.85rem;
            margin-top: 4px;
        }
        @media (max-width: 900px) {
            .grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
<div class="page">
    <h1>Image-Based Welding / Bolting Report</h1>
    <p class="small fade">
        Upload one <strong>main drawing/connection image</strong> plus optional
        <strong>detail images</strong>. The backend will call
        <code>/generate-report-from-images</code> and use GPT-Vision to draft a
        professional inspection report.
    </p>

    <div class="card">
        <div class="grid">
            <!-- LEFT: FORM -->
            <div>
                <h2>1. Inspection Inputs</h2>
                <form id="image-report-form" enctype="multipart/form-data">
                    <div class="grid-2">
                        <div class="field">
                            <label for="project_name">Project name</label>
                            <input type="text" id="project_name" name="project_name"
                                   placeholder="123 Main St – Sidewalk Framing" required />
                        </div>
                        <div class="field">
                            <label for="inspection_date">Inspection date</label>
                            <input type="date" id="inspection_date" name="inspection_date" required />
                        </div>
                    </div>

                    <div class="grid-2">
                        <div class="field">
                            <label for="trade">Trade</label>
                            <select id="trade" name="trade" required>
                                <option value="welding">Welding</option>
                                <option value="bolting">Bolting / HSB</option>
                                <option value="welding_bolting">Welding + Bolting</option>
                                <option value="anchors">Anchors</option>
                                <option value="rebar">Rebar</option>
                                <option value="masonry">Masonry</option>
                            </select>
                        </div>
                        <div class="field">
                            <label for="area_inspected">Area inspected (gridlines / level)</label>
                            <input type="text" id="area_inspected" name="area_inspected"
                                   placeholder="Gridline D/11–12 – sidewalk steel frame" required />
                        </div>
                    </div>

                    <div class="field">
                        <label for="reference_details">Reference details / sections</label>
                        <input type="text" id="reference_details" name="reference_details"
                               placeholder="Detail 5/S3.1, Detail 2/S4.2" />
                    </div>

                    <div class="field">
                        <label for="inspector_notes">On-site inspector notes</label>
                        <textarea id="inspector_notes" name="inspector_notes"
                                  placeholder="Welds appear continuous; no visible undercut; bolts snug-tight; no rotation of plies."></textarea>
                    </div>

                    <hr style="border: 0; border-top: 1px solid #1f2937; margin: 12px 0;" />

                    <div class="field">
                        <label for="main_image">
                            Main image (required)
                            <span class="small fade">– drawing crop / connection overview</span>
                        </label>
                        <input type="file" id="main_image" name="main_image" accept="image/*" required />
                    </div>

                    <div class="field">
                        <label for="detail_images">
                            Detail images (optional)
                            <span class="small fade">– callouts, close-ups, detail bubbles</span>
                        </label>
                        <input type="file" id="detail_images" name="detail_images"
                               accept="image/*" multiple />
                    </div>

                    <div class="btn-row">
                        <button type="submit" id="submit-btn">
                            <span id="btn-label">⚙️ Generate AI Report from Images</span>
                        </button>
                        <span id="status-pill" class="pill">
                            <span class="status-dot status-OPEN"></span>
                            <span id="status-text">Idle</span>
                        </span>
                    </div>
                    <div id="form-error" class="error" style="display:none;"></div>
                </form>
            </div>

            <!-- RIGHT: REPORT PREVIEW -->
            <div>
                <h2>2. Report Preview</h2>
                <p class="small fade">
                    After generation, the AI output appears here. You can later plug the same
                    JSON into your DOCX report templates.
                </p>

                <div class="field">
                    <label>Overall summary</label>
                    <div id="overall_summary" class="report-block small fade">
                        No report generated yet.
                    </div>
                </div>

                <div class="field">
                    <label>Detailed findings</label>
                    <div id="findings_container" class="report-block">
                        <span class="small fade">No findings yet.</span>
                    </div>
                </div>

                <div class="field">
                    <label>Conclusion</label>
                    <div id="conclusion" class="report-block small fade">
                        No conclusion yet.
                    </div>
                </div>

                <div class="field">
                    <label class="small">Raw JSON (for debugging / DOCX mapping)</label>
                    <textarea id="raw_json" readonly class="small"
                              style="min-height: 80px;"></textarea>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
(function() {
    const form = document.getElementById("image-report-form");
    const submitBtn = document.getElementById("submit-btn");
    const btnLabel = document.getElementById("btn-label");
    const statusPill = document.getElementById("status-pill");
    const statusText = document.getElementById("status-text");
    const formError = document.getElementById("form-error");

    const overallSummaryEl = document.getElementById("overall_summary");
    const findingsContainer = document.getElementById("findings_container");
    const conclusionEl = document.getElementById("conclusion");
    const rawJsonEl = document.getElementById("raw_json");

    function setStatus(text) {
        statusText.textContent = text;
    }

    function setLoading(isLoading) {
        submitBtn.disabled = isLoading;
        if (isLoading) {
            btnLabel.textContent = "⏳ Generating...";
            setStatus("Calling /generate-report-from-images");
        } else {
            btnLabel.textContent = "⚙️ Generate AI Report from Images";
        }
    }

    function renderFindings(detailedFindings) {
        if (!Array.isArray(detailedFindings) || detailedFindings.length === 0) {
            findingsContainer.innerHTML =
                '<span class="small fade">No detailed findings in response.</span>';
            return;
        }

        let html = '<table><thead><tr>' +
            '<th>Item</th><th>Observation</th><th>Ref</th><th>Status</th><th>Remarks</th>' +
            '</tr></thead><tbody>';

        for (const f of detailedFindings) {
            const status = (f.status || "").toUpperCase();
            const cls = status ? "status-" + status : "";
            html += "<tr>";
            html += "<td>" + (f.item || "") + "</td>";
            html += "<td>" + (f.observation || "") + "</td>";
            html += "<td>" + (f.code_or_detail_ref || "") + "</td>";
            html += '<td><span class="badge">' +
                '<span class="status-dot ' + cls + '"></span>' +
                (status || "N/A") +
                "</span></td>";
            html += "<td>" + (f.remarks || "") + "</td>";
            html += "</tr>";
        }

        html += "</tbody></table>";
        findingsContainer.innerHTML = html;
    }

    form.addEventListener("submit", async function (e) {
        e.preventDefault();
        formError.style.display = "none";
        formError.textContent = "";
        setLoading(true);

        const formData = new FormData(form);

        try {
            const resp = await fetch("/generate-report-from-images", {
                method: "POST",
                body: formData
            });

            if (!resp.ok) {
                const text = await resp.text();
                throw new Error("HTTP " + resp.status + ": " + text);
            }

            const data = await resp.json();
            const report = data.report_data || data;

            overallSummaryEl.classList.remove("fade");
            conclusionEl.classList.remove("fade");

            overallSummaryEl.textContent = report.overall_summary || "(no overall_summary)";
            conclusionEl.textContent = report.conclusion || "(no conclusion)";

            renderFindings(report.detailed_findings);

            rawJsonEl.value = JSON.stringify(report, null, 2);

            setStatus("Report generated");
        } catch (err) {
            console.error(err);
            formError.style.display = "block";
            formError.textContent = "Error generating report: " + err.message;
            setStatus("Error");
        } finally {
            setLoading(false);
        }
    });
})();
</script>

</body>
</html>
    """
    return HTMLResponse(html)
