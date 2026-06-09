import streamlit as st
from PIL import Image
from fpdf import FPDF
import tempfile
import os
import hashlib
import io
from datetime import datetime

# ── Library Opsional: Clipboard Paste (Fitur 6) ───────────────────────
try:
    from streamlit_paste_button import paste_image_button
    PASTE_SUPPORTED = True
except ImportError:
    PASTE_SUPPORTED = False

# ── Konfigurasi Halaman ───────────────────────────────────────────────
st.set_page_config(
    page_title="Foto Praktikum → PDF Print",
    page_icon="📸",
    layout="centered"
)

# ── Konstanta Tetap (tidak bergantung orientasi/kolom) ────────────────
DPI               = 300
A4_W_PORTRAIT     = 210   # lebar A4 portrait (mm)
A4_H_PORTRAIT     = 297   # tinggi A4 portrait (mm)
GAP_MM            = 1
PAGE_MARGIN_MM    = 2
TOP_MARGIN_MM     = 0
BOTTOM_MARGIN_MM  = 0
BORDER_MM         = 0.5
CAPTION_HEIGHT_MM = 4.0
CAPTION_FONT_PT   = 5


# ═══════════════════════════════════════════════════════════════════════
#  HELPER: CAPTION
# ═══════════════════════════════════════════════════════════════════════

