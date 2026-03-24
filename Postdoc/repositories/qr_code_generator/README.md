# QR Code Generator

Kurztool zum Erstellen mehrerer QR-Codes und Export als PDF.

## Start
1. `python -m venv .venv`
2. `.venv\\Scripts\\activate`
3. `pip install -r requirements.txt`
4. `python qr_pdf_generator.py`

## Eingabeformat
- Eine Zeile pro QR-Code.
- Optional: `payload|label` (Label wird unter dem Code angezeigt).
