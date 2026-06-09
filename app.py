import streamlit as st
from PIL import Image
from fpdf import FPDF
import tempfile
import os
import hashlib
import io
from datetime import datetime

# ── Library Opsional: Clipboard Paste ─────────────────────────────────
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

# [CHANGE 3] Threshold lebar kolom minimum yang masih layak baca
MIN_COL_WIDTH_MM  = 20.0


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

    [CHANGE 3] Ditambahkan guard max(1, n_cols) untuk cegah ZeroDivisionError
    saat fungsi dipanggil sebelum slider ter-render sempurna.
    """
    n_cols = max(1, n_cols)   # [CHANGE 3] zero-division guard
    return (a4_w_mm - 2 * PAGE_MARGIN_MM - (n_cols - 1) * GAP_MM) / n_cols


def get_exif_date(file_bytes: bytes) -> datetime:
    """
    Ekstrak tanggal pengambilan foto dari metadata Exif.
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
    img_width_mm sebagai parameter agar cache otomatis invalid
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
#  HELPER: HEADER IDENTITAS PRAKTIKAN
#  [CHANGE 2] Font diperkecil & margin diperketat → hemat ~10.5mm vs versi lama
# ═══════════════════════════════════════════════════════════════════════

def estimate_header_height(mata: str, judul: str, tanggal: str) -> float:
    """
    Estimasi tinggi header (mm) SEBELUM PDF di-generate.

    [CHANGE 2] Nilai HARUS sinkron persis dengan draw_header():
      y_start  = 1.0mm  (was 3.0mm)
      line_gap = 0.5mm  (was 1.0mm)
      cell heights: mata=4.0mm, judul=3.5mm, tanggal=3.0mm (semua diperkecil)
      separator+pad = 1.5mm (was 3.0mm)

    Hasil 3 field: 14.5mm  (vs 25.0mm di versi lama → hemat 10.5mm)
    """
    if not any([mata, judul, tanggal]):
        return 0.0
    y = 1.0                     # [CHANGE 2] y_start dikurangi dari 3.0 → 1.0
    if mata:    y += 4.0 + 0.5  # [CHANGE 2] cell 4.0mm + gap 0.5mm
    if judul:   y += 3.5 + 0.5  # [CHANGE 2] cell 3.5mm + gap 0.5mm
    if tanggal: y += 3.0 + 0.5  # [CHANGE 2] cell 3.0mm + gap 0.5mm
    y += 1.5                    # [CHANGE 2] separator + padding (was 3.0mm)
    return y


def draw_header(
    pdf: FPDF,
    mata: str,
    judul: str,
    tanggal: str,
    a4_w_mm: float,
) -> float:
    """
    [CHANGE 2] Cetak header identitas praktikan multi-baris yang kompak.

    Perubahan dari versi sebelumnya:
      - Mata Praktikum : 10pt Bold  → 8pt Bold   (cell h 6mm → 4mm)
      - Judul Modul    : 8pt        → 7pt         (cell h 5mm → 3.5mm)
      - Tanggal        : 7pt Italic → 6pt Italic  (cell h 4mm → 3mm)
      - y_start        : 3.0mm     → 1.0mm
      - line_gap       : 1.0mm     → 0.5mm
      - separator+pad  : 3.0mm     → 1.5mm

    Return: posisi Y absolut (mm) tepat setelah header — tempat foto pertama mulai.
    """
    if not any([mata, judul, tanggal]):
        return TOP_MARGIN_MM

    y        = 1.0    # [CHANGE 2] margin atas dikurangi dari 3.0 → 1.0mm
    line_gap = 0.5    # [CHANGE 2] jarak antar baris dikurangi dari 1.0 → 0.5mm
    usable_w = a4_w_mm - 2 * PAGE_MARGIN_MM

    if mata:
        pdf.set_font("Helvetica", "B", 8)       # [CHANGE 2] was 10pt → 8pt Bold
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(PAGE_MARGIN_MM, y)
        pdf.cell(usable_w, 4.0, mata, align="C")  # [CHANGE 2] cell h: 6mm → 4mm
        y += 4.0 + line_gap

    if judul:
        pdf.set_font("Helvetica", "", 7)        # [CHANGE 2] was 8pt → 7pt
        pdf.set_text_color(50, 50, 50)
        pdf.set_xy(PAGE_MARGIN_MM, y)
        pdf.cell(usable_w, 3.5, judul, align="C")  # [CHANGE 2] cell h: 5mm → 3.5mm
        y += 3.5 + line_gap

    if tanggal:
        pdf.set_font("Helvetica", "I", 6)       # [CHANGE 2] was 7pt → 6pt Italic
        pdf.set_text_color(90, 90, 90)
        pdf.set_xy(PAGE_MARGIN_MM, y)
        pdf.cell(usable_w, 3.0, f"Tanggal: {tanggal}", align="C")  # [CHANGE 2] cell h: 4mm → 3mm
        y += 3.0 + line_gap

    # Garis pemisah tipis
    pdf.set_draw_color(190, 190, 190)
    pdf.set_line_width(0.15)
    pdf.line(PAGE_MARGIN_MM, y, a4_w_mm - PAGE_MARGIN_MM, y)

    # Reset warna & ketebalan garis ke default PDF
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(BORDER_MM)
    pdf.set_text_color(0, 0, 0)
    y += 1.5    # [CHANGE 2] padding setelah garis: 3.0mm → 1.5mm

    return y    # Y absolut awal foto pertama (max 14.5mm jika 3 field diisi)


