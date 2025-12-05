import os
import json
import zipfile
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from docx import Document
from docx.shared import RGBColor

# --------------------------------------------------------
# App init
# --------------------------------------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True
)

# --------------------------------------------------------
# Paths
# --------------------------------------------------------
DATA_DIR = "data"
DOC_FILE = f"{DATA_DIR}/documents.json"
ANN_FILE = f"{DATA_DIR}/annotations.json"
LABEL_FILE = f"{DATA_DIR}/labels.json"

os.makedirs(DATA_DIR, exist_ok=True)

# --------------------------------------------------------
# Helper functions
# --------------------------------------------------------

def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return {}

def save_json(path: str, data: Dict[str, Any]):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def make_preview(text: str, n: int = 120) -> str:
    text = text.replace("\n", " ")
    text = " ".join(text.split())
    return text[:n] + ("..." if len(text) > n else "")

# --------------------------------------------------------
# Upload single file
# --------------------------------------------------------

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    content = await file.read()
    try:
        text = content.decode("utf-8", errors="ignore")
    except:
        text = ""

    docs = load_json(DOC_FILE)

    doc_id = file.filename
    docs[doc_id] = {
        "doc_id": doc_id,
        "filename": file.filename,
        "text": text,
        "preview": make_preview(text)
    }

    save_json(DOC_FILE, docs)
    return {"status": "uploaded", "doc_id": doc_id}

# --------------------------------------------------------
# Upload ZIP
# --------------------------------------------------------

@app.post("/upload-zip")
async def upload_zip(file: UploadFile = File(...)):
    docs = load_json(DOC_FILE)

    data = await file.read()
    path = "temp.zip"
    with open(path, "wb") as f:
        f.write(data)

    with zipfile.ZipFile(path, "r") as z:
        for name in z.namelist():
            if name.endswith(".txt"):
                txt = z.read(name).decode("utf-8", errors="ignore")
                docs[name] = {
                    "doc_id": name,
                    "filename": name,
                    "text": txt,
                    "preview": make_preview(txt)
                }

    save_json(DOC_FILE, docs)
    os.remove(path)
    return {"status": "uploaded-zip"}

# --------------------------------------------------------
# Upload folder (multiple files)
# --------------------------------------------------------

@app.post("/upload-folder")
async def upload_folder(files: List[UploadFile] = File(...)):
    docs = load_json(DOC_FILE)

    for f in files:
        content = await f.read()
        txt = content.decode("utf-8", errors="ignore")
        docs[f.filename] = {
            "doc_id": f.filename,
            "filename": f.filename,
            "text": txt,
            "preview": make_preview(txt)
        }

    save_json(DOC_FILE, docs)
    return {"status": "folder-uploaded"}

# --------------------------------------------------------
# List documents
# --------------------------------------------------------

@app.get("/documents")
def list_docs():
    docs = load_json(DOC_FILE)
    return list(docs.values())   # IMPORTANT: return list of objects

# --------------------------------------------------------
# Get document text
# --------------------------------------------------------

@app.get("/document/{doc_id}")
def get_doc(doc_id: str):
    docs = load_json(DOC_FILE)
    if doc_id not in docs:
        return JSONResponse({"error": "not found"}, status_code=404)

    return {
        "doc_id": doc_id,
        "text": docs[doc_id]["text"]
    }

# --------------------------------------------------------
# Save annotation (with rank)
# --------------------------------------------------------

@app.post("/save-annotation")
async def save_annot(
    doc_id: str = Form(...),
    start: int = Form(...),
    end: int = Form(...),
    text: str = Form(...),
    label: str = Form(...),
    rank: Optional[str] = Form(None)
):
    anns = load_json(ANN_FILE)
    if doc_id not in anns:
        anns[doc_id] = []

    def overlaps(a_start, a_end, b_start, b_end):
        return a_start < b_end and b_start < a_end

    current = anns[doc_id]
    filtered = [a for a in current if not overlaps(a["start"], a["end"], start, end)]
    filtered.append({
        "start": start,
        "end": end,
        "text": text,
        "label": label,
        "rank": rank
    })

    filtered.sort(key=lambda x: x["start"])
    anns[doc_id] = filtered

    save_json(ANN_FILE, anns)
    return {"status": "saved"}

# --------------------------------------------------------
# Get annotations for doc
# --------------------------------------------------------

@app.get("/annotations/{doc_id}")
def get_annots(doc_id: str):
    data = load_json(ANN_FILE)
    return data.get(doc_id, [])


@app.delete("/annotations/{doc_id}/{index}")
def delete_annotation(doc_id: str, index: int):
    anns = load_json(ANN_FILE)
    if doc_id not in anns or index < 0 or index >= len(anns[doc_id]):
        return JSONResponse({"error": "annotation not found"}, status_code=404)

    anns[doc_id].pop(index)
    save_json(ANN_FILE, anns)
    return {"status": "annotation deleted"}

# --------------------------------------------------------
# Label manager
# --------------------------------------------------------

@app.post("/labels")
async def save_label(name: str = Form(...), color: str = Form(...)):
    labels = load_json(LABEL_FILE)
    labels[name] = color
    save_json(LABEL_FILE, labels)
    return {"status": "label saved"}


@app.delete("/labels/{label_name}")
async def delete_label(label_name: str):
    labels = load_json(LABEL_FILE)
    if label_name not in labels:
        return JSONResponse({"error": "label not found"}, status_code=404)

    labels.pop(label_name, None)
    save_json(LABEL_FILE, labels)
    return {"status": "label deleted"}

@app.get("/labels")
def get_label():
    return load_json(LABEL_FILE)

# --------------------------------------------------------
# Export JSON
# --------------------------------------------------------

@app.get("/export-json/{doc_id}")
def export_json_file(doc_id: str):
    anns = load_json(ANN_FILE).get(doc_id, [])
    output = f"{doc_id}_annotations.json"
    with open(output, "w") as f:
        json.dump(anns, f, indent=2)
    return FileResponse(output, filename=output)

# --------------------------------------------------------
# Export Word
# --------------------------------------------------------

@app.get("/export-word/{doc_id}")
def export_word(doc_id: str):
    docs = load_json(DOC_FILE)
    anns = load_json(ANN_FILE)

    if doc_id not in docs:
        return JSONResponse({"error": "Not found"}, status_code=404)

    document = Document()
    document.add_heading(f"Annotations for {doc_id}", level=1)

    for a in anns.get(doc_id, []):
        p = document.add_paragraph()
        run = p.add_run(f"[{a['label']}] {a['text']} (Rank={a.get('rank','')})")
        run.font.color.rgb = RGBColor(200, 0, 0)

    filename = f"{doc_id}_annotations.docx"
    document.save(filename)

    return FileResponse(filename, filename)
