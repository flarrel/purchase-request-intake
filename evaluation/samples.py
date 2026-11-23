"""Reproducible synthetic development and holdout purchase notes."""

CATALOG = {
    "office": ("kertas A4", "map arsip biru", "spidol papan", "buku catatan", "amplop cokelat", "pulpen hitam"),
    "it": ("router kantor", "kabel HDMI", "laptop unit layanan", "tetikus optik", "keyboard rapat", "SSD eksternal"),
    "facilities": ("lampu lorong", "pel lantai", "filter air", "engsel pintu", "sabun tangan", "karpet ruang rapat"),
    "services": ("penerjemahan panduan", "pelatihan operator", "kurir dokumen", "servis AC", "kalibrasi alat", "instalasi rak"),
}
VENDORS = ("CV Contoh Rekaan", "PT Sumber Fiktif", "CV Karya Simulasi", "PT Niaga Rekaan", "CV Langit Tiruan")
DEVELOPMENT = (
    "Vendor: {vendor}; barang: {item}; jumlah {n} unit; untuk tim layanan.",
    "Mohon pesan {n} unit {item} dari {vendor} untuk kegiatan rutin.",
    "Pemasok: {vendor}; item: {item}; jumlah {n} unit. Penggunaan internal.",
    "{vendor} bisa menyediakan {n} unit {item} untuk divisi kami.",
    "Tim operasi minta {n} unit {item}. Pengadaan dari {vendor}.",
)
HOLDOUT = (
    "Untuk gudang, dibutuhkan {n} unit {item}. Penawaran datang dari {vendor}.",
    "Penyedia: {vendor}; jumlah {n} unit; item: {item}. Segera diproses.",
    "Apakah bisa membeli {n} unit {item} melalui {vendor} untuk ruang kerja?",
    "{vendor} -- {n} unit {item} -- pengadaan divisi umum.",
    "Setelah stok dicek, pemohon ingin {n} unit {item} dengan pemasok {vendor}.",
)


def make_split(split):
    holdout = split == "holdout"
    cases = []
    for template_index, template in enumerate(HOLDOUT if holdout else DEVELOPMENT):
        for category_index, (category, catalog) in enumerate(CATALOG.items()):
            for item_index in range(2 if holdout else 3):
                offset = 3 + (item_index + template_index) % 3 if holdout else item_index
                item = catalog[offset]
                vendor = VENDORS[(offset + category_index + template_index) % len(VENDORS)]
                n = 1 + (template_index * 3 + offset * 7 + category_index) % 24
                case = {
                    "id": f"{split}-{len(cases) + 1:02}",
                    "note": template.format(vendor=vendor, item=item, n=n),
                    "gold": {"vendor": vendor, "item": item, "quantity": n, "category": category},
                    "template": template_index,
                }
                cases.append(case)
    return cases
