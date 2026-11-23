"""Write a dated, fictional CSV for the operator walkthrough to standard output."""

import csv
import sys
from datetime import date

today = date.today()
writer = csv.writer(sys.stdout)
writer.writerow((" Reference ", "Department", "Date", "Currency", "Amount", "Notes"))
writer.writerows((
    ("demo-101", "Operations", today.strftime("%d/%m/%Y"), "idr", "Rp 750.000,00",
     "Vendor: CV Contoh Rekaan; barang: kertas A4; jumlah 2 unit; untuk loket."),
    ("demo-102", "Finance", today.isoformat(), "IDR", "Rp 5.500.000",
     "Penyedia: PT Sumber Fiktif; item: keyboard rapat; jumlah 4 unit; untuk ruang rapat."),
    ("demo-103", "Facilities", today.isoformat(), "IDR", "Rp 90.000",
     "Perlu perlengkapan kebersihan. Jumlah belum pasti dan vendor menyusul. Hubungi demo@example.invalid."),
    ("demo-104", "Operations", today.isoformat(), "IDR", "belum diisi",
     "Minta perlengkapan untuk loket."),
))
