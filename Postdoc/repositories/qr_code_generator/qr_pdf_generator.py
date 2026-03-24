import argparse
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import filedialog, messagebox

import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageTk
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

MM_TO_PT = 72 / 25.4


@dataclass
class QrItem:
    payload: str
    label: str


@dataclass
class LayoutSpec:
    codes_per_row: int = 5
    rows_per_page: int = 7
    left_margin_mm: float = 9.0
    right_margin_mm: float = 8.0
    top_margin_mm: float = 8.0
    bottom_margin_mm: float = 13.0
    horizontal_gap_mm: float = 4.0
    vertical_gap_mm: float = 4.0
    qr_size_mm: float = 34.0
    label_font_size: int = 8
    label_gap_mm: float = 0.2


def mm(value: float) -> float:
    return value * MM_TO_PT


def truncate_for_reportlab(c: canvas.Canvas, text: str, max_width: float, font_name: str, font_size: int) -> str:
    if c.stringWidth(text, font_name, font_size) <= max_width:
        return text
    if max_width <= 0:
        return ""

    ellipsis = "..."
    if c.stringWidth(ellipsis, font_name, font_size) > max_width:
        return ""

    for end in range(len(text), 0, -1):
        candidate = f"{text[:end]}{ellipsis}"
        if c.stringWidth(candidate, font_name, font_size) <= max_width:
            return candidate
    return ellipsis


def truncate_for_pillow(draw: ImageDraw.ImageDraw, text: str, max_width: int, font: ImageFont.ImageFont) -> str:
    if max_width <= 0:
        return ""

    def text_width(value: str) -> int:
        bbox = draw.textbbox((0, 0), value, font=font)
        return bbox[2] - bbox[0]

    if text_width(text) <= max_width:
        return text

    ellipsis = "..."
    if text_width(ellipsis) > max_width:
        return ""

    for end in range(len(text), 0, -1):
        candidate = f"{text[:end]}{ellipsis}"
        if text_width(candidate) <= max_width:
            return candidate
    return ellipsis


def parse_items(raw_lines: list[str]) -> list[QrItem]:
    parsed: list[QrItem] = []
    for line in raw_lines:
        value = line.strip()
        if not value:
            continue

        if "|" in value:
            payload, label = value.split("|", 1)
            payload = payload.strip()
            label = label.strip() or payload
        else:
            payload = value
            label = value

        if payload:
            parsed.append(QrItem(payload=payload, label=label))

    return parsed


def make_qr_image(data: str, pixel_size: int = 800) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return image.resize((pixel_size, pixel_size), Image.Resampling.LANCZOS)


def draw_item(
    c: canvas.Canvas,
    item: QrItem,
    x: float,
    top_y: float,
    cell_width_pt: float,
    cell_height_pt: float,
    qr_size_pt: float,
    label_gap_pt: float,
    font_size: int,
) -> None:
    qr_image = make_qr_image(item.payload)
    cell_bottom_y = top_y - cell_height_pt
    qr_x = x + (cell_width_pt - qr_size_pt) / 2
    qr_bottom_y = top_y - qr_size_pt
    max_label_width = cell_width_pt - mm(1.0)

    image_buffer = BytesIO()
    qr_image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    c.drawImage(
        ImageReader(image_buffer),
        qr_x,
        qr_bottom_y,
        width=qr_size_pt,
        height=qr_size_pt,
        preserveAspectRatio=True,
        mask="auto",
    )

    label_text = truncate_for_reportlab(c, item.label[:80], max_label_width, "Helvetica", font_size)
    c.setFont("Helvetica", font_size)

    ascent_pt = (pdfmetrics.getAscent("Helvetica") * font_size) / 1000.0
    # Baseline so setzen, dass die Oberkante der Schrift direkt unterhalb des QR-Codes liegt.
    label_y = qr_bottom_y - label_gap_pt - ascent_pt

    # Falls der Text wegen extremer Einstellungen nach unten aus der Zelle fallen wuerde,
    # nur dann auf die Unterkante begrenzen.
    descent_pt = abs((pdfmetrics.getDescent("Helvetica") * font_size) / 1000.0)
    min_baseline = cell_bottom_y + mm(0.4) + descent_pt
    if label_y < min_baseline:
        label_y = min_baseline
    c.drawCentredString(
        x + cell_width_pt / 2,
        label_y,
        label_text,
    )


