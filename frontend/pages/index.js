// frontend/pages/index.js
import { useEffect, useRef, useState } from "react";

const API_BASE = "http://localhost:8000";

const TRADE_OPTIONS = [
  { value: "welding", label: "Welding" },
  { value: "bolting", label: "Bolting / HSB" },
  { value: "detail", label: "Detail (same structural drawing)" },
  { value: "rebar", label: "Cast-in-place concrete / rebar" },
  { value: "masonry", label: "Masonry" },
  { value: "cold_formed", label: "Cold-formed steel" },
  { value: "anchors", label: "Post-installed anchors" },
  { value: "frp", label: "Fire-resistance penetrations & joints" },
  { value: "sfrm", label: "Sprayed fire-resistive materials (SFRM)" },
];

export default function InspectionToolPage() {
  const canvasRef = useRef(null);      // visible drawing + annotations
  const imgRef = useRef(null);         // hidden <img> base drawing
  const pdfjsLibRef = useRef(null);
  const pdfDocRef = useRef(null);
  const pdfArrayBufferRef = useRef(null);

  const [drawingId, setDrawingId] = useState(null);
  const [fileName, setFileName] = useState("");
  const [isPdf, setIsPdf] = useState(false);
  const [numPages, setNumPages] = useState(1);
  const [currentPage, setCurrentPage] = useState(1);
  const [baseImageUrl, setBaseImageUrl] = useState(null);
  const [imgNaturalSize, setImgNaturalSize] = useState({ w: 0, h: 0 });

  // shapes: all coordinates in IMAGE SPACE (naturalWidth/naturalHeight)
  const [shapes, setShapes] = useState([]); // {id,page,type,x,y,w,h,...}
  const [selectedShapeId, setSelectedShapeId] = useState(null);

  const [tool, setTool] = useState("select"); // select | rect | highlight | arrow | text | callout | check | cross | ocr
  const [strokeColor, setStrokeColor] = useState("#ff0000");
  const [fillColor, setFillColor] = useState("#ffff00");
  const [textColor, setTextColor] = useState("#000000");

  const [zoom, setZoom] = useState(1);
  // we intentionally DISABLE pan for now to keep alignment correct
  const pan = { x: 0, y: 0 };

  const dragStateRef = useRef({
    mode: null, // "draw" | "ocr"
    startX: 0,
    startY: 0,
    shapeId: null,
  });

  const [history, setHistory] = useState([]);

  const [ocrRect, setOcrRect] = useState(null); // {page,x,y,w,h}
  const [ocrText, setOcrText] = useState("");

  const [selectedTrade, setSelectedTrade] = useState("welding");
  const [tradePrompt, setTradePrompt] = useState("");
  const [checklistTemplate, setChecklistTemplate] = useState("");
  const [projectInfo, setProjectInfo] = useState(
    "Steel frame around gridline D/11–12."
  );

  const [reportText, setReportText] = useState("");
  const [checklistText, setChecklistText] = useState("");
  const [aiItems, setAiItems] = useState([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [aiError, setAiError] = useState("");

  // load pdf.js
  useEffect(() => {
    let mounted = true;
    async function loadPdfJs() {
      if (typeof window === "undefined") return;
      try {
        const pdfModule = await import("pdfjs-dist/build/pdf");
        if (!mounted) return;
        pdfjsLibRef.current = pdfModule;
        pdfModule.GlobalWorkerOptions.workerSrc =
          "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
      } catch (e) {
        console.error("Failed to load pdf.js", e);
      }
    }
    loadPdfJs();
    return () => {
      mounted = false;
    };
  }, []);

  function nextShapeId() {
    return `shape_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  }

  function getVisibleShapes() {
    return shapes.filter((s) => s.page === currentPage);
  }

  function getCanvas() {
    return canvasRef.current;
  }

  function pushHistory(prevShapes) {
    setHistory((h) => {
      const copy = [...h, prevShapes];
      if (copy.length > 30) copy.shift();
      return copy;
    });
  }

  function handleUndo() {
    setHistory((h) => {
      if (h.length === 0) return h;
      const prev = h[h.length - 1];
      setShapes(prev);
      setSelectedShapeId(null);
      return h.slice(0, h.length - 1);
    });
  }

  function getImageCoords(evt) {
    const canvas = getCanvas();
    if (!canvas || imgNaturalSize.w === 0) return { x: 0, y: 0 };

    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const cx = (evt.clientX - rect.left) * scaleX;
    const cy = (evt.clientY - rect.top) * scaleY;

    // no pan; just zoom
    const ix = cx / zoom;
    const iy = cy / zoom;

    return { x: ix, y: iy };
  }

  function drawShape(ctx, shape, isSelected, zoomFactor = 1) {
    const scale = zoomFactor;
    const toCx = (v) => v * scale;

    if (shape.type === "rect" || shape.type === "highlight") {
      const x = toCx(shape.x);
      const y = toCx(shape.y);
      const w = toCx(shape.w || 0);
      const h = toCx(shape.h || 0);

      if (shape.type === "highlight") {
        ctx.save();
        ctx.fillStyle = shape.fill || "rgba(255,255,0,0.3)";
        ctx.strokeStyle = shape.stroke || "rgba(255,255,0,0.8)";
        ctx.lineWidth = 2;
        ctx.fillRect(x, y, w, h);
        ctx.strokeRect(x, y, w, h);
        ctx.restore();
      } else {
        ctx.save();
        ctx.strokeStyle = shape.stroke || "#ff0000";
        ctx.lineWidth = 2;
        ctx.strokeRect(x, y, w, h);
        ctx.restore();
      }

      if (isSelected) {
        ctx.save();
        ctx.setLineDash([4, 2]);
        ctx.strokeStyle = "#00aaff";
        ctx.strokeRect(x - 3, y - 3, w + 6, h + 6);
        ctx.restore();
      }
    } else if (shape.type === "check" || shape.type === "cross") {
      const size = (shape.size || 24) * scale;
      const x = toCx(shape.x);
      const y = toCx(shape.y);

      ctx.save();
      ctx.lineWidth = 3;
      ctx.strokeStyle = shape.type === "check" ? "green" : "red";
      ctx.beginPath();
      if (shape.type === "check") {
        ctx.moveTo(x, y + size * 0.4);
        ctx.lineTo(x + size * 0.3, y + size);
        ctx.lineTo(x + size, y);
      } else {
        ctx.moveTo(x, y);
        ctx.lineTo(x + size, y + size);
        ctx.moveTo(x + size, y);
        ctx.lineTo(x, y + size);
      }
      ctx.stroke();
      ctx.restore();

      if (isSelected) {
        ctx.save();
        ctx.setLineDash([4, 2]);
        ctx.strokeStyle = "#00aaff";
        ctx.strokeRect(x - 3, y - 3, size + 6, size + 6);
        ctx.restore();
      }
    } else if (shape.type === "arrow") {
      const x1 = toCx(shape.x1);
      const y1 = toCx(shape.y1);
      const x2 = toCx(shape.x2);
      const y2 = toCx(shape.y2);

      ctx.save();
      ctx.strokeStyle = shape.stroke || "#ff0000";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();

      const angle = Math.atan2(y2 - y1, x2 - x1);
      const len = 10;
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(
        x2 - len * Math.cos(angle - Math.PI / 6),
        y2 - len * Math.sin(angle - Math.PI / 6)
      );
      ctx.lineTo(
        x2 - len * Math.cos(angle + Math.PI / 6),
        y2 - len * Math.sin(angle + Math.PI / 6)
      );
      ctx.closePath();
      ctx.fillStyle = shape.stroke || "#ff0000";
      ctx.fill();
      ctx.restore();

      if (isSelected) {
        const minX = Math.min(x1, x2);
        const maxX = Math.max(x1, x2);
        const minY = Math.min(y1, y2);
        const maxY = Math.max(y1, y2);
        ctx.save();
        ctx.setLineDash([4, 2]);
        ctx.strokeStyle = "#00aaff";
        ctx.strokeRect(minX - 3, minY - 3, maxX - minX + 6, maxY - minY + 6);
        ctx.restore();
      }
    } else if (shape.type === "text" || shape.type === "callout") {
      const x = toCx(shape.x);
      const y = toCx(shape.y);
      const fontSize = 16 * scale;
      const text = shape.text || (shape.type === "callout" ? "Callout text" : "Text");

      ctx.save();
      ctx.fillStyle = shape.color || "#000000";
      ctx.font = `${fontSize}px Arial`;
      ctx.textBaseline = "top";

      const lines = text.split("\n");
      const lineHeight = fontSize + 2;
      lines.forEach((ln, i) => {
        ctx.fillText(ln, x, y + i * lineHeight);
      });

      // (optional) callout arrowTo not implemented yet
      ctx.restore();

      if (isSelected) {
        const textHeight = lineHeight * lines.length;
        const boxW = (shape.w || 200) * scale;
        ctx.save();
        ctx.setLineDash([4, 2]);
        ctx.strokeStyle = "#00aaff";
        ctx.strokeRect(x - 3, y - 3, boxW + 6, textHeight + 6);
        ctx.restore();
      }
    }
  }

  function redrawCanvas() {
    const canvas = getCanvas();
    const img = imgRef.current;
    if (!canvas || !img || !baseImageUrl || imgNaturalSize.w === 0) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    canvas.width = imgNaturalSize.w * zoom;
    canvas.height = imgNaturalSize.h * zoom;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // draw background image
    ctx.drawImage(
      img,
      0,
      0,
      imgNaturalSize.w * zoom,
      imgNaturalSize.h * zoom
    );

    const currentShapes = getVisibleShapes();
    currentShapes.forEach((s) =>
      drawShape(ctx, s, s.id === selectedShapeId, zoom)
    );

    if (ocrRect && ocrRect.page === currentPage) {
      const x = ocrRect.x * zoom;
      const y = ocrRect.y * zoom;
      const w = ocrRect.w * zoom;
      const h = ocrRect.h * zoom;
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = "#00aaee";
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, w, h);
      ctx.restore();
    }
  }

  useEffect(() => {
    redrawCanvas();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseImageUrl, shapes, zoom, selectedShapeId, ocrRect, currentPage]);

  useEffect(() => {
    const img = imgRef.current;
    if (!img || !baseImageUrl) return;
    img.onload = () => {
      setImgNaturalSize({ w: img.naturalWidth, h: img.naturalHeight });
      setZoom(1);
    };
    img.src = baseImageUrl;
  }, [baseImageUrl]);

  async function renderPdfPage(pageNum) {
    const pdfjsLib = pdfjsLibRef.current;
    if (!pdfjsLib || !pdfDocRef.current) return;

    try {
      const page = await pdfDocRef.current.getPage(pageNum);
      const viewport = page.getViewport({ scale: 1.5 });
      const offCanvas = document.createElement("canvas");
      const ctx = offCanvas.getContext("2d");
      offCanvas.width = viewport.width;
      offCanvas.height = viewport.height;
      await page.render({ canvasContext: ctx, viewport }).promise;
      const dataUrl = offCanvas.toDataURL("image/png");
      setBaseImageUrl(dataUrl);
    } catch (e) {
      console.error("renderPdfPage error", e);
      alert("Failed to render PDF page.");
    }
  }

  async function goToPage(newPage) {
    if (newPage < 1 || newPage > numPages) return;
    setCurrentPage(newPage);
    setOcrRect(null);
    if (isPdf && pdfDocRef.current) {
      await renderPdfPage(newPage);
    }
    if (drawingId) {
      await loadAnnotationsForPage(drawingId, newPage);
    }
  }

  async function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    setFileName(file.name || "");
    const isPdfFile =
      file.type === "application/pdf" ||
      file.name.toLowerCase().endsWith(".pdf");
    setIsPdf(isPdfFile);
    setDrawingId(null);
    setShapes([]);
    setHistory([]);
    setOcrRect(null);
    setOcrText("");
    setReportText("");
    setChecklistText("");
    setAiItems([]);
    setCurrentPage(1);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("trade_type", selectedTrade);

    let newDrawingId = null;

    try {
      const res = await fetch(`${API_BASE}/upload-drawing`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const text = await res.text();
        console.error("upload-drawing error:", text);
        alert("Upload error from backend.");
        return;
      }
      const data = await res.json();
      newDrawingId = data.drawing_id || data.id || null;
      setDrawingId(newDrawingId);
      setNumPages(data.num_pages || 1);
    } catch (err) {
      console.error("upload-drawing fetch error", err);
      alert("Failed to upload drawing to backend.");
      return;
    }

    if (isPdfFile) {
      try {
        const arrayBuffer = await file.arrayBuffer();
        pdfArrayBufferRef.current = arrayBuffer;
        const pdfjsLib = pdfjsLibRef.current;
        if (!pdfjsLib) {
          alert("pdf.js not loaded yet.");
          return;
        }
        const pdfDoc = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        pdfDocRef.current = pdfDoc;
        setNumPages(pdfDoc.numPages || 1);
        await renderPdfPage(1);
      } catch (e2) {
        console.error("Error loading PDF in frontend", e2);
        alert("Could not render PDF in browser.");
      }
    } else {
      const url = URL.createObjectURL(file);
      setBaseImageUrl(url);
    }
  }

  async function loadAnnotationsForPage(dId, pageNum) {
    try {
      const url = `${API_BASE}/load-annotations?drawing_id=${encodeURIComponent(
        dId
      )}&page=${pageNum}`;
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      const incoming = Array.isArray(data.annotations) ? data.annotations : [];
      setShapes((prev) => {
        const others = prev.filter((s) => s.page !== pageNum);
        return [...others, ...incoming];
      });
    } catch (e) {
      console.error("load-annotations error", e);
    }
  }

  async function handleSaveAnnotations() {
    if (!drawingId) {
      alert("No drawing_id. Upload a drawing first.");
      return;
    }
    const pageShapes = getVisibleShapes();
    try {
      const res = await fetch(`${API_BASE}/save-annotations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          drawing_id: drawingId,
          page: currentPage,
          annotations: pageShapes,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        console.error("/save-annotations error:", text);
        alert("Failed to save annotations.");
        return;
      }
      alert("Annotations saved for this page.");
    } catch (e) {
      console.error("save-annotations error", e);
      alert("Error saving annotations.");
    }
  }

  async function handleLoadAnnotationsClick() {
    if (!drawingId) {
      alert("Upload a drawing first.");
      return;
    }
    await loadAnnotationsForPage(drawingId, currentPage);
  }

  function hitTestShape(ix, iy) {
    const visible = getVisibleShapes();
    for (let i = visible.length - 1; i >= 0; i--) {
      const s = visible[i];
      if (s.type === "arrow") {
        const minX = Math.min(s.x1, s.x2);
        const maxX = Math.max(s.x1, s.x2);
        const minY = Math.min(s.y1, s.y2);
        const maxY = Math.max(s.y1, s.y2);
        if (ix >= minX && ix <= maxX && iy >= minY && iy <= maxY) {
          return s.id;
        }
      } else if (s.type === "check" || s.type === "cross") {
        const size = s.size || 24;
        if (ix >= s.x && ix <= s.x + size && iy >= s.y && iy <= s.y + size) {
          return s.id;
        }
      } else if (s.type === "text" || s.type === "callout") {
        const w = s.w || 200;
        const h = s.h || 40;
        if (ix >= s.x && ix <= s.x + w && iy >= s.y && iy <= s.y + h) {
          return s.id;
        }
      } else {
        const w = s.w || 0;
        const h = s.h || 0;
        if (ix >= s.x && ix <= s.x + w && iy >= s.y && iy <= s.y + h) {
          return s.id;
        }
      }
    }
    return null;
  }

  function handleCanvasMouseDown(evt) {
    const canvas = getCanvas();
    if (!canvas || imgNaturalSize.w === 0) return;

    const { x: ix, y: iy } = getImageCoords(evt);

    if (tool === "select") {
      const hitId = hitTestShape(ix, iy);
      setSelectedShapeId(hitId);
      return;
    }

    if (tool === "ocr") {
      dragStateRef.current = {
        mode: "ocr",
        startX: ix,
        startY: iy,
        shapeId: null,
      };
      return;
    }

    const id = nextShapeId();
    let newShape = {
      id,
      page: currentPage,
      type: tool,
      x: ix,
      y: iy,
      w: 0,
      h: 0,
      stroke: strokeColor,
      fill: fillColor,
      color: textColor,
    };

    if (tool === "arrow") {
      newShape = { ...newShape, x1: ix, y1: iy, x2: ix, y2: iy };
    } else if (tool === "check" || tool === "cross") {
      newShape.size = 24;
    } else if (tool === "text" || tool === "callout") {
      newShape.text = tool === "callout" ? "Callout text" : "Text";
      newShape.font = "16px Arial";
      // give it a default box for hit testing
      newShape.w = 200;
      newShape.h = 40;
    }

    if (tool === "check" || tool === "cross" || tool === "text" || tool === "callout") {
      setShapes((prev) => {
        pushHistory(prev);
        return [...prev, newShape];
      });
      setSelectedShapeId(id);
      return;
    }

    setShapes((prev) => {
      pushHistory(prev);
      return [...prev, newShape];
    });
    setSelectedShapeId(id);
    dragStateRef.current = {
      mode: "draw",
      startX: ix,
      startY: iy,
      shapeId: id,
    };
  }

  function handleCanvasMouseMove(evt) {
    const drag = dragStateRef.current;
    if (!drag.mode) return;

    const { x: ix, y: iy } = getImageCoords(evt);

    if (drag.mode === "ocr") {
      const ox = drag.startX;
      const oy = drag.startY;
      setOcrRect({
        page: currentPage,
        x: Math.min(ox, ix),
        y: Math.min(oy, iy),
        w: Math.abs(ix - ox),
        h: Math.abs(iy - oy),
      });
      return;
    }

    if (drag.mode === "draw" && drag.shapeId) {
      setShapes((prev) =>
        prev.map((s) => {
          if (s.id !== drag.shapeId) return s;
          if (s.type === "arrow") {
            return { ...s, x2: ix, y2: iy };
          }
          return {
            ...s,
            x: Math.min(drag.startX, ix),
            y: Math.min(drag.startY, iy),
            w: Math.abs(ix - drag.startX),
            h: Math.abs(iy - drag.startY),
          };
        })
      );
    }
  }

  function handleCanvasMouseUp() {
    dragStateRef.current = { mode: null, startX: 0, startY: 0, shapeId: null };
  }

  function handleDeleteSelected() {
    if (!selectedShapeId) return;
    setShapes((prev) => {
      pushHistory(prev);
      return prev.filter((s) => s.id !== selectedShapeId);
    });
    setSelectedShapeId(null);
  }

  function handleClearPage() {
    if (!window.confirm("Clear all annotations on this page?")) return;
    setShapes((prev) => {
      pushHistory(prev);
      return prev.filter((s) => s.page !== currentPage);
    });
    setSelectedShapeId(null);
    setOcrRect(null);
  }

  function zoomIn() {
    setZoom((z) => Math.min(z * 1.2, 5));
  }
  function zoomOut() {
    setZoom((z) => Math.max(z / 1.2, 0.2));
  }
  function resetZoom() {
    setZoom(1);
  }

  async function handleOcrSelectedRegion() {
    if (!drawingId) {
      alert("Upload a drawing first.");
      return;
    }
    if (!ocrRect || ocrRect.page !== currentPage) {
      alert("Draw an OCR rectangle first (tool: OCR).");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/ocr-crop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          drawing_id: drawingId,
          page: currentPage,
          crop: {
            x: ocrRect.x,
            y: ocrRect.y,
            w: ocrRect.w,
            h: ocrRect.h,
          },
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        console.error("ocr-crop error:", text);
        alert("OCR crop error from backend.");
        return;
      }
      const data = await res.json();
      const t = data.text || data.ocr_text || "";
      setOcrText(t);
    } catch (e) {
      console.error("ocr-crop fetch error", e);
      alert("Failed to run OCR crop.");
    }
  }

  async function loadTradeConfig(trade) {
    try {
      const res = await fetch(
        `${API_BASE}/get-trade-config?trade=${encodeURIComponent(trade)}`
      );
      if (!res.ok) return;
      const data = await res.json();
      if (typeof data.system_prompt === "string") setTradePrompt(data.system_prompt);
      if (typeof data.checklist_template === "string")
        setChecklistTemplate(data.checklist_template);
    } catch (e) {
      console.error("get-trade-config error", e);
    }
  }

  useEffect(() => {
    loadTradeConfig(selectedTrade);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTrade]);

  async function handleSaveTradeConfig() {
    try {
      const res = await fetch(`${API_BASE}/save-trade-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          trade: selectedTrade,
          system_prompt: tradePrompt,
          checklist_template: checklistTemplate,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        console.error("save-trade-config error:", text);
        alert("Failed to save trade config.");
        return;
      }
      alert("Trade template saved.");
    } catch (e) {
      console.error("save-trade-config fetch error", e);
      alert("Error saving trade config.");
    }
  }

  async function handleGenerateReport() {
    if (!drawingId) {
      alert("Upload a drawing first.");
      return;
    }
    setIsGenerating(true);
    setAiError("");
    try {
      const res = await fetch(`${API_BASE}/generate-report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          drawing_id: drawingId,
          trade_type: selectedTrade,
          project_info: projectInfo,
          page: currentPage,
          annotations: getVisibleShapes(),
          ocr_crop: ocrRect,
          ocr_text: ocrText,
          trade_prompt: tradePrompt,
          checklist_template: checklistTemplate,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        console.error("generate-report error:", text);
        setAiError("Backend generate-report error.");
        return;
      }
      const data = await res.json();
      setReportText(data.report_text || "");
      setChecklistText(data.checklist_text || "");
      setAiItems(Array.isArray(data.json_items) ? data.json_items : []);
    } catch (e) {
      console.error("generate-report fetch error", e);
      setAiError("Failed to call generate-report.");
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleExportFullPdf() {
    if (!isPdf || !pdfDocRef.current) {
      alert("This export is only available for uploaded PDFs.");
      return;
    }
    const pdfjsLib = pdfjsLibRef.current;
    if (!pdfjsLib) {
      alert("pdf.js not loaded.");
      return;
    }

    try {
      const pagesDataUrls = [];
      for (let p = 1; p <= numPages; p++) {
        const page = await pdfDocRef.current.getPage(p);
        const viewport = page.getViewport({ scale: 1.5 });

        const baseCanvas = document.createElement("canvas");
        const baseCtx = baseCanvas.getContext("2d");
        baseCanvas.width = viewport.width;
        baseCanvas.height = viewport.height;

        await page.render({ canvasContext: baseCtx, viewport }).promise;

        const pageShapes = shapes.filter((s) => s.page === p);
        if (pageShapes.length > 0) {
          pageShapes.forEach((shape) => {
            drawShape(baseCtx, shape, false, 1);
          });
        }

        const dataUrl = baseCanvas.toDataURL("image/png");
        pagesDataUrls.push(dataUrl);
      }

      const res = await fetch(`${API_BASE}/export-pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pages: pagesDataUrls }),
      });

      if (!res.ok) {
        const text = await res.text();
        console.error("export-pdf error:", text);
        alert("Backend export-pdf error.");
        return;
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const cleanName = fileName
        ? fileName.replace(/\.[^/.]+$/, "")
        : "annotated";
      a.download = `${cleanName}-annotated.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("export full pdf error", e);
      alert("Failed to export annotated PDF.");
    }
  }

  const selectedShape =
    shapes.find((s) => s.id === selectedShapeId) || null;

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: 16 }}>
      <h1 style={{ marginBottom: 8 }}>
        Construction Inspection – Drawing Annotation Prototype
      </h1>

      <section style={{ marginBottom: 16 }}>
        <h2>1. Upload drawing (image or PDF)</h2>
        <input type="file" accept="image/*,application/pdf" onChange={handleFileChange} />
        <div style={{ marginTop: 8, fontSize: 14 }}>
          {fileName ? (
            <>
              <strong>File:</strong> {fileName}{" "}
              {drawingId && (
                <>
                  &nbsp; | <strong>drawing_id:</strong> {drawingId}
                </>
              )}
            </>
          ) : (
            <>No file chosen.</>
          )}
        </div>
        {isPdf && (
          <div
            style={{
              marginTop: 8,
              padding: 8,
              background: "#fffbe6",
              border: "1px solid #ffe58f",
              fontSize: 13,
            }}
          >
            PDF detected. Use the page controls below to switch pages.
          </div>
        )}
      </section>

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <div style={{ flex: 3 }}>
          <section style={{ marginBottom: 16 }}>
            <h2>2. Annotate drawing</h2>

            <div style={{ marginBottom: 8, display: "flex", flexWrap: "wrap", gap: 4 }}>
              <label style={{ fontSize: 13, marginRight: 4 }}>Tool:</label>
              {[
                ["select", "Select"],
                ["rect", "Rectangle"],
                ["highlight", "Highlight"],
                ["arrow", "Arrow"],
                ["text", "Text"],
                ["callout", "Callout"],
                ["check", "✔"],
                ["cross", "✖"],
                ["ocr", "OCR Rect"],
              ].map(([val, label]) => (
                <button
                  key={val}
                  onClick={() => setTool(val)}
                  style={{
                    padding: "2px 8px",
                    borderRadius: 4,
                    border: tool === val ? "2px solid #1677ff" : "1px solid #ccc",
                    background: tool === val ? "#e6f4ff" : "#f5f5f5",
                    fontSize: 12,
                  }}
                >
                  {label}
                </button>
              ))}
              <button
                onClick={handleClearPage}
                style={{ marginLeft: 8, padding: "2px 8px", fontSize: 12 }}
              >
                Clear Page
              </button>
              <button
                onClick={handleDeleteSelected}
                style={{ padding: "2px 8px", fontSize: 12 }}
              >
                Delete Selected
              </button>
              <button
                onClick={handleUndo}
                style={{ padding: "2px 8px", fontSize: 12 }}
              >
                Undo
              </button>
            </div>

            <div style={{ marginBottom: 8, display: "flex", gap: 16, flexWrap: "wrap" }}>
              <div>
                <label style={{ fontSize: 13 }}>
                  Stroke:&nbsp;
                  <input
                    type="color"
                    value={strokeColor}
                    onChange={(e) => setStrokeColor(e.target.value)}
                  />
                </label>
              </div>
              <div>
                <label style={{ fontSize: 13 }}>
                  Fill / Highlight:&nbsp;
                  <input
                    type="color"
                    value={fillColor}
                    onChange={(e) => setFillColor(e.target.value)}
                  />
                </label>
              </div>
              <div>
                <label style={{ fontSize: 13 }}>
                  Text:&nbsp;
                  <input
                    type="color"
                    value={textColor}
                    onChange={(e) => setTextColor(e.target.value)}
                  />
                </label>
              </div>

              <div>
                <span style={{ marginRight: 4 }}>Zoom:</span>
                <button onClick={zoomOut} style={{ padding: "0 6px" }}>
                  -
                </button>
                <button
                  onClick={zoomIn}
                  style={{ padding: "0 6px", marginLeft: 2, marginRight: 2 }}
                >
                  +
                </button>
                <button onClick={resetZoom} style={{ padding: "0 6px" }}>
                  Reset
                </button>
                <span style={{ marginLeft: 8, fontSize: 12 }}>
                  {zoom.toFixed(2)}x
                </span>
              </div>
            </div>

            {isPdf && (
              <div style={{ marginBottom: 8, fontSize: 13 }}>
                Page:&nbsp;
                <button
                  onClick={() => goToPage(currentPage - 1)}
                  disabled={currentPage <= 1}
                  style={{ padding: "0 6px", marginRight: 4 }}
                >
                  ◀
                </button>
                <span>
                  {currentPage} / {numPages}
                </span>
                <button
                  onClick={() => goToPage(currentPage + 1)}
                  disabled={currentPage >= numPages}
                  style={{ padding: "0 6px", marginLeft: 4 }}
                >
                  ▶
                </button>
              </div>
            )}

            <div
              style={{
                border: "1px solid #ccc",
                width: "100%",
                height: 600,
                position: "relative",
                overflow: "auto",
                background: "#f5f5f5",
              }}
            >
              {baseImageUrl && (
                <img
                  ref={imgRef}
                  src={baseImageUrl}
                  alt="drawing"
                  style={{ display: "none" }}
                />
              )}
              <canvas
                ref={canvasRef}
                style={{
                  display: "block",
                  margin: "0 auto",
                  cursor: tool === "select" ? "default" : "crosshair",
                }}
                onMouseDown={handleCanvasMouseDown}
                onMouseMove={handleCanvasMouseMove}
                onMouseUp={handleCanvasMouseUp}
              />
            </div>

            <div
              style={{
                marginTop: 8,
                display: "flex",
                flexWrap: "wrap",
                gap: 8,
                fontSize: 12,
              }}
            >
              <button onClick={handleSaveAnnotations}>💾 Save Annotations</button>
              <button onClick={handleLoadAnnotationsClick}>📥 Load Annotations</button>
              {isPdf && (
                <button onClick={handleExportFullPdf}>
                  ⬇ Download Full Annotated PDF
                </button>
              )}
              <button onClick={handleOcrSelectedRegion}>
                🧾 OCR Selected Region (tool: OCR)
              </button>
            </div>

            {/* Selected text editor */}
            {selectedShape &&
              (selectedShape.type === "text" ||
                selectedShape.type === "callout") && (
                <div style={{ marginTop: 8 }}>
                  <label style={{ display: "block", marginBottom: 4 }}>
                    Selected annotation text:
                  </label>
                  <textarea
                    rows={3}
                    style={{ width: "100%" }}
                    value={selectedShape.text || ""}
                    onChange={(e) => {
                      const newText = e.target.value;
                      setShapes((prev) =>
                        prev.map((s) =>
                          s.id === selectedShape.id
                            ? { ...s, text: newText }
                            : s
                        )
                      );
                    }}
                  />
                </div>
              )}
          </section>

          <section style={{ marginBottom: 16 }}>
            <h2>3. AI Description & Checklist</h2>
            <div style={{ marginBottom: 8 }}>
              <label>
                Trade:&nbsp;
                <select
                  value={selectedTrade}
                  onChange={(e) => setSelectedTrade(e.target.value)}
                >
                  {TRADE_OPTIONS.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div style={{ marginBottom: 8 }}>
              <label style={{ display: "block", marginBottom: 4 }}>
                Short project / location description:
              </label>
              <textarea
                value={projectInfo}
                onChange={(e) => setProjectInfo(e.target.value)}
                rows={3}
                style={{ width: "100%" }}
              />
            </div>

            <div style={{ marginBottom: 8 }}>
              <label style={{ display: "block", marginBottom: 4 }}>
                Latest OCR text (from selected area):
              </label>
              <textarea
                value={ocrText}
                readOnly
                rows={3}
                style={{ width: "100%", background: "#fafafa" }}
              />
            </div>

            <button onClick={handleGenerateReport} disabled={isGenerating}>
              {isGenerating ? "Generating..." : "Generate AI Description & Checklist"}
            </button>

            <div style={{ marginTop: 12 }}>
              <h3>AI Weld/Bolt Description</h3>
              {aiError && (
                <div style={{ color: "red", marginBottom: 4 }}>{aiError}</div>
              )}
              <div
                style={{
                  border: "1px solid #ddd",
                  padding: 8,
                  minHeight: 80,
                  background: "#fff",
                  whiteSpace: "pre-wrap",
                }}
              >
                {reportText || "(No AI report yet.)"}
              </div>
            </div>

            <div style={{ marginTop: 12 }}>
              <h3>AI Checklist</h3>
              <div
                style={{
                  border: "1px solid #ddd",
                  padding: 8,
                  minHeight: 80,
                  background: "#fff",
                  whiteSpace: "pre-wrap",
                }}
              >
                {checklistText || "(No AI checklist yet.)"}
              </div>
            </div>

            {aiItems && aiItems.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <h4>Structured checklist items</h4>
                <ul style={{ paddingLeft: 20 }}>
                  {aiItems.map((item, idx) => (
                    <li key={idx}>
                      <strong>[{item.status || "OPEN"}]</strong> {item.item}{" "}
                      {item.note ? `– ${item.note}` : ""}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        </div>

        {/* RIGHT – trade templates */}
        <div style={{ flex: 2 }}>
          <section style={{ marginBottom: 16 }}>
            <h2>Trade template (prompt & checklist pattern)</h2>
            <p style={{ fontSize: 13 }}>
              Each trade can have its own system prompt and checklist hints.
              Customize and save per trade.
            </p>

            <div style={{ marginBottom: 8 }}>
              <label>
                Trade:&nbsp;
                <select
                  value={selectedTrade}
                  onChange={(e) => setSelectedTrade(e.target.value)}
                >
                  {TRADE_OPTIONS.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div style={{ marginBottom: 8 }}>
              <label style={{ display: "block", marginBottom: 4 }}>
                Trade-specific system prompt:
              </label>
              <textarea
                value={tradePrompt}
                onChange={(e) => setTradePrompt(e.target.value)}
                rows={10}
                style={{ width: "100%", fontSize: 13 }}
              />
            </div>

            <div style={{ marginBottom: 8 }}>
              <label style={{ display: "block", marginBottom: 4 }}>
                Checklist template (high-level pattern):
              </label>
              <textarea
                value={checklistTemplate}
                onChange={(e) => setChecklistTemplate(e.target.value)}
                rows={6}
                style={{ width: "100%", fontSize: 13 }}
              />
            </div>

            <button onClick={handleSaveTradeConfig}>Save Template for Trade</button>
          </section>
        </div>
      </div>
    </div>
  );
}
