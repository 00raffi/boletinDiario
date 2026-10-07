"""Proceso separado y acotado para extraer PDFs. No es un sandbox de seguridad completo."""
import json
import resource
import sys

from pypdf import PdfReader


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
    reader = PdfReader(sys.argv[1])
    if reader.is_encrypted:
        raise ValueError("PDF cifrado no admitido")
    total_pages = len(reader.pages)
    overview = "--overview" in sys.argv
    headings = []
    if overview:
        def visit(outline, level=0):
            for entry in outline:
                if isinstance(entry, list):
                    visit(entry, level + 1)
                else:
                    number = reader.get_destination_page_number(entry)
                    if number is not None and 0 <= number < total_pages:
                        headings.append({"title": str(entry.title)[:180], "page": number + 1, "level": level})
        try:
            visit(reader.outline)
        except (ValueError, TypeError, KeyError):
            headings = []
    indices = list(range(min(100, total_pages)))
    if overview and total_pages > 100:
        # Preservar el final (conclusión/apoyos) y las páginas de capítulos del índice.
        priority = [*range(min(4, total_pages)), *range(max(0, total_pages - 16), total_pages)]
        for heading in headings:
            if heading["level"] == 0:
                priority += list(range(heading["page"] - 1, min(total_pages, heading["page"] + 2)))
                priority += list(range(max(0, heading["page"] - 3), heading["page"] - 1))
        indices = list(dict.fromkeys([*priority, *range(total_pages)]))[:100]
    pages, chars, truncated = [], 0, False
    for index in indices:
        number, page = index + 1, reader.pages[index]
        text = page.extract_text() or ""
        text = text[:max(0, 300_000 - chars)]
        chars += len(text)
        pages.append({"page": number, "text": text})
        if chars >= 300_000:
            break
    if chars < 300:
        raise ValueError("Texto insuficiente. El PDF puede requerir OCR; no se inventará un análisis.")
    print(json.dumps({"pages": pages, "total_pages": total_pages,
                      "headings": headings if overview else [],
                      "sampled": overview,
                      "extraction_partial": truncated or len(pages) < total_pages or chars >= 300_000}))


if __name__ == "__main__":
    main()