def generate_pdf(items: list[QrItem], output_path: Path, page_size=A4, layout: Optional[LayoutSpec] = None) -> None:
    if not items:
        raise ValueError("Keine gültigen Einträge gefunden.")

    layout = layout or LayoutSpec()
    page_width, page_height = page_size

    left_margin_pt = mm(layout.left_margin_mm)
    right_margin_pt = mm(layout.right_margin_mm)
    top_margin_pt = mm(layout.top_margin_mm)
    bottom_margin_pt = mm(layout.bottom_margin_mm)
    horizontal_gap_pt = mm(layout.horizontal_gap_mm)
    vertical_gap_pt = mm(layout.vertical_gap_mm)
    qr_size_pt = mm(layout.qr_size_mm)
    label_gap_pt = mm(layout.label_gap_mm)
    available_width_pt = page_width - left_margin_pt - right_margin_pt
    available_height_pt = page_height - top_margin_pt - bottom_margin_pt

    required_gap_width_pt = (layout.codes_per_row - 1) * horizontal_gap_pt
    required_gap_height_pt = (layout.rows_per_page - 1) * vertical_gap_pt
    if required_gap_width_pt >= available_width_pt:
        raise ValueError("Layout passt horizontal nicht auf die Seite.")
    if required_gap_height_pt >= available_height_pt:
        raise ValueError("Layout passt vertikal nicht auf die Seite.")

    cell_width_pt = (available_width_pt - required_gap_width_pt) / layout.codes_per_row
    cell_height_pt = (available_height_pt - required_gap_height_pt) / layout.rows_per_page
    if cell_width_pt <= 0 or cell_height_pt <= 0:
        raise ValueError("Layout passt vertikal nicht auf die Seite.")
    if qr_size_pt > cell_width_pt or qr_size_pt > cell_height_pt:
        raise ValueError("QR-Groesse passt nicht in die Labelzelle.")

    items_per_page = layout.rows_per_page * layout.codes_per_row
    x_start_pt = left_margin_pt
    top_y_start = page_height - top_margin_pt

    c = canvas.Canvas(str(output_path), pagesize=page_size)

    for index, item in enumerate(items):
        position_on_page = index % items_per_page
        row_index = position_on_page // layout.codes_per_row
        col_index = position_on_page % layout.codes_per_row

        if position_on_page == 0 and index > 0:
            c.showPage()

        x = x_start_pt + col_index * (cell_width_pt + horizontal_gap_pt)
        top_y = top_y_start - row_index * (cell_height_pt + vertical_gap_pt)

        draw_item(
            c=c,
            item=item,
            x=x,
            top_y=top_y,
            cell_width_pt=cell_width_pt,
            cell_height_pt=cell_height_pt,
            qr_size_pt=qr_size_pt,
            label_gap_pt=label_gap_pt,
            font_size=layout.label_font_size,
        )

    c.save()


