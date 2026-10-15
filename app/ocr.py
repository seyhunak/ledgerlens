"""OCR and text extraction. No Mistral. pypdf text layer + tesseract fallback."""
from __future__ import annotations
import io

OCR_USED_LAST = False


def extract_pdf_text(path: str) -> tuple[str, int, bool]:
    """Return (full_text, pages, ocr_used). Falls back to tesseract per-page render if needed."""
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages_text: list[str] = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        pages_text.append(t)
    full = "\n\f\n".join(pages_text)
    chars = len(full.strip())
    if chars >= 100:
        return full, len(reader.pages), False
    # Sparse text -> try OCR by rendering with pypdf? pypdf can't render.
    # Try pdf -> image via Pillow? Without poppler we use tesseract directly on embedded images.
    try:
        from PIL import Image
        import pytesseract
        ocr_chunks: list[str] = []
        for page in reader.pages:
            for img in getattr(page, "images", []):
                try:
                    pil = Image.open(io.BytesIO(img.data))
                    ocr_chunks.append(pytesseract.image_to_string(pil))
                except Exception:
                    continue
        ocr_text = "\n".join(ocr_chunks).strip()
        if len(ocr_text) >= 20:
            return ocr_text, len(reader.pages), True
    except Exception:
        pass
    return full, len(reader.pages), False


def extract_image_text(path: str) -> tuple[str, bool]:
    from PIL import Image
    import pytesseract
    img = Image.open(path)
    return pytesseract.image_to_string(img), True


def extract_text(path: str, filename: str) -> tuple[str, int, bool]:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return extract_pdf_text(path)
    elif lower.endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp")):
        text, ocr = extract_image_text(path)
        return text, 1, ocr
    elif lower.endswith(".txt"):
        with open(path, "r", errors="ignore") as f:
            t = f.read()
        return t, 1, False
    raise ValueError(f"Unsupported file type: {filename}")