def cap_key(i: int, fname: str) -> str:
    """Widget key aman berbasis hash nama file (hindari karakter ilegal)."""
    h = hashlib.md5(fname.encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"wfc_{i}_{h}"


def default_caption(fname: str) -> str:
    return os.path.splitext(fname)[0]


def init_captions(image_data: list):
    """Inisialisasi semua widget key caption SEBELUM rendering apapun."""
    for i, (_, _, fname) in enumerate(image_data):
        k = cap_key(i, fname)
        if k not in st.session_state:
            st.session_state[k] = default_caption(fname)


def get_caption(i: int, fname: str) -> str:
    """Baca caption langsung dari session state (no intermediate dict)."""
    val = st.session_state.get(cap_key(i, fname), "").strip()
    return val if val else default_caption(fname)


# ═══════════════════════════════════════════════════════════════════════
#  HELPER: DIMENSI & GAMBAR
# ═══════════════════════════════════════════════════════════════════════

def mm_to_px(mm: float) -> int:
    return int(mm * DPI / 25.4)


def compute_img_width(a4_w_mm: float, n_cols: int) -> float:
    """
    Hitung lebar kolom gambar secara dinamis agar tidak overflow.
    Formula: (lebar_halaman - 2×margin - (n_kolom-1)×gap) / n_kolom
    """
    return (a4_w_mm - 2 * PAGE_MARGIN_MM - (n_cols - 1) * GAP_MM) / n_cols


def get_exif_date(file_bytes: bytes) -> datetime:
    """
    Fitur 5: Ekstrak tanggal pengambilan foto dari metadata Exif.
    Fallback ke datetime.min jika tidak ada Exif (foto screenshot, dll.)
    sehingga aplikasi tidak crash dan foto tetap masuk urutan.
    """
    try:
        img = Image.open(io.BytesIO(file_bytes))
        exif_data = img._getexif()
        if exif_data:
            dt_str = exif_data.get(36867)   # Tag 36867 = DateTimeOriginal
            if dt_str:
                return datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return datetime.min   # fallback aman: tidak crash, muncul di awal urutan


@st.cache_data
def process_image_data(file_bytes: bytes, img_width_mm: float):
    """
    Buka, rotasi (jika portrait), dan resize gambar sesuai lebar kolom.
    img_width_mm ikut sebagai parameter agar cache otomatis invalid
    saat jumlah kolom atau orientasi berubah.
    """
    try:
        img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        if img.height > img.width:
            img = img.rotate(-90, expand=True)
        target_w = mm_to_px(img_width_mm)
        ratio    = target_w / img.width
        target_h = int(img.height * ratio)
        img      = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        h_mm     = img_width_mm * img.height / img.width
        return img, h_mm
    except Exception:
        return None, None


# ═══════════════════════════════════════════════════════════════════════
#  HELPER: ALGORITMA WATERFALL & ESTIMASI HALAMAN
# ═══════════════════════════════════════════════════════════════════════

def simulate_waterfall(
    image_list: list,
    n_cols: int,
    a4_h_mm: float,
    extra_h: float = 0,
) -> list:
    """
    Simulasi penempatan foto ke kolom (identik dengan logika PDF generation).
    Return: list indeks kolom untuk tiap foto.
    """
    if not image_list:
        return []
    max_y       = a4_h_mm - BOTTOM_MARGIN_MM
    col_heights = [TOP_MARGIN_MM] * n_cols
    col_assign  = []
    for _, h_mm, _ in image_list:
        slot_h  = h_mm + extra_h
        min_col = col_heights.index(min(col_heights))
        y       = col_heights[min_col]
        if y + slot_h > max_y:
            col_heights = [TOP_MARGIN_MM] * n_cols
            min_col     = 0
            y           = col_heights[min_col]
        col_assign.append(min_col)
        col_heights[min_col] += slot_h + GAP_MM
    return col_assign


def estimate_pages(
    image_list: list,
    n_cols: int,
    a4_h_mm: float,
    extra_h: float = 0,
    page1_start_y: float = 0,
) -> int:
    """
    Hitung estimasi jumlah halaman PDF.
    page1_start_y: Y awal di halaman 1 (offset karena header identitas).
    """
    if not image_list:
        return 0
    max_y       = a4_h_mm - BOTTOM_MARGIN_MM
    col_heights = [page1_start_y] * n_cols
    pages       = 1
    for _, h_mm, _ in image_list:
        slot_h  = h_mm + extra_h
        min_col = col_heights.index(min(col_heights))
        y       = col_heights[min_col]
        if y + slot_h > max_y:
            pages      += 1
            col_heights = [TOP_MARGIN_MM] * n_cols
            min_col     = 0
        col_heights[min_col] += slot_h + GAP_MM
    return pages


def fit_caption(pdf: FPDF, text: str, max_width_mm: float) -> str:
    """Potong teks agar muat dalam lebar kolom, tambah '...' jika dipotong."""
    if not text:
        return ""
    original = text
    while text and pdf.get_string_width(text) > max_width_mm:
        text = text[:-1]
    if len(text) < len(original):
        while text and pdf.get_string_width(text + "...") > max_width_mm:
            text = text[:-1]
        text += "..."
    return text


# ═══════════════════════════════════════════════════════════════════════
#  HELPER: HEADER IDENTITAS (Fitur 1) — kompak, font kecil, tanpa background
# ═══════════════════════════════════════════════════════════════════════

# Konstanta header yang sangat kompak agar tidak boros ruang gambar
_HDR_LINE_GAP   = 0.4   # jarak antar baris (mm)
_HDR_MATA_H     = 3.5   # tinggi cell mata praktikum (mm), font 7pt bold
_HDR_JUDUL_H    = 3.0   # tinggi cell judul modul (mm), font 6pt
_HDR_TGL_H      = 2.8   # tinggi cell tanggal (mm), font 5pt italic
_HDR_SEP_PAD    = 1.5   # padding setelah garis pemisah (mm)
_HDR_TOP_PAD    = 1.5   # padding dari tepi atas kertas (mm)


def estimate_header_height(mata: str, judul: str, tanggal: str) -> float:
    """
    Estimasi tinggi header (mm) SEBELUM PDF di-generate.
    Konsisten dengan draw_header() agar estimasi halaman akurat.
    """
    y = _HDR_TOP_PAD
    if mata:    y += _HDR_MATA_H + _HDR_LINE_GAP
    if judul:   y += _HDR_JUDUL_H + _HDR_LINE_GAP
    if tanggal: y += _HDR_TGL_H + _HDR_LINE_GAP
    y += _HDR_SEP_PAD   # garis tipis + padding bawah
    return y


def draw_header(
    pdf: FPDF,
    mata: str,
    judul: str,
    tanggal: str,
    a4_w_mm: float,
) -> float:
    """
    Cetak header identitas praktikan di dalam area halaman A4 (tanpa background).
    Huruf kecil & kompak agar tidak memakan ruang gambar secara signifikan.
    Return: posisi Y absolut (mm) tepat setelah header.
    """
    y        = _HDR_TOP_PAD
    usable_w = a4_w_mm - 2 * PAGE_MARGIN_MM

    if mata:
        pdf.set_font("Helvetica", "B", 7)       # bold 7pt — kecil tapi terbaca
        pdf.set_text_color(20, 20, 20)
        pdf.set_xy(PAGE_MARGIN_MM, y)
        pdf.cell(usable_w, _HDR_MATA_H, mata, align="C")
        y += _HDR_MATA_H + _HDR_LINE_GAP

    if judul:
        pdf.set_font("Helvetica", "", 6)        # regular 6pt
        pdf.set_text_color(50, 50, 50)
        pdf.set_xy(PAGE_MARGIN_MM, y)
        pdf.cell(usable_w, _HDR_JUDUL_H, judul, align="C")
        y += _HDR_JUDUL_H + _HDR_LINE_GAP

    if tanggal:
        pdf.set_font("Helvetica", "I", 5)       # italic 5pt
        pdf.set_text_color(90, 90, 90)
        pdf.set_xy(PAGE_MARGIN_MM, y)
        pdf.cell(usable_w, _HDR_TGL_H, f"Tanggal: {tanggal}", align="C")
        y += _HDR_TGL_H + _HDR_LINE_GAP

    # Garis pemisah sangat tipis
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.2)
    pdf.line(PAGE_MARGIN_MM, y + 0.3, a4_w_mm - PAGE_MARGIN_MM, y + 0.3)

    # Reset ke default
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(BORDER_MM)
    pdf.set_text_color(0, 0, 0)
    y += _HDR_SEP_PAD

    return y   # Y absolut awal foto pertama