def build_preview_pages(items: list[QrItem], layout: Optional[LayoutSpec] = None, preview_scale: int = 4) -> list[Image.Image]:
    if not items:
        return []

    layout = layout or LayoutSpec()
    page_width_mm = 210.0
    page_height_mm = 297.0
    page_width_px = int(round(page_width_mm * preview_scale))
    page_height_px = int(round(page_height_mm * preview_scale))

    left_margin_px = int(round(layout.left_margin_mm * preview_scale))
    right_margin_px = int(round(layout.right_margin_mm * preview_scale))
    top_margin_px = int(round(layout.top_margin_mm * preview_scale))
    bottom_margin_px = int(round(layout.bottom_margin_mm * preview_scale))
    horizontal_gap_px = int(round(layout.horizontal_gap_mm * preview_scale))
    vertical_gap_px = int(round(layout.vertical_gap_mm * preview_scale))
    qr_size_px = max(int(round(layout.qr_size_mm * preview_scale)), 1)
    label_gap_px = max(int(round(layout.label_gap_mm * preview_scale)), 1)

    available_width_px = page_width_px - left_margin_px - right_margin_px
    available_height_px = page_height_px - top_margin_px - bottom_margin_px
    required_gap_width_px = (layout.codes_per_row - 1) * horizontal_gap_px
    required_gap_height_px = (layout.rows_per_page - 1) * vertical_gap_px
    cell_width_px = (available_width_px - required_gap_width_px) // layout.codes_per_row
    cell_height_px = (available_height_px - required_gap_height_px) // layout.rows_per_page
    if qr_size_px > cell_width_px or qr_size_px > cell_height_px:
        raise ValueError("QR-Groesse passt nicht in die Labelzelle.")

    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except OSError:
        font = ImageFont.load_default()

    x_start_px = left_margin_px
    y_start_px = top_margin_px

    items_per_page = layout.codes_per_row * layout.rows_per_page
    pages: list[Image.Image] = []

    for start in range(0, len(items), items_per_page):
        page = Image.new("RGB", (page_width_px, page_height_px), "white")
        page_items = items[start : start + items_per_page]

        for index, item in enumerate(page_items):
            row_index = index // layout.codes_per_row
            col_index = index % layout.codes_per_row
            x = x_start_px + col_index * (cell_width_px + horizontal_gap_px)
            y = y_start_px + row_index * (cell_height_px + vertical_gap_px)

            qr_image = make_qr_image(item.payload, pixel_size=qr_size_px)
            qr_x = x + (cell_width_px - qr_size_px) // 2
            page.paste(qr_image, (qr_x, y))

            draw = ImageDraw.Draw(page)
            label_text = truncate_for_pillow(draw, item.label[:40], cell_width_px - 4, font)
            label_y_top = y + qr_size_px + label_gap_px

            bbox = draw.textbbox((0, 0), label_text, font=font)
            label_width = bbox[2] - bbox[0]
            tx = x + (cell_width_px - label_width) // 2
            min_label_y = y + cell_height_px - (bbox[3] - bbox[1]) - 1
            ty = min(label_y_top + 1, min_label_y)
            draw.text((tx, ty), label_text, fill="black", font=font)

        pages.append(page)

    return pages


def read_lines_from_file(file_path: Path) -> list[str]:
    return file_path.read_text(encoding="utf-8").splitlines()


