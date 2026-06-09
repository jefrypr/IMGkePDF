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
TOP_MARGIN_MM     = 1
BOTTOM_MARGIN_MM  = 1
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


def estimate_pages(image_list, n_cols, a4_h_mm, extra_h=0):
    if not image_list:
        return 0
    max_y       = a4_h_mm - BOTTOM_MARGIN_MM
    col_heights = [TOP_MARGIN_MM] * n_cols
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
#  UI UTAMA
# ═══════════════════════════════════════════════════════════════════════

st.title("📸 Foto → PDF Waterfall")
st.markdown(
    "Upload foto, atur urutan, dan jadikan satu file PDF "
    "dengan *layout waterfall* yang rapi."
)

# ── File Uploader ─────────────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "➕ Tambahkan Foto (JPG, JPEG, PNG)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

# ── Fitur 6: Clipboard Paste ──────────────────────────────────────────
if "clipboard_images" not in st.session_state:
    st.session_state.clipboard_images = []

if "clipboard_hashes" not in st.session_state:
    st.session_state.clipboard_hashes = set()

if PASTE_SUPPORTED:
    paste_result = paste_image_button(
        label="📋 Paste from Clipboard",
        background_color="#1F2532",
        hover_background_color="#0e1117",
    )
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
            st.caption(f"📋 {len(st.session_state.clipboard_images)} gambar dari clipboard ditambahkan.")
        with c2:
            if st.button("🗑️ Hapus Semua", use_container_width=True):
                st.session_state.clipboard_images = []
                st.session_state.clipboard_hashes = set()
                st.rerun()
else:
    st.caption("ℹ️ Fitur paste clipboard tidak aktif. Pastikan `streamlit-paste-button` sudah terinstall.")

# ── Gabungkan semua sumber ────────────────────────────────────────────
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
        pdf_name = st.text_input("Nama File PDF:", value="output_foto", placeholder="output_foto")

    if sort_mode == "Nama File A → Z":
        all_file_items = sorted(all_file_items, key=lambda x: x[1].lower())
    elif sort_mode == "Nama File Z → A":
        all_file_items = sorted(all_file_items, key=lambda x: x[1].lower(), reverse=True)
    elif sort_mode == "Waktu Pengambilan (Exif)":
        all_file_items = sorted(all_file_items, key=lambda x: get_exif_date(x[0]))

    # ── Pengaturan Lanjutan ───────────────────────────────────────────
    with st.expander("⚙️ Pengaturan Lanjutan"):

        st.subheader("📐 Layout Halaman")
        orientation = st.radio(
            "Orientasi Halaman:",
            options=["Portrait", "Landscape"],
            horizontal=True,
            key="page_orientation",
        )

        _cols_default = 4 if orientation == "Landscape" else 3
        if st.session_state.get("_last_orient") != orientation:
            st.session_state["n_cols_slider"] = _cols_default
            st.session_state["_last_orient"]  = orientation

        n_cols = st.slider(
            "Jumlah Kolom:",
            min_value=1,
            max_value=10,
            key="n_cols_slider",
            help="Otomatis berubah ke 4 saat Landscape, 3 saat Portrait. Maks 10 kolom.",
        )

        st.divider()

        st.subheader("🖼️ Kualitas Gambar")
        jpeg_quality = st.slider(
            "Kualitas JPEG:",
            min_value=10,
            max_value=100,
            value=100,
            step=5,
            key="jpeg_quality_slider",
            help="Lebih tinggi = gambar lebih tajam tapi ukuran file lebih besar.",
        )

    # ── Dimensi halaman ───────────────────────────────────────────────
    if orientation == "Landscape":
        A4_W = A4_H_PORTRAIT
        A4_H = A4_W_PORTRAIT
    else:
        A4_W = A4_W_PORTRAIT
        A4_H = A4_H_PORTRAIT

    IMG_WIDTH_MM   = compute_img_width(A4_W, n_cols)
    LEFT_MARGIN_MM = PAGE_MARGIN_MM
    col_x          = [LEFT_MARGIN_MM + c * (IMG_WIDTH_MM + GAP_MM) for c in range(n_cols)]

    # ── Proses gambar ─────────────────────────────────────────────────
    image_data = []
    for file_bytes, fname in all_file_items:
        img, h_mm = process_image_data(file_bytes, IMG_WIDTH_MM)
        if img:
            image_data.append((img, h_mm, fname))

    n_photos = len(image_data)

    enable_captions = st.checkbox(
        "🏷️ Tambahkan keterangan pada setiap foto",
        value=False,
        help="Aktifkan untuk menambahkan teks keterangan di bawah tiap foto dalam PDF.",
    )
    extra_h = CAPTION_HEIGHT_MM if enable_captions else 0

    init_captions(image_data)

    est_pages = estimate_pages(image_data, n_cols, A4_H, extra_h=extra_h)

    st.info(
        f"📷 **{n_photos}** foto siap diproses  |  "
        f"📄 Estimasi **{est_pages}** halaman PDF  |  "
        f"📐 {orientation} · {n_cols} kolom · JPEG {jpeg_quality}"
    )

    # ── Generate PDF ──────────────────────────────────────────────────
    if st.button("✅ Generate PDF", type="primary", use_container_width=True):
        progress_bar = st.progress(0, text="Menyiapkan PDF...")

        fpdf_orient = "L" if orientation == "Landscape" else "P"
        pdf = FPDF(orientation=fpdf_orient, unit="mm", format="A4")
        pdf.add_page()

        max_y       = A4_H - BOTTOM_MARGIN_MM
        col_heights = [TOP_MARGIN_MM] * n_cols

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

        safe_name    = "".join(c for c in pdf_name if c.isalnum() or c in (" ", "_", "-")).strip()
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

    # ── Preview Galeri ────────────────────────────────────────────────
    with st.expander("👀 Lihat Preview Galeri Foto"):
        if enable_captions:
            hdr_col, btn_col = st.columns([4, 1])
            with hdr_col:
                st.caption("✏️ Isi keterangan di bawah tiap foto. Kosongkan jika tidak perlu.")
            with btn_col:
                if st.button("🔄 Reset", help="Kembalikan semua keterangan ke nama file", use_container_width=True):
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
    st.info("📂 Silakan upload foto untuk memulai. Mendukung format **JPG**, **JPEG**, dan **PNG**.")
