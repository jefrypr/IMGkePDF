import streamlit as st
from PIL import Image
from fpdf import FPDF
import tempfile
import os
import hashlib
import io
from datetime import datetime

# ── Library Opsional: Clipboard Paste ────────────────────────────────
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

# ── Tema Warna Konsisten ──────────────────────────────────────────────
st.markdown("""
<style>
    /* ── Base & Background ── */
    .stApp { background-color: #F0F4FB; }
    section[data-testid="stSidebar"] { background-color: #E4EBF7; }

    /* ── Title ── */
    h1 { color: #1E3A6E !important; font-weight: 700; letter-spacing: -0.5px; }
    h2, h3 { color: #2C5096 !important; }

    /* ── Primary Button ── */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #2C5096, #3D7ECC);
        color: #FFFFFF;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        letter-spacing: 0.3px;
        transition: opacity 0.2s;
    }
    .stButton > button[kind="primary"]:hover { opacity: 0.88; }

    /* ── Secondary Button ── */
    .stButton > button {
        border-radius: 8px;
        border: 1.5px solid #3D7ECC;
        color: #2C5096;
        font-weight: 500;
    }

    /* ── Info / Success / Warning boxes ── */
    .stAlert { border-radius: 8px; }

    /* ── Expander ── */
    .streamlit-expanderHeader {
        background-color: #D9E5F7 !important;
        border-radius: 8px !important;
        color: #1E3A6E !important;
        font-weight: 600;
    }
    .streamlit-expanderContent { background-color: #EBF1FB; border-radius: 0 0 8px 8px; }

    /* ── Text inputs / Select / Slider ── */
    .stTextInput > div > div > input,
    .stSelectbox > div > div {
        border-radius: 6px;
        border-color: #9AB6E0 !important;
    }
    .stSlider > div > div > div > div { background-color: #2C5096 !important; }

    /* ── Progress bar ── */
    .stProgress > div > div > div { background-color: #3D7ECC; }

    /* ── Download button ── */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #1E7A4E, #27A865);
        color: #FFFFFF;
        border: none;
        border-radius: 8px;
        font-weight: 600;
    }
    .stDownloadButton > button:hover { opacity: 0.88; }

    /* ── Divider ── */
    hr { border-color: #BDD0EE; }

    /* ── Caption ── */
    .stCaption { color: #5A7AAD; }

    /* ── Checkbox ── */
    .stCheckbox span { color: #1E3A6E; }
</style>
""", unsafe_allow_html=True)

# ── Konstanta Tetap ───────────────────────────────────────────────────
DPI               = 300
A4_W_PORTRAIT     = 210
A4_H_PORTRAIT     = 297
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
    h = hashlib.md5(fname.encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"wfc_{i}_{h}"


def default_caption(fname: str) -> str:
    return os.path.splitext(fname)[0]


def init_captions(image_data: list):
    for i, (_, _, fname) in enumerate(image_data):
        k = cap_key(i, fname)
        if k not in st.session_state:
            st.session_state[k] = default_caption(fname)


def get_caption(i: int, fname: str) -> str:
    val = st.session_state.get(cap_key(i, fname), "").strip()
    return val if val else default_caption(fname)


# ═══════════════════════════════════════════════════════════════════════
#  HELPER: DIMENSI & GAMBAR
# ═══════════════════════════════════════════════════════════════════════

def mm_to_px(mm: float) -> int:
    return int(mm * DPI / 25.4)


def compute_img_width(a4_w_mm: float, n_cols: int) -> float:
    return (a4_w_mm - 2 * PAGE_MARGIN_MM - (n_cols - 1) * GAP_MM) / n_cols


def get_exif_date(file_bytes: bytes) -> datetime:
    try:
        img = Image.open(io.BytesIO(file_bytes))
        exif_data = img._getexif()
        if exif_data:
            dt_str = exif_data.get(36867)
            if dt_str:
                return datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return datetime.min


@st.cache_data
def process_image_data(file_bytes: bytes, img_width_mm: float):
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

def simulate_waterfall(image_list, n_cols, a4_h_mm, extra_h=0):
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


def estimate_pages(image_list, n_cols, a4_h_mm, extra_h=0, page1_start_y=0):
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
#  HELPER: HEADER IDENTITAS — kompak, di dalam batas kertas A4
#  Semua teks kecil (≤7pt), satu baris per field, tanpa background.
#  Total tinggi: ≤ 5 mm agar tidak mengorbankan banyak ruang gambar.
# ═══════════════════════════════════════════════════════════════════════

HEADER_LINE_H  = 3.2   # tinggi tiap baris teks (mm)
HEADER_SEP     = 0.4   # jarak antar baris (mm)
HEADER_PAD_BOT = 1.0   # padding bawah setelah semua baris


def estimate_header_height(mata: str, judul: str, tanggal: str) -> float:
    """Estimasi total tinggi header (mm) agar konsisten dengan draw_header."""
    n_lines = sum(1 for s in [mata, judul, tanggal] if s)
    if n_lines == 0:
        return 0.0
    return n_lines * HEADER_LINE_H + (n_lines - 1) * HEADER_SEP + HEADER_PAD_BOT


def draw_header(pdf: FPDF, mata: str, judul: str, tanggal: str, a4_w_mm: float) -> float:
    """
    Cetak header identitas yang sangat kompak di dalam batas A4.
    Semua informasi dalam satu baris kecil (≤7pt), tanpa background.
    Return: posisi Y absolut (mm) awal foto pertama.
    """
    usable_w = a4_w_mm - 2 * PAGE_MARGIN_MM
    y        = TOP_MARGIN_MM + 0.5   # mulai 0.5 mm dari atas

    lines = []
    if mata:
        lines.append(("B", 7, mata))
    if judul:
        lines.append(("", 6, judul))
    if tanggal:
        lines.append(("I", 5.5, f"Tanggal: {tanggal}"))

    for style, pt, text in lines:
        pdf.set_font("Helvetica", style, pt)
        pdf.set_text_color(30, 30, 30)
        pdf.set_xy(PAGE_MARGIN_MM, y)
        pdf.cell(usable_w, HEADER_LINE_H, text, align="C")
        y += HEADER_LINE_H + HEADER_SEP

    # Garis tipis pemisah (0.2 mm tebal, abu terang)
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.2)
    pdf.line(PAGE_MARGIN_MM, y + 0.1, a4_w_mm - PAGE_MARGIN_MM, y + 0.1)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(BORDER_MM)
    pdf.set_text_color(0, 0, 0)

    y += HEADER_PAD_BOT
    return y


