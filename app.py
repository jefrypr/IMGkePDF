import streamlit as st
from PIL import Image
from fpdf import FPDF
import tempfile
import os
import hashlib

# ── Konfigurasi Halaman ────────────────────────────────────────────────
st.set_page_config(page_title="Foto Praktikum → PDF Print", page_icon="📸", layout="centered")

# ── Konstanta ─────────────────────────────────────────────────────────
DPI              = 300
A4_WIDTH_MM      = 210
A4_HEIGHT_MM     = 297
COLS             = 3
GAP_MM           = 1
PAGE_MARGIN_MM   = 2        # margin kiri & kanan halaman

# FIX ROOT CAUSE: hitung IMG_WIDTH dari lebar A4 agar tidak negatif
# (sebelumnya: IMG_WIDTH=70 → total=212mm > A4 210mm → LEFT_MARGIN=-1mm)
IMG_WIDTH_MM     = (A4_WIDTH_MM - 2 * PAGE_MARGIN_MM - (COLS - 1) * GAP_MM) / COLS
# = (210 - 4 - 2) / 3 = 68.0mm → total = 3×68 + 2×1 = 206mm → margin = 2mm ✓

LEFT_MARGIN_MM   = PAGE_MARGIN_MM
TOP_MARGIN_MM    = 0
BOTTOM_MARGIN_MM = 0
BORDER_MM        = 0.5

CAPTION_HEIGHT_MM = 4.0
CAPTION_FONT_PT   = 5


