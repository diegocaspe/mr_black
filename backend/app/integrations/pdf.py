"""Generación del comprobante en PDF (ReportLab) con la identidad Mr Black."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.timeutils import tz
from app.models.sale import SALE_ANULADA, SALE_PAGADA, SALE_PENDIENTE_PAGO, Sale

GOLD = colors.HexColor("#B8932B")
DARK = colors.HexColor("#121212")
GREY = colors.HexColor("#6b6b6b")
LINE = colors.HexColor("#d9d9d9")

STATUS_TEXT = {SALE_PAGADA: "PAGADO", SALE_PENDIENTE_PAGO: "PENDIENTE DE PAGO", SALE_ANULADA: "ANULADO"}


def _p(text: str, size=8.5, color=DARK, bold=False, align=0) -> Paragraph:
    style = ParagraphStyle(
        "x", fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size, leading=size * 1.3,
        textColor=color, alignment=align,
    )
    return Paragraph(text, style)


def _esc(v) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_receipt_pdf(sale: Sale, business: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A5, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=f"Comprobante {sale.receipt.code}", author=business.get("name"))
    width = doc.width
    story = []

    header = Table(
        [[
            _p("<b>MB</b>", 14, colors.HexColor("#111111"), True),
            [_p("MR BLACK", 13, DARK, True), _p("BARBER SHOP", 7, GREY)],
            [_p("BOLETA DE VENTA ELECTRÓNICA", 7.5, GREY, True, TA_RIGHT),
             _p(_esc(sale.receipt.code), 12, DARK, True, TA_RIGHT),
             _p("Comprobante simulado – sin valor tributario", 6.5, GREY, False, TA_RIGHT)],
        ]],
        colWidths=[14 * mm, width * 0.42, None],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#D4AF37")),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [header, Spacer(1, 6)]
    story.append(_p(
        f"{_esc(business.get('legal_name', ''))} · RUC {_esc(business.get('ruc', ''))}<br/>"
        f"{_esc(business.get('address', ''))} · Tel. {_esc(business.get('phone', ''))} · {_esc(business.get('email', ''))}",
        7, GREY,
    ))
    story.append(Spacer(1, 8))

    issued = sale.receipt.issued_at.astimezone(tz())
    info = Table(
        [
            [_p("Cliente", 7, GREY), _p(_esc(sale.receipt.customer_name), 8.5, DARK, True),
             _p("Fecha", 7, GREY), _p(issued.strftime("%d/%m/%Y %H:%M"), 8.5, DARK, True)],
            [_p("Teléfono", 7, GREY), _p(_esc(sale.receipt.customer_phone or "—"), 8.5),
             _p("Venta N.°", 7, GREY), _p(f"{sale.id:06d}", 8.5)],
            [_p("Canal", 7, GREY), _p("Tienda online" if sale.channel == "ONLINE" else "Mostrador", 8.5),
             _p("Estado", 7, GREY), _p(STATUS_TEXT.get(sale.status, sale.status), 8.5, GOLD, True)],
        ],
        colWidths=[16 * mm, width / 2 - 16 * mm, 16 * mm, None],
    )
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story += [info, Spacer(1, 8)]

    rows = [[_p("Descripción", 7.5, colors.white, True), _p("Cant.", 7.5, colors.white, True, TA_RIGHT),
             _p("P. unit.", 7.5, colors.white, True, TA_RIGHT), _p("Importe", 7.5, colors.white, True, TA_RIGHT)]]
    for item in sale.items:
        rows.append([
            _p(_esc(item.description) + (" <font color='#6b6b6b'>(servicio)</font>" if item.service_id else ""), 8),
            _p(str(item.quantity), 8, align=TA_RIGHT),
            _p(f"S/ {item.unit_price:.2f}", 8, align=TA_RIGHT),
            _p(f"S/ {item.line_total:.2f}", 8, align=TA_RIGHT),
        ])
    items = Table(rows, colWidths=[width * 0.5, width * 0.12, width * 0.19, width * 0.19], repeatRows=1)
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [items, Spacer(1, 6)]

    totals = Table(
        [
            ["", _p("Subtotal", 8, GREY, align=TA_RIGHT), _p(f"S/ {sale.subtotal:.2f}", 8.5, align=TA_RIGHT)],
            ["", _p("Descuento", 8, GREY, align=TA_RIGHT), _p(f"S/ {sale.discount:.2f}", 8.5, align=TA_RIGHT)],
            ["", _p("TOTAL", 10, DARK, True, TA_RIGHT), _p(f"S/ {sale.total:.2f}", 11, GOLD, True, TA_RIGHT)],
        ],
        colWidths=[width * 0.5, width * 0.25, width * 0.25],
    )
    totals.setStyle(TableStyle([("LINEABOVE", (1, 2), (-1, 2), 0.8, DARK)]))
    story += [totals, Spacer(1, 10)]

    approved = [p for p in sale.payments if p.status == "APROBADO"]
    pay_lines = [f"<b>Método de pago:</b> {_esc(sale.method.name)}"]
    for p in approved:
        pay_lines.append(f"{_esc(p.payer_detail or p.method_code)} · Op. {_esc(p.reference or '—')}")
    if sale.status == SALE_PENDIENTE_PAGO:
        pay_lines.append("Pago pendiente: cancela el importe al recoger tu pedido en el local.")
    story.append(_p("<br/>".join(pay_lines), 7.5))
    story.append(Spacer(1, 14))
    story.append(_p("Gracias por elegir Mr Black · Tu estilo, nuestra pasión.", 8, GOLD, True, 1))

    doc.build(story)
    return buf.getvalue()