# ═══════════════════════════════════════════════════════════════════════
#  GLOBAL CSS INJECTION — Upload Zone & Paste Button Redesign
#  Diinjeksikan sekali di awal UI, berlaku untuk seluruh halaman.
# ═══════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
/* ── Upload zone card: target container yang berisi file uploader ── */
[data-testid="stVerticalBlockBorderWrapper"]:has([data-testid="stFileUploader"]) {
    background: linear-gradient(150deg, #F5F7FF 0%, #EDEEFF 100%) !important;
    border: 2px dashed #A5B4FC !important;
    border-radius: 16px !important;
    padding: 4px 8px 10px 8px !important;
    transition: border-color 0.25s ease, box-shadow 0.25s ease !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has([data-testid="stFileUploader"]):hover {
    border-color: #6366F1 !important;
    box-shadow: 0 4px 24px rgba(99,102,241,0.10) !important;
}

/* ── File uploader inner drop zone ─────────────────────────────── */
[data-testid="stFileUploader"] section {
    border-radius: 10px !important;
    border: 1.5px dashed #C7D2FE !important;
    background: rgba(255,255,255,0.75) !important;
    backdrop-filter: blur(4px) !important;
}
[data-testid="stFileUploader"] section:hover {
    border-color: #818CF8 !important;
    background: rgba(255,255,255,0.95) !important;
}

/* ── Clipboard status badge ─────────────────────────────────────── */
.clip-badge {
    display: flex;
    align-items: center;
    gap: 8px;
    background: #EEF2FF;
    border: 1.5px solid #C7D2FE;
    border-radius: 10px;
    padding: 9px 14px;
    margin: 6px 0 2px 0;
}
.clip-badge-text {
    color: #4338CA;
    font-size: 0.84rem;
    font-weight: 500;
    flex: 1;
}

/* ── "atau" divider label ───────────────────────────────────────── */
.or-divider {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 12px 2px 10px 2px;
}
.or-divider-line {
    flex: 1;
    height: 1px;
    background: #E0E7FF;
}
.or-divider-text {
    color: #A5B4FC;
    font-size: 0.70rem;
    font-weight: 700;
    letter-spacing: 0.09em;
    text-transform: uppercase;
}

/* ── Hapus clipboard button: subtle red ghost ───────────────────── */
[data-testid="stBaseButton-secondary"][kind="secondary"] {
    border-color: #FECACA !important;
    color: #DC2626 !important;
}
[data-testid="stBaseButton-secondary"][kind="secondary"]:hover {
    background: #FEF2F2 !important;
    border-color: #F87171 !important;
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
#  UI UTAMA
# ═══════════════════════════════════════════════════════════════════════

# ── Page header ──────────────────────────────────────────────────────
st.markdown("""
<div style="margin-bottom: 4px;">
  <h2 style="margin:0; font-size:1.55rem; font-weight:700; color:#1E1B4B;
             letter-spacing:-0.02em;">
    📸 Foto → PDF Waterfall
  </h2>
  <p style="margin:4px 0 18px 0; font-size:0.875rem; color:#6B7280;">
    Upload foto, atur urutan, dan ekspor ke satu file PDF dengan
    <em>layout waterfall</em> yang rapi.
  </p>
</div>
""", unsafe_allow_html=True)

# ────────────────────────────────────────────────────────────────────────
#  UNIFIED UPLOAD UX — container bergaya dengan CSS injection di atas
# ────────────────────────────────────────────────────────────────────────
if "clipboard_images" not in st.session_state:
    st.session_state.clipboard_images = []

with st.container(border=True):

    # ── Custom header dalam card ──────────────────────────────────────
    st.markdown("""
    <div style="display:flex; align-items:center; gap:10px; padding: 6px 2px 2px 2px;">
      <div style="font-size:1.6rem; line-height:1;">📁</div>
      <div>
        <div style="font-weight:600; font-size:0.92rem; color:#1E1B4B;
                    line-height:1.3;">Tambahkan Foto</div>
        <div style="font-size:0.73rem; color:#6B7280; margin-top:1px;">
          Seret &amp; lepas, atau klik untuk memilih file · JPG · JPEG · PNG
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── File uploader (label disembunyikan, diganti header kustom) ────
    uploaded_files = st.file_uploader(
        "Pilih foto",                   # label aksesibel (disembunyikan)
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        label_visibility="collapsed",   # header kustom di atas sudah menjelaskan
    )

    # ── Paste button + divider ────────────────────────────────────────
    if PASTE_SUPPORTED:
        # Divider "atau"
        st.markdown("""
        <div class="or-divider">
          <div class="or-divider-line"></div>
          <span class="or-divider-text">atau</span>
          <div class="or-divider-line"></div>
        </div>
        """, unsafe_allow_html=True)

        # Paste button — warna indigo yang jelas & konsisten dengan brand card
        paste_result = paste_image_button(
            label="📋  Tempel dari Clipboard",
            background_color="#4F46E5",        # indigo-600: jelas, tidak bertabrakan
            hover_background_color="#3730A3",  # indigo-800: feedback hover tegas
        )

        # Simpan gambar clipboard ke session state
        if paste_result and paste_result.image_data is not None:
            buf = io.BytesIO()
            paste_result.image_data.save(buf, format="PNG")
            fname_clip = f"clipboard_{len(st.session_state.clipboard_images) + 1}.png"
            st.session_state.clipboard_images.append((buf.getvalue(), fname_clip))

    else:
        # Info install — styled warm banner, bukan caption abu-abu polos
        st.markdown("""
        <div style="background:#FFFBEB; border:1.5px solid #FDE68A; border-radius:10px;
                    padding:9px 13px; margin-top:10px; font-size:0.80rem; color:#92400E;
                    display:flex; align-items:center; gap:7px;">
          <span>💡</span>
          <span>Install <code>streamlit-paste-button</code> untuk aktifkan fitur
                tempel dari clipboard.</span>
        </div>
        """, unsafe_allow_html=True)

    # ── Status clipboard — badge styled, bukan caption polos ─────────
    if st.session_state.clipboard_images:
        n_clip = len(st.session_state.clipboard_images)
        st.markdown(f"""
        <div class="clip-badge">
          <span style="font-size:1rem;">✅</span>
          <span class="clip-badge-text">
            {n_clip} gambar dari clipboard siap diproses
          </span>
        </div>
        """, unsafe_allow_html=True)

        if st.button(
            "🗑️  Hapus semua dari clipboard",
            key="btn_del_clipboard",
            use_container_width=True,
        ):
            st.session_state.clipboard_images = []
            st.rerun()

# ────────────────────────────────────────────────────────────────────────
#  [CHANGE 1] Gabungkan semua sumber: file uploader + clipboard
#  Keduanya diperlakukan identik dalam satu list — tidak ada perbedaan
#  antara gambar upload dan gambar paste dari titik ini ke bawah.
# ────────────────────────────────────────────────────────────────────────
all_file_items: list[tuple[bytes, str]] = []  # list of (bytes, filename)
for f in (uploaded_files or []):
    all_file_items.append((f.getvalue(), f.name))
for img_bytes, fname in st.session_state.clipboard_images:
    all_file_items.append((img_bytes, fname))   # [CHANGE 1] merged seamlessly


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
                "Waktu Pengambilan (Exif)",
            ],
        )
    with col2:
        pdf_name = st.text_input(
            "Nama File PDF:",
            value="output_foto",
            placeholder="output_foto"
        )

    # ── Sorting ───────────────────────────────────────────────────────
    if sort_mode == "Nama File A → Z":
        all_file_items = sorted(all_file_items, key=lambda x: x[1].lower())
    elif sort_mode == "Nama File Z → A":
        all_file_items = sorted(all_file_items, key=lambda x: x[1].lower(), reverse=True)
    elif sort_mode == "Waktu Pengambilan (Exif)":
        # Foto tanpa Exif → datetime.min → tidak crash, masuk urutan awal
        all_file_items = sorted(all_file_items, key=lambda x: get_exif_date(x[0]))

    # ════════════════════════════════════════════════════════════════════
    #  ⚙️ Pengaturan Lanjutan
    # ════════════════════════════════════════════════════════════════════
    with st.expander("⚙️ Pengaturan Lanjutan"):

        # ── Identitas Praktikan ───────────────────────────────────────
        st.subheader("🪪 Identitas Praktikan (Opsional)")
        st.caption(
            "Jika diisi, dicetak sebagai header kompak di halaman pertama PDF. "
            "Kosongkan semua field untuk melewatinya."
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

        # ── Orientasi Halaman ─────────────────────────────────────────
        st.subheader("📐 Layout Halaman")
        orientation = st.radio(
            "Orientasi Halaman:",
            options=["Portrait", "Landscape"],
            horizontal=True,
            key="page_orientation",
        )

        # ── Jumlah Kolom Dinamis (reaktif terhadap orientasi) ─────────
        # Reset slider ke default baru saat orientasi berubah
        _cols_default = 4 if orientation == "Landscape" else 3
        if st.session_state.get("_last_orient") != orientation:
            st.session_state["n_cols_slider"] = _cols_default
            st.session_state["_last_orient"]  = orientation

        # [CHANGE 3] max_value diubah dari 4 → 10
        n_cols = st.slider(
            "Jumlah Kolom:",
            min_value=1,
            max_value=10,           # [CHANGE 3] was 4 → sekarang 10
            key="n_cols_slider",
            help=(
                "Default otomatis: Portrait=3, Landscape=4. "
                "Kolom ≥8 menghasilkan foto sangat kecil — gunakan orientasi Landscape."
            ),
        )

        st.divider()

        # ── Kualitas JPEG ─────────────────────────────────────────────
        st.subheader("🖼️ Kualitas Gambar")
        jpeg_quality = st.slider(
            "Kualitas JPEG:",
            min_value=10,
            max_value=100,
            value=80,
            step=5,
            key="jpeg_quality_slider",
            help="Lebih tinggi = gambar lebih tajam tapi ukuran file lebih besar.",
        )

    # ── Hitung dimensi halaman berdasarkan orientasi ──────────────────
    if orientation == "Landscape":
        A4_W = A4_H_PORTRAIT   # 297mm → lebar landscape
        A4_H = A4_W_PORTRAIT   # 210mm → tinggi landscape
    else:
        A4_W = A4_W_PORTRAIT   # 210mm
        A4_H = A4_H_PORTRAIT   # 297mm

    # [CHANGE 3] IMG_WIDTH_MM dihitung dari n_cols yang bisa sampai 10;
    #            compute_img_width memiliki guard max(1, n_cols) untuk keamanan
    IMG_WIDTH_MM   = compute_img_width(A4_W, n_cols)
    LEFT_MARGIN_MM = PAGE_MARGIN_MM
    col_x          = [LEFT_MARGIN_MM + c * (IMG_WIDTH_MM + GAP_MM) for c in range(n_cols)]

    # [CHANGE 3] Peringatan jika lebar kolom sangat sempit (di bawah threshold)
    if IMG_WIDTH_MM < MIN_COL_WIDTH_MM:
        st.warning(
            f"⚠️ Lebar foto per kolom: **{IMG_WIDTH_MM:.1f}mm** — sangat sempit dan "
            f"mungkin tidak terbaca dengan jelas. "
            f"Kurangi jumlah kolom atau pilih orientasi **Landscape**."
        )

    # ── Proses semua gambar ───────────────────────────────────────────
    image_data: list[tuple] = []
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
    # [CHANGE 2] estimate_header_height sekarang sinkron dengan draw_header baru
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
        f"📐 {orientation} · {n_cols} kolom · {IMG_WIDTH_MM:.1f}mm/kolom · JPEG {jpeg_quality}"
    )

    # ════════════════════════════════════════════════════════════════════
    #  GENERATE PDF
    # ════════════════════════════════════════════════════════════════════
    if st.button("✅ Generate PDF", type="primary", use_container_width=True):
        progress_bar = st.progress(0, text="Menyiapkan PDF...")

        # Setup FPDF sesuai orientasi
        fpdf_orient = "L" if orientation == "Landscape" else "P"
        pdf = FPDF(orientation=fpdf_orient, unit="mm", format="A4")
        pdf.add_page()

        max_y = A4_H - BOTTOM_MARGIN_MM

        # [CHANGE 2] Cetak header kompak di halaman pertama (jika ada isian)
        if has_header:
            first_y = draw_header(
                pdf, mata_praktikum, judul_modul, tanggal_praktikum, A4_W
            )
        else:
            first_y = TOP_MARGIN_MM

        col_heights = [first_y] * n_cols

        # ── Loop waterfall ────────────────────────────────────────────
        for i, (img, h_mm, fname) in enumerate(image_data):
            slot_h  = h_mm + extra_h
            min_col = col_heights.index(min(col_heights))
            x       = col_x[min_col]
            y       = col_heights[min_col]

            # Pindah ke halaman baru jika foto tidak muat di halaman ini
            if y + slot_h > max_y:
                pdf.add_page()
                col_heights = [TOP_MARGIN_MM] * n_cols
                min_col     = 0
                x           = col_x[min_col]
                y           = col_heights[min_col]

            # Simpan gambar ke file sementara, lalu sisipkan ke PDF
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                temp_path = tmp.name
                img.save(temp_path, "JPEG", quality=jpeg_quality)

            pdf.image(temp_path, x=x, y=y, w=IMG_WIDTH_MM, h=h_mm)
            os.remove(temp_path)

            # Border gambar
            pdf.set_draw_color(0, 0, 0)
            pdf.set_line_width(BORDER_MM)
            pdf.rect(x, y, IMG_WIDTH_MM, h_mm)

            # Caption (jika aktif)
            if enable_captions:
                raw = get_caption(i, fname)
                if raw:
                    pdf.set_font("Helvetica", size=CAPTION_FONT_PT)
                    pdf.set_text_color(0, 0, 0)
                    final = fit_caption(pdf, raw, IMG_WIDTH_MM - 1)
                    if final:
                        cap_y  = y + h_mm + 0.8
                        safe_x = max(0.0, x)   # safeguard: x tidak pernah negatif
                        pdf.set_xy(safe_x, cap_y)
                        pdf.cell(IMG_WIDTH_MM, CAPTION_HEIGHT_MM - 0.8, final, align="C")

            col_heights[min_col] = y + slot_h + GAP_MM
            progress_bar.progress(
                (i + 1) / n_photos,
                text=f"Memproses foto {i + 1}/{n_photos}..."
            )

        # ── Output PDF ke bytes ───────────────────────────────────────
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

        # Simulasi waterfall → tentukan foto mana masuk kolom mana
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
                        # Gunakan cap_key yang SAMA persis dengan yang dibaca saat generate PDF
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