def run_gui() -> None:
    root = tk.Tk()
    root.title("QR Code Generator mit Vorschau")
    root.geometry("1100x760")

    frame = tk.Frame(root, padx=12, pady=12)
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        frame,
        text="Eintrag pro Zeile. Optional: payload|label (Label wird mit in die PDF gedruckt).",
        anchor="w",
    ).pack(fill=tk.X)

    main_split = tk.PanedWindow(frame, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
    main_split.pack(fill=tk.BOTH, expand=True, pady=(6, 10))

    left_panel = tk.Frame(main_split)
    right_panel = tk.Frame(main_split)
    main_split.add(left_panel, stretch="always", minsize=360)
    main_split.add(right_panel, stretch="always", minsize=420)

    text = tk.Text(left_panel, height=22, wrap=tk.NONE)
    text.pack(fill=tk.BOTH, expand=True)

    bottom = tk.Frame(frame)
    bottom.pack(fill=tk.X)

    output_var = tk.StringVar(value=str(Path.cwd() / "qr_codes.pdf"))
    page_info_var = tk.StringVar(value="Noch keine Vorschau erstellt")

    preview_canvas = tk.Canvas(right_panel, bg="#d5d8dc", highlightthickness=0)
    preview_scroll = tk.Scrollbar(right_panel, orient=tk.VERTICAL, command=preview_canvas.yview)
    preview_canvas.configure(yscrollcommand=preview_scroll.set)
    preview_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    preview_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    preview_container = tk.Frame(preview_canvas, bg="#d5d8dc")
    preview_canvas.create_window((0, 0), window=preview_container, anchor="nw")

    def refresh_scroll_region(_: object = None) -> None:
        preview_canvas.configure(scrollregion=preview_canvas.bbox("all"))

    preview_container.bind("<Configure>", refresh_scroll_region)

    current_items: list[QrItem] = []
    preview_refs: list[Image.Image] = []
    preview_tk_refs: list[ImageTk.PhotoImage] = []

    def load_txt() -> None:
        file_name = filedialog.askopenfilename(
            title="Textdatei auswählen",
            filetypes=[("Textdatei", "*.txt"), ("Alle Dateien", "*.*")],
        )
        if not file_name:
            return
        lines = read_lines_from_file(Path(file_name))
        text.delete("1.0", tk.END)
        text.insert("1.0", "\n".join(lines))

    def pick_output() -> None:
        file_name = filedialog.asksaveasfilename(
            title="PDF speichern unter",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if file_name:
            output_var.set(file_name)

    def transform_preview() -> None:
        raw = text.get("1.0", tk.END).splitlines()
        items = parse_items(raw)
        if not items:
            messagebox.showerror("Fehler", "Keine gültigen Einträge gefunden.")
            return

        for child in preview_container.winfo_children():
            child.destroy()

        preview_pages = build_preview_pages(items)
        if not preview_pages:
            messagebox.showerror("Fehler", "Vorschau konnte nicht erstellt werden.")
            return

        preview_refs.clear()
        preview_tk_refs.clear()

        for page_index, page in enumerate(preview_pages, start=1):
            # Die Vorschauseiten werden zur besseren Lesbarkeit verkleinert angezeigt.
            display_page = page.resize((int(page.width * 0.55), int(page.height * 0.55)), Image.Resampling.LANCZOS)
            preview_refs.append(display_page)
            photo = ImageTk.PhotoImage(display_page, master=root)
            preview_tk_refs.append(photo)

            holder = tk.Frame(preview_container, bg="#d5d8dc", pady=10)
            holder.pack(fill=tk.X)
            tk.Label(holder, text=f"Seite {page_index}", bg="#d5d8dc", anchor="w").pack(fill=tk.X, padx=12)
            tk.Label(holder, image=photo, bd=1, relief=tk.SOLID).pack(padx=12, pady=(4, 0), anchor="w")

        current_items.clear()
        current_items.extend(items)
        save_pdf_button.config(state=tk.NORMAL)
        page_info_var.set(f"Vorschau: {len(preview_pages)} Seite(n), {len(items)} Code(s)")
        preview_canvas.yview_moveto(0.0)

    def create_pdf() -> None:
        if not current_items:
            messagebox.showerror("Fehler", "Bitte zuerst auf 'Transformieren' klicken.")
            return

        output = Path(output_var.get()).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        try:
            generate_pdf(current_items, output)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Fehler", f"PDF konnte nicht erzeugt werden:\n{exc}")
            return

        messagebox.showinfo("Erfolg", f"PDF erzeugt:\n{output}")

    controls = tk.Frame(bottom)
    controls.pack(side=tk.LEFT)

    tk.Button(controls, text="Textdatei laden", command=load_txt, width=16).pack(side=tk.LEFT, padx=(0, 8))
    tk.Button(controls, text="Transformieren", command=transform_preview, width=16).pack(side=tk.LEFT, padx=(0, 8))
    save_pdf_button = tk.Button(controls, text="Als PDF speichern", command=create_pdf, width=16, state=tk.DISABLED)
    save_pdf_button.pack(side=tk.LEFT)

    output_frame = tk.Frame(bottom)
    output_frame.pack(side=tk.RIGHT, fill=tk.X, expand=True)

    tk.Label(frame, textvariable=page_info_var, anchor="w").pack(fill=tk.X, pady=(0, 8))

    tk.Label(output_frame, text="Ausgabe:").pack(side=tk.LEFT, padx=(0, 6))
    tk.Entry(output_frame, textvariable=output_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
    tk.Button(output_frame, text="...", command=pick_output, width=4).pack(side=tk.LEFT, padx=(6, 0))

    root.mainloop()


def run_cli(input_file: Optional[Path], output: Path, items: list[str]) -> None:
    raw_lines: list[str] = []

    if input_file:
        raw_lines.extend(read_lines_from_file(input_file))

    raw_lines.extend(items)

    parsed_items = parse_items(raw_lines)
    output.parent.mkdir(parents=True, exist_ok=True)
    generate_pdf(parsed_items, output)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QR-Code-Generator für druckbare PDF")
    parser.add_argument("--input-file", type=Path, help="Textdatei mit Einträgen")
    parser.add_argument("--item", action="append", default=[], help="Ein einzelner Eintrag")
    parser.add_argument("--output", type=Path, default=Path("qr_codes.pdf"), help="Ausgabedatei PDF")
    parser.add_argument("--nogui", action="store_true", help="Nur CLI verwenden")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.nogui or args.input_file or args.item:
        run_cli(args.input_file, args.output, args.item)
    else:
        run_gui()


if __name__ == "__main__":
    main()
