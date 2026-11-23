"""Resume text extraction from PDF and DOCX documents with size and signature verification."""

import io
from fastapi import HTTPException, status
from pypdf import PdfReader
from docx import Document

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
MIN_EXTRACTED_TEXT_LENGTH = 200

PDF_SIGNATURE = b"%PDF"
DOCX_SIGNATURE = b"PK\x03\x04"


def validate_file_metadata(content: bytes, filename: str) -> str:
    """Validate file size, extension, and binary signature.

    Args:
        content: Raw bytes of the uploaded file.
        filename: Name of the uploaded file.

    Returns:
        str: File extension in lowercase ('pdf' or 'docx').

    Raises:
        HTTPException: 413 if file exceeds 5MB, 400 if type/signature is invalid.
    """
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of 5 MB ({len(content)} bytes uploaded).",
        )

    lower_name = filename.lower()
    if lower_name.endswith(".pdf"):
        if not content.startswith(PDF_SIGNATURE):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file signature: expected a valid PDF document (%PDF).",
            )
        return "pdf"
    elif lower_name.endswith(".docx"):
        if not content.startswith(DOCX_SIGNATURE):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file signature: expected a valid DOCX document (PK zip).",
            )
        return "docx"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format. Please upload a .pdf or .docx file.",
        )


def extract_text_from_pdf(content: bytes) -> str:
    """Extract plain text from PDF bytes using pypdf.

    Args:
        content: Raw bytes of the PDF file.

    Returns:
        str: Extracted text from all pages.
    """
    try:
        reader = PdfReader(io.BytesIO(content))
        text_parts = []
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text_parts.append(extracted)
        return "\n".join(text_parts).strip()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read PDF document: {str(exc)}",
        )


def extract_text_from_docx(content: bytes) -> str:
    """Extract plain text from DOCX bytes using python-docx.

    Args:
        content: Raw bytes of the DOCX file.

    Returns:
        str: Extracted text from paragraphs and tables.
    """
    try:
        doc = Document(io.BytesIO(content))
        text_parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        text_parts.append(cell.text.strip())
        return "\n".join(text_parts).strip()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read DOCX document: {str(exc)}",
        )


def extract_resume_text(content: bytes, filename: str) -> str:
    """Validate and extract text from an uploaded resume file.

    Args:
        content: Raw bytes of the uploaded resume.
        filename: Original file name.

    Returns:
        str: Extracted text content.

    Raises:
        HTTPException: 413 (oversize), 400 (invalid format/signature), 422 (scanned / insufficient text).
    """
    file_type = validate_file_metadata(content, filename)
    if file_type == "pdf":
        raw_text = extract_text_from_pdf(content)
    else:
        raw_text = extract_text_from_docx(content)

    if len(raw_text) < MIN_EXTRACTED_TEXT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Extracted resume text is under {MIN_EXTRACTED_TEXT_LENGTH} characters. "
                "The file appears to be a scanned image or empty. "
                "Please upload a text-based PDF or DOCX file."
            ),
        )

    return raw_text