# ═══════════════════════════════════════════════════════════════════════
#  UI UTAMA
# ═══════════════════════════════════════════════════════════════════════

st.title("📸 Foto → PDF Waterfall")
st.markdown(
    "Upload foto, atur urutan, dan jadikan satu file PDF "
    "dengan *layout waterfall* yang rapi."
)

# ────────────────────────────────────────────────────────────────────────
#  Upload via File Uploader
# ────────────────────────────────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "➕ Tambahkan Foto (JPG, JPEG, PNG)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

# ────────────────────────────────────────────────────────────────────────
#  Fitur 6: Upload via Clipboard Paste
#  BUG FIX: paste_image_button mengembalikan gambar terakhir di SETIAP rerun.
#  Solusi: simpan hash setiap gambar yang sudah ditambahkan; skip duplikat.
# ────────────────────────────────────────────────────────────────────────
if "clipboard_images" not in st.session_state:
    st.session_state.clipboard_images = []

if "clipboard_hashes" not in st.session_state:
    st.session_state.clipboard_hashes = set()

if PASTE_SUPPORTED:
    paste_result = paste_image_button(
        label="📋 Tempel dari Clipboard (Ctrl+V / Cmd+V)",
        background_color="#f0f2f6",
        hover_background_color="#dce0e8",
    )
    if paste_result and paste_result.image_data is not None:
        buf = io.BytesIO()
        paste_result.image_data.save(buf, format="PNG")
        img_bytes = buf.getvalue()
        # Hanya tambahkan jika hash belum pernah disimpan sebelumnya
        img_hash = hashlib.md5(img_bytes).hexdigest()
        if img_hash not in st.session_state.clipboard_hashes:
            st.session_state.clipboard_hashes.add(img_hash)
            fname_clip = f"clipboard_{len(st.session_state.clipboard_images) + 1}.png"
            st.session_state.clipboard_images.append((img_bytes, fname_clip))

    if st.session_state.clipboard_images:
        c1, c2 = st.columns([4, 1])
        with c1:
            st.caption(
                f"📋 {len(st.session_state.clipboard_images)} gambar dari clipboard ditambahkan."
            )
        with c2:
            if st.button("🗑️ Hapus Semua", use_container_width=True):
                st.session_state.clipboard_images = []
                st.session_state.clipboard_hashes = set()   # reset hash juga
                st.rerun()