# ── Helper key caption ─────────────────────────────────────────────────
def cap_key(i: int, fname: str) -> str:
    """
    Widget key AMAN (tanpa karakter spasi/simbol dari nama file).
    Nama file langsung di-hash → pasti valid sebagai Streamlit widget key.
    """
    h = hashlib.md5(fname.encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"wfc_{i}_{h}"


def default_caption(fname: str) -> str:
    return os.path.splitext(fname)[0]


def init_captions(image_data):
    """Inisialisasi semua widget key SEBELUM rendering apapun."""
    for i, (_, _, fname) in enumerate(image_data):
        k = cap_key(i, fname)
        if k not in st.session_state:
            st.session_state[k] = default_caption(fname)


def get_caption(i: int, fname: str) -> str:
    """Baca caption langsung dari widget key (no intermediate dict)."""
    val = st.session_state.get(cap_key(i, fname), "").strip()
    return val if val else default_caption(fname)


# ── Fungsi Helper ─────────────────────────────────────────────────────
def mm_to_px(mm):
    return int(mm * DPI / 25.4)


@st.cache_data
def process_image_data(file_bytes):
    try:
        import io
        img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        if img.height > img.width:
            img = img.rotate(-90, expand=True)
        target_w = mm_to_px(IMG_WIDTH_MM)
        ratio    = target_w / img.width
        target_h = int(img.height * ratio)
        img      = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        h_mm     = IMG_WIDTH_MM * img.height / img.width
        return img, h_mm
    except Exception:
        return None, None


def simulate_waterfall(image_list, extra_h=0):
    """
    Simulasi algoritma waterfall identik dengan PDF generation.
    Return: col_assign[i] = kolom (0/1/2) tempat foto ke-i.
    """
    if not image_list:
        return []
    max_y       = A4_HEIGHT_MM - BOTTOM_MARGIN_MM
    col_heights = [TOP_MARGIN_MM] * COLS
    col_assign  = []
    for _, h_mm, _ in image_list:
        slot_h  = h_mm + extra_h
        min_col = col_heights.index(min(col_heights))
        y       = col_heights[min_col]
        if y + slot_h > max_y:
            col_heights = [TOP_MARGIN_MM] * COLS
            min_col     = 0
            y           = col_heights[min_col]
        col_assign.append(min_col)
        col_heights[min_col] += slot_h + GAP_MM
    return col_assign


def estimate_pages(image_list, extra_h=0):
    if not image_list:
        return 0
    max_y       = A4_HEIGHT_MM - BOTTOM_MARGIN_MM
    col_heights = [TOP_MARGIN_MM] * COLS
    pages       = 1
    for _, h_mm, _ in image_list:
        slot_h  = h_mm + extra_h
        min_col = col_heights.index(min(col_heights))
        y       = col_heights[min_col]
        if y + slot_h > max_y:
            pages      += 1
            col_heights = [TOP_MARGIN_MM] * COLS
            min_col     = 0
        col_heights[min_col] += slot_h + GAP_MM
    return pages


def fit_caption(pdf, text, max_width_mm):
    """Potong teks agar muat dalam max_width_mm, tambah '...' jika dipotong."""
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


# ── UI ────────────────────────────────────────────────────────────────
st.title("📸 Foto → PDF Waterfall")
st.markdown(
    "Upload foto bertahap, atur urutan, dan jadikan satu file PDF "
    "dengan *layout waterfall* yang rapi."
)

uploaded_files = st.file_uploader(
    "➕ Tambahkan Foto (JPG, JPEG, PNG)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

if uploaded_files:
    col1, col2 = st.columns(2)
    with col1:
        sort_mode = st.selectbox(
            "Urutan Foto:",
            options=["Sesuai Urutan Upload", "Nama File A → Z", "Nama File Z → A"],
        )
    with col2:
        pdf_name = st.text_input("Nama File PDF:", value="output_foto", placeholder="output_foto")

    if sort_mode == "Nama File A → Z":
        uploaded_files = sorted(uploaded_files, key=lambda f: f.name.lower())
    elif sort_mode == "Nama File Z → A":
        uploaded_files = sorted(uploaded_files, key=lambda f: f.name.lower(), reverse=True)

    image_data = []
    for f in uploaded_files:
        img, h_mm = process_image_data(f.getvalue())
        if img:
            image_data.append((img, h_mm, f.name))

    n_photos = len(image_data)

    enable_captions = st.checkbox(
        "🏷️ Tambahkan keterangan pada setiap foto",
        value=False,
        help="Aktifkan untuk menambahkan teks keterangan di bawah tiap foto dalam PDF.",
    )

    extra_h = CAPTION_HEIGHT_MM if enable_captions else 0

    # ── Inisialisasi caption state SEBELUM rendering apapun ───────────
    # (termasuk sebelum expander dan sebelum tombol Generate)
    # Membaca caption langsung dari widget key → tidak butuh dict perantara
    init_captions(image_data)

    est_pages = estimate_pages(image_data, extra_h=extra_h)
    st.info(f"📷 **{n_photos}** foto siap diproses | 📄 Estimasi **{est_pages}** halaman PDF")

    # ── Generate PDF ──────────────────────────────────────────────────
    if st.button("✅ Generate PDF", type="primary", use_container_width=True):
        progress_bar = st.progress(0, text="Menyiapkan PDF...")

        pdf = FPDF(unit="mm", format="A4")
        pdf.add_page()

        col_x = [LEFT_MARGIN_MM + c * (IMG_WIDTH_MM + GAP_MM) for c in range(COLS)]
        max_y       = A4_HEIGHT_MM - BOTTOM_MARGIN_MM
        col_heights = [TOP_MARGIN_MM] * COLS

        for i, (img, h_mm, fname) in enumerate(image_data):
            slot_h  = h_mm + extra_h
            min_col = col_heights.index(min(col_heights))
            x       = col_x[min_col]
            y       = col_heights[min_col]

            if y + slot_h > max_y:
                pdf.add_page()
                col_heights = [TOP_MARGIN_MM] * COLS
                min_col     = 0
                x           = col_x[min_col]
                y           = col_heights[min_col]

            # Simpan gambar sementara
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                temp_path = tmp.name
                img.save(temp_path, "JPEG", quality=95)

            pdf.image(temp_path, x=x, y=y, w=IMG_WIDTH_MM, h=h_mm)
            os.remove(temp_path)

            # Border
            pdf.set_draw_color(0, 0, 0)
            pdf.set_line_width(BORDER_MM)
            pdf.rect(x, y, IMG_WIDTH_MM, h_mm)

            # Caption — baca langsung dari widget key (pasti valid)
            if enable_captions:
                raw = get_caption(i, fname)
                if raw:
                    pdf.set_font("Helvetica", size=CAPTION_FONT_PT)
                    pdf.set_text_color(0, 0, 0)
                    final = fit_caption(pdf, raw, IMG_WIDTH_MM - 1)
                    if final:
                        cap_y = y + h_mm + 0.8
                        # Pastikan x selalu >= 0 (safeguard tambahan)
                        safe_x = max(0.0, x)
                        pdf.set_xy(safe_x, cap_y)
                        pdf.cell(IMG_WIDTH_MM, CAPTION_HEIGHT_MM - 0.8, final, align="C")

            col_heights[min_col] = y + slot_h + GAP_MM
            progress_bar.progress((i + 1) / n_photos, text=f"Memproses {i+1}/{n_photos}...")

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

        # Urutan preview = urutan PDF (waterfall simulation)
        col_assign  = simulate_waterfall(image_data, extra_h=extra_h)
        cols_photos = [[] for _ in range(COLS)]
        for idx, c in enumerate(col_assign):
            cols_photos[c].append(idx)

        preview_cols = st.columns(COLS)
        for col_idx in range(COLS):
            with preview_cols[col_idx]:
                for photo_idx in cols_photos[col_idx]:
                    img, _, fname = image_data[photo_idx]
                    st.image(img, use_container_width=True)
                    if enable_captions:
                        # Gunakan cap_key yang sama persis dengan yang dibaca PDF
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
