import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
import barcode
from barcode.writer import ImageWriter

# Ensure directory exists
if not os.path.exists("invoices"):
    os.makedirs("invoices")

def create_invoice(log_id, slot_id, entry_dt, exit_dt, duration_sec, fee):
    """
    Generates a professional PDF receipt for a parking session.
    """
    filename = f"invoices/invoice_{log_id}.pdf"
    
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter

    # --- HEADER ---
    c.setFillColor(colors.darkblue)
    c.rect(0, height - 1.5*inch, width, 1.5*inch, fill=1, stroke=0)
    
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width / 2, height - 0.6*inch, "SMART PARKING SYSTEM")
    c.setFont("Helvetica", 12)
    c.drawCentredString(width / 2, height - 0.9*inch, "Official Payment Receipt")

    # --- DETAILS BOX ---
    c.setFillColor(colors.black)
    c.setStrokeColor(colors.gray)
    c.setLineWidth(1)
    
    # Box Coordinates
    box_x = 1 * inch
    box_y = height - 5.5 * inch
    box_w = width - 2 * inch
    box_h = 3 * inch
    
    c.rect(box_x, box_y, box_w, box_h, fill=0, stroke=1)

    # Text Settings
    x_label = box_x + 0.2 * inch
    x_value = box_x + 3.5 * inch
    y_start = box_y + box_h - 0.5 * inch
    line_height = 0.4 * inch

    c.setFont("Helvetica-Bold", 14)
    c.drawString(x_label, y_start, "Transaction ID:")
    c.setFont("Courier", 14)
    c.drawString(x_value, y_start, f"#{log_id:06d}")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(x_label, y_start - line_height, "Parking Slot:")
    c.setFont("Helvetica", 12)
    c.drawString(x_value, y_start - line_height, f"Slot {slot_id}")

    c.drawString(x_label, y_start - 2*line_height, "Entry Time:")
    c.drawString(x_value, y_start - 2*line_height, entry_dt.strftime("%Y-%m-%d %H:%M:%S"))

    c.drawString(x_label, y_start - 3*line_height, "Exit Time:")
    c.drawString(x_value, y_start - 3*line_height, exit_dt.strftime("%Y-%m-%d %H:%M:%S"))

    c.drawString(x_label, y_start - 4*line_height, "Duration:")
    hours = duration_sec // 3600
    minutes = (duration_sec % 3600) // 60
    c.drawString(x_value, y_start - 4*line_height, f"{hours}h {minutes}m")

    # --- TOTAL FEE HIGHLIGHT ---
    c.setFillColor(colors.whitesmoke)
    c.rect(box_x, box_y, box_w, 0.6*inch, fill=1, stroke=1)
    c.setFillColor(colors.darkgreen)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(x_label, box_y + 0.2*inch, "TOTAL PAID:")
    c.drawString(x_value, box_y + 0.2*inch, f"${fee:.2f}")

    # --- FOOTER & BARCODE ---
    # Generate temporary barcode image
    ean = barcode.get('code128', str(log_id), writer=ImageWriter())
    barcode_filename = f"temp_barcode_{log_id}"
    ean.save(barcode_filename)

    # Draw Barcode on PDF
    try:
        c.drawImage(f"{barcode_filename}.png", width/2 - 1.5*inch, 1.5*inch, width=3*inch, height=1*inch)
    except:
        pass # Skip if barcode fails

    # Cleanup temp barcode
    if os.path.exists(f"{barcode_filename}.png"):
        os.remove(f"{barcode_filename}.png")

    c.setFillColor(colors.gray)
    c.setFont("Helvetica-Oblique", 10)
    c.drawCentredString(width / 2, 1 * inch, "Thank you for parking with us.")
    c.drawCentredString(width / 2, 0.8 * inch, "This is a computer-generated invoice.")

    c.save()
    return filename