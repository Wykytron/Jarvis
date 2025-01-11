# parser_utils.py
import pdfplumber
import requests
import tempfile
import os

from io import BytesIO
from bs4 import BeautifulSoup
import docx  # python-docx for .docx

def parse_file(raw_bytes: bytes, extension: str) -> str:
    """Parse PDF, DOCX, TXT, HTML (or fallback) into extracted text."""
    extension = extension.lower()
    if extension == "pdf":
        return parse_pdf(raw_bytes)
    elif extension == "docx":
        return parse_docx(raw_bytes)
    elif extension in ["html", "htm"]:
        return parse_html_file(raw_bytes)
    elif extension == "txt":
        return parse_txt(raw_bytes)
    else:
        # fallback: treat as plain text
        return raw_bytes.decode("utf-8", errors="ignore")

def parse_pdf(raw_bytes: bytes) -> str:
    with pdfplumber.open(BytesIO(raw_bytes)) as pdf:
        all_text = []
        for page in pdf.pages:
            txt = page.extract_text()
            if txt:
                all_text.append(txt)
        return "\n".join(all_text)

def parse_docx(raw_bytes: bytes) -> str:
    # python-docx must read from an actual file
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name

    doc = docx.Document(tmp_path)
    paragraphs = [p.text for p in doc.paragraphs]

    os.remove(tmp_path)
    return "\n".join(paragraphs)

def parse_html_file(raw_bytes: bytes) -> str:
    soup = BeautifulSoup(raw_bytes, "html.parser")
    for script in soup(["script", "style"]):
        script.extract()
    return soup.get_text(separator="\n")

def parse_txt(raw_bytes: bytes) -> str:
    return raw_bytes.decode("utf-8", errors="ignore")

def parse_url(url: str) -> str:
    """Fetch an HTML page from 'url' and parse text."""
    resp = requests.get(url)
    soup = BeautifulSoup(resp.content, "html.parser")
    for script in soup(["script", "style"]):
        script.decompose()
    return soup.get_text(separator="\n")