# ═══════════════════════════════════════════════════════════════════════
#  UI UTAMA
# ═══════════════════════════════════════════════════════════════════════

st.title("📸 Foto → PDF Waterfall")
st.markdown(
    "<span style='color:#5A7AAD'>Upload foto, atur urutan, dan jadikan satu file PDF "
    "dengan <i>layout waterfall</i> yang rapi.</span>",
    unsafe_allow_html=True,
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
#  Upload via Clipboard Paste
#  BUG FIX: Gunakan hash MD5 gambar untuk mendeteksi duplikat.
#  Hanya tambahkan ke daftar jika hash belum pernah diproses sebelumnya.
# ────────────────────────────────────────────────────────────────────────
if "clipboard_images" not in st.session_state:
    st.session_state.clipboard_images = []

if "clipboard_hashes" not in st.session_state:
    st.session_state.clipboard_hashes = set()

if PASTE_SUPPORTED:
    paste_result = paste_image_button(
        label="📋 Tempel dari Clipboard (Ctrl+V / Cmd+V)",
        background_color="#D9E5F7",
        hover_background_color="#BDD0EE",
    )
    # Hanya tambahkan jika ada gambar DAN hashnya belum ada (cegah duplikat)
    if paste_result and paste_result.image_data is not None:
        buf = io.BytesIO()
        paste_result.image_data.save(buf, format="PNG")
        img_bytes = buf.getvalue()
        img_hash  = hashlib.md5(img_bytes).hexdigest()

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
                st.session_state.clipboard_hashes = set()   # reset hashes juga
                st.rerun()
else:
    st.caption(
        "ℹ️ Fitur paste clipboard tidak aktif. "
        "Pastikan `streamlit-paste-button` sudah terinstall."
    )

# ── Gabungkan semua sumber ─────────────────────────────────────────────
all_file_items = []
for f in (uploaded_files or []):
    all_file_items.append((f.getvalue(), f.name))
for img_bytes, fname in st.session_state.clipboard_images:
    all_file_items.append((img_bytes, fname))


# ════════════════════════════════════════════════════════════════════════
#  Konten utama
# ════════════════════════════════════════════════════════════════════════
if all_file_items:

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
        all_file_items = sorted(all_file_items, key=lambda x: get_exif_date(x[0]))

    # ════════════════════════════════════════════════════════════════════
    #  ⚙️ Pengaturan Lanjutan
    # ════════════════════════════════════════════════════════════════════
    with st.expander("⚙️ Pengaturan Lanjutan"):

        # ── Identitas Praktikan ────────────────────────────────────────
        st.subheader("🪪 Identitas Praktikan (Opsional)")
        st.caption(
            "Jika diisi, header singkat dan kecil akan dicetak di dalam halaman A4 "
            "(≤ 5 mm total, tanpa background)."
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

        # ── Orientasi & Kolom ─────────────────────────────────────────
        st.subheader("📐 Layout Halaman")
        orientation = st.radio(
            "Orientasi Halaman:",
            options=["Portrait", "Landscape"],
            horizontal=True,
            key="page_orientation",
        )

        # Reset slider default saat orientasi berubah
        _cols_default = 4 if orientation == "Landscape" else 3
        if st.session_state.get("_last_orient") != orientation:
            st.session_state["n_cols_slider"] = _cols_default
            st.session_state["_last_orient"]  = orientation

        n_cols = st.slider(
            "Jumlah Kolom:",
            min_value=1,
            max_value=10,           # ← dinaikkan ke 10
            key="n_cols_slider",
            help="Nilai default: 3 (Portrait) / 4 (Landscape). Maksimal 10 kolom.",
        )

        st.divider()

        # ── Kualitas JPEG ─────────────────────────────────────────────
        st.subheader("🖼️ Kualitas Gambar")
        jpeg_quality = st.slider(
            "Kualitas JPEG:",
            min_value=10,
            max_value=100,
            value=100,              # ← default 100
            step=5,
            key="jpeg_quality_slider",
            help="100 = kualitas penuh (lossless-ish). Turunkan untuk ukuran file lebih kecil.",
        )

    # ── Hitung dimensi halaman ────────────────────────────────────────
    if orientation == "Landscape":
        A4_W = A4_H_PORTRAIT
        A4_H = A4_W_PORTRAIT
    else:
        A4_W = A4_W_PORTRAIT
        A4_H = A4_H_PORTRAIT

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

    init_captions(image_data)

    # ── Estimasi halaman ──────────────────────────────────────────────
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