else:
    st.caption(
        "ℹ️ Fitur paste clipboard tidak aktif. "
        "Pastikan `streamlit-paste-button` sudah terinstall."
    )

# ────────────────────────────────────────────────────────────────────────
#  Gabungkan semua sumber: file uploader + clipboard
# ────────────────────────────────────────────────────────────────────────
all_file_items = []   # list of (bytes, filename)
for f in (uploaded_files or []):
    all_file_items.append((f.getvalue(), f.name))
for img_bytes, fname in st.session_state.clipboard_images:
    all_file_items.append((img_bytes, fname))


# ════════════════════════════════════════════════════════════════════════
#  Konten utama: hanya muncul jika ada gambar
# ════════════════════════════════════════════════════════════════════════
if all_file_items:

    # ── Baris kontrol utama: Urutan & Nama PDF ────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        sort_mode = st.selectbox(
            "Urutan Foto:",
            options=[
                "Sesuai Urutan Upload",
                "Nama File A → Z",
                "Nama File Z → A",
                "Waktu Pengambilan (Exif)",   # Fitur 5
            ],
        )
    with col2:
        pdf_name = st.text_input(
            "Nama File PDF:",
            value="output_foto",
            placeholder="output_foto"
        )

    # ── Sorting (Fitur 5: Exif dengan safe fallback) ──────────────────
    if sort_mode == "Nama File A → Z":
        all_file_items = sorted(all_file_items, key=lambda x: x[1].lower())
    elif sort_mode == "Nama File Z → A":
        all_file_items = sorted(all_file_items, key=lambda x: x[1].lower(), reverse=True)
    elif sort_mode == "Waktu Pengambilan (Exif)":
        all_file_items = sorted(all_file_items, key=lambda x: get_exif_date(x[0]))

    # ════════════════════════════════════════════════════════════════════
    #  ⚙️ Pengaturan Lanjutan (semua fitur opsional)
    # ════════════════════════════════════════════════════════════════════
    with st.expander("⚙️ Pengaturan Lanjutan"):

        # ── Fitur 1: Identitas Praktikan ──────────────────────────────
        st.subheader("🪪 Identitas Praktikan (Opsional)")
        st.caption(
            "Jika diisi, dicetak sebagai header mini di dalam halaman pertama PDF "
            "(font sangat kecil, tanpa background, tidak mengurangi kapasitas gambar secara signifikan)."
        )

        id_c1, id_c2 = st.columns(2)
        with id_c1:
            mata_praktikum = st.text_input(
                "Mata Praktikum",
                placeholder="Sistem Kendali Digital",
                key="id_mata",
            )
            judul_modul = st.text_input(
                "Judul Modul",
                placeholder="Modul 1: Kontrol PID",
                key="id_judul",
            )
        with id_c2:
            tanggal_praktikum = st.text_input(
                "Tanggal Praktikum",
                placeholder="7 Juni 2026",
                key="id_tanggal",
            )

        st.divider()

        # ── Fitur 2: Orientasi Halaman ────────────────────────────────
        st.subheader("📐 Layout Halaman")
        orientation = st.radio(
            "Orientasi Halaman:",
            options=["Portrait", "Landscape"],
            horizontal=True,
            key="page_orientation",
        )

        # ── Fitur 3: Jumlah Kolom Dinamis ─────────────────────────────
        # Default: 3 (portrait) / 4 (landscape) — tidak berubah
        # Max slider dinaikkan ke 10
        _cols_default = 4 if orientation == "Landscape" else 3
        if st.session_state.get("_last_orient") != orientation:
            st.session_state["n_cols_slider"] = _cols_default
            st.session_state["_last_orient"]  = orientation

        n_cols = st.slider(
            "Jumlah Kolom:",
            min_value=1,
            max_value=10,          # ← dinaikkan dari 4 ke 10
            key="n_cols_slider",
            help="Otomatis berubah ke 4 saat Landscape, 3 saat Portrait. Maks 10 kolom.",
        )

        st.divider()

        # ── Fitur 4: Kualitas JPEG / Kompresi ────────────────────────
        st.subheader("🖼️ Kualitas Gambar")
        jpeg_quality = st.slider(
            "Kualitas JPEG:",
            min_value=10,
            max_value=100,
            value=100,             # ← default diubah dari 80 ke 100
            step=5,
            key="jpeg_quality_slider",
            help="Lebih tinggi = gambar lebih tajam tapi ukuran file lebih besar.",
        )

    # ── Hitung dimensi halaman berdasarkan orientasi (Fitur 2) ────────
    if orientation == "Landscape":
        A4_W = A4_H_PORTRAIT   # 297mm → lebar landscape
        A4_H = A4_W_PORTRAIT   # 210mm → tinggi landscape
    else:
        A4_W = A4_W_PORTRAIT   # 210mm
        A4_H = A4_H_PORTRAIT   # 297mm

    IMG_WIDTH_MM   = compute_img_width(A4_W, n_cols)
    LEFT_MARGIN_MM = PAGE_MARGIN_MM
    col_x          = [LEFT_MARGIN_MM + c * (IMG_WIDTH_MM + GAP_MM) for c in range(n_cols)]

    # ── Proses semua gambar ───────────────────────────────────────────
    image_data = []
    for file_bytes, fname in all_file_items:
        img, h_mm = process_image_data(file_bytes, IMG_WIDTH_MM)
        if img:
            image_data.append((img, h_mm, fname))

    n_photos = len(image_data)

    # ── Checkbox Caption ──────────────────────────────────────────────
    enable_captions = st.checkbox(
        "🏷️ Tambahkan keterangan pada setiap foto",
        value=False,
        help="Aktifkan untuk menambahkan teks keterangan di bawah tiap foto dalam PDF.",
    )
    extra_h = CAPTION_HEIGHT_MM if enable_captions else 0

    # Inisialisasi caption state SEBELUM rendering apapun
    init_captions(image_data)

    # ── Estimasi halaman (memperhitungkan tinggi header jika ada) ──────
    has_header    = any([mata_praktikum, judul_modul, tanggal_praktikum])
    page1_start_y = (
        estimate_header_height(mata_praktikum, judul_modul, tanggal_praktikum)
        if has_header
        else TOP_MARGIN_MM
    )
    est_pages = estimate_pages(
        image_data, n_cols, A4_H, extra_h=extra_h, page1_start_y=page1_start_y
    )

    st.info(
        f"📷 **{n_photos}** foto siap diproses  |  "
        f"📄 Estimasi **{est_pages}** halaman PDF  |  "
        f"📐 {orientation} · {n_cols} kolom · JPEG {jpeg_quality}"
    )

    # ════════════════════════════════════════════════════════════════════
    #  GENERATE PDF
    # ════════════════════════════════════════════════════════════════════
    if st.button("✅ Generate PDF", type="primary", use_container_width=True):
        progress_bar = st.progress(0, text="Menyiapkan PDF...")

        fpdf_orient = "L" if orientation == "Landscape" else "P"
        pdf = FPDF(orientation=fpdf_orient, unit="mm", format="A4")
        pdf.add_page()

        max_y = A4_H - BOTTOM_MARGIN_MM

        if has_header:
            first_y = draw_header(
                pdf, mata_praktikum, judul_modul, tanggal_praktikum, A4_W
            )
        else:
            first_y = TOP_MARGIN_MM

        col_heights = [first_y] * n_cols

        for i, (img, h_mm, fname) in enumerate(image_data):
            slot_h  = h_mm + extra_h
            min_col = col_heights.index(min(col_heights))
            x       = col_x[min_col]
            y       = col_heights[min_col]

            if y + slot_h > max_y:
                pdf.add_page()
                col_heights = [TOP_MARGIN_MM] * n_cols
                min_col     = 0
                x           = col_x[min_col]
                y           = col_heights[min_col]

            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                temp_path = tmp.name
                img.save(temp_path, "JPEG", quality=jpeg_quality)

            pdf.image(temp_path, x=x, y=y, w=IMG_WIDTH_MM, h=h_mm)
            os.remove(temp_path)

            pdf.set_draw_color(0, 0, 0)
            pdf.set_line_width(BORDER_MM)
            pdf.rect(x, y, IMG_WIDTH_MM, h_mm)

            if enable_captions:
                raw = get_caption(i, fname)
                if raw:
                    pdf.set_font("Helvetica", size=CAPTION_FONT_PT)
                    pdf.set_text_color(0, 0, 0)
                    final = fit_caption(pdf, raw, IMG_WIDTH_MM - 1)
                    if final:
                        cap_y  = y + h_mm + 0.8
                        safe_x = max(0.0, x)
                        pdf.set_xy(safe_x, cap_y)
                        pdf.cell(IMG_WIDTH_MM, CAPTION_HEIGHT_MM - 0.8, final, align="C")

            col_heights[min_col] = y + slot_h + GAP_MM
            progress_bar.progress(
                (i + 1) / n_photos,
                text=f"Memproses foto {i + 1}/{n_photos}..."
            )

        safe_name    = "".join(
            c for c in pdf_name if c.isalnum() or c in (" ", "_", "-")
        ).strip()
        output_fname = (safe_name or "output_foto") + ".pdf"

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
            pdf_path = tmp_pdf.name
            pdf.output(pdf_path)

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        os.remove(pdf_path)
        progress_bar.empty()

        st.success("🎉 Selesai! PDF berhasil dibuat.")
        st.download_button(
            label="📥 Unduh File PDF",
            data=pdf_bytes,
            file_name=output_fname,
            mime="application/pdf",
            use_container_width=True,
        )

    # ════════════════════════════════════════════════════════════════════
    #  PREVIEW GALERI
    # ════════════════════════════════════════════════════════════════════
    with st.expander("👀 Lihat Preview Galeri Foto"):
        if enable_captions:
            hdr_col, btn_col = st.columns([4, 1])
            with hdr_col:
                st.caption("✏️ Isi keterangan di bawah tiap foto. Kosongkan jika tidak perlu.")
            with btn_col:
                if st.button(
                    "🔄 Reset",
                    help="Kembalikan semua keterangan ke nama file",
                    use_container_width=True,
                ):
                    for i, (_, _, fname) in enumerate(image_data):
                        st.session_state[cap_key(i, fname)] = default_caption(fname)
                    st.rerun()

        col_assign  = simulate_waterfall(image_data, n_cols, A4_H, extra_h=extra_h)
        cols_photos = [[] for _ in range(n_cols)]
        for idx, c in enumerate(col_assign):
            cols_photos[c].append(idx)

        preview_cols = st.columns(n_cols)
        for col_idx in range(n_cols):
            with preview_cols[col_idx]:
                for photo_idx in cols_photos[col_idx]:
                    img, _, fname = image_data[photo_idx]
                    st.image(img, use_container_width=True)
                    if enable_captions:
                        st.text_input(
                            label="keterangan",
                            key=cap_key(photo_idx, fname),
                            max_chars=80,
                            label_visibility="collapsed",
                            placeholder="Keterangan foto...",
                        )
                    else:
                        st.caption(f"[{photo_idx + 1}] {fname}")

else:
    st.info(
        "📂 Silakan upload foto untuk memulai. "
        "Mendukung format **JPG**, **JPEG**, dan **PNG**."
    )