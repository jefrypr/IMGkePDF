import streamlit as st
from PIL import Image
from fpdf import FPDF
import tempfile
import os
import hashlib

# ── Konfigurasi Halaman Streamlit ─────────────────────────────────────
st.set_page_config(page_title="Foto ke PDF Waterfall", page_icon="📸", layout="centered")

# ── Konstanta ─────────────────────────────────────────────────────────
DPI               = 300
A4_WIDTH_MM       = 210
A4_HEIGHT_MM      = 297
IMG_WIDTH_MM      = 70
COLS              = 3
GAP_MM            = 1
TOP_MARGIN_MM     = 0
BOTTOM_MARGIN_MM  = 0
BORDER_MM         = 0.5
CAPTION_HEIGHT_MM = 4.0
CAPTION_FONT_PT   = 5

_total_cols_width = COLS * IMG_WIDTH_MM + (COLS - 1) * GAP_MM
LEFT_MARGIN_MM    = (A4_WIDTH_MM - _total_cols_width) / 2


# ── Widget key helper ─────────────────────────────────────────────────
def make_widget_key(i: int, fname: str) -> str:
    """
    Key aman untuk st.text_input — nama file bisa berisi spasi/karakter
    khusus yang merusak Streamlit widget tracking, jadi kita hash fname-nya.
    """
    h = hashlib.md5(fname.encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"wfc_{i}_{h}"


def init_all_caption_keys(image_data):
    """
    Inisialisasi SEMUA widget-key caption ke default (nama file tanpa ekstensi)
    SEBELUM widget apapun dirender. Dipanggil setiap rerun.

    Satu sumber kebenaran: session_state[widget_key].
    Tidak ada dict WF_CAPS terpisah → tidak ada masalah sinkronisasi.
    """
    for i, (_, _, fname) in enumerate(image_data):
        wk = make_widget_key(i, fname)
        if wk not in st.session_state:
            st.session_state[wk] = os.path.splitext(fname)[0]


def get_caption(i: int, fname: str) -> str:
    """
    Ambil caption foto ke-i langsung dari session_state (satu sumber).
    Fallback ke nama file jika kosong.
    """
    wk   = make_widget_key(i, fname)
    text = st.session_state.get(wk, "").strip()
    if not text:
        text = os.path.splitext(fname)[0].strip()
    return text


# ── Fungsi Helper ─────────────────────────────────────────────────────
def mm_to_px(mm):
    return int(mm * DPI / 25.4)


@st.cache_data
def process_image_data(file_bytes):
    """Rotasi portrait → landscape, resize proporsional."""
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
    Simulasi algoritma waterfall persis seperti PDF generation.
    Kembalikan col_assign[i] = kolom (0/1/2) untuk foto ke-i.
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


# ── UI Aplikasi ───────────────────────────────────────────────────────
st.title("📸 Foto → PDF Waterfall")
st.markdown(
    "Upload foto bertahap, atur urutan, dan jadikan satu file PDF "
    "dengan *layout waterfall* yang rapi."
)

# ── Upload File ───────────────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "➕ Tambahkan Foto (JPG, JPEG, PNG)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

if uploaded_files:
    # ── Opsi Pengaturan ───────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        sort_mode = st.selectbox(
            "Urutan Foto:",
            options=["Sesuai Urutan Upload", "Nama File A → Z", "Nama File Z → A"],
        )
    with col2:
        pdf_name = st.text_input(
            "Nama File PDF:", value="output_foto", placeholder="output_foto"
        )

    if sort_mode == "Nama File A → Z":
        uploaded_files = sorted(uploaded_files, key=lambda f: f.name.lower())
    elif sort_mode == "Nama File Z → A":
        uploaded_files = sorted(uploaded_files, key=lambda f: f.name.lower(), reverse=True)

    # Proses foto ke memori
    image_data = []
    for f in uploaded_files:
        img, h_mm = process_image_data(f.getvalue())
        if img:
            image_data.append((img, h_mm, f.name))

    n_photos = len(image_data)

    # ── Toggle Fitur Keterangan ───────────────────────────────────────
    enable_captions = st.checkbox(
        "🏷️ Tambahkan keterangan pada setiap foto",
        value=False,
        help=(
            "Aktifkan untuk menambahkan teks keterangan di bawah tiap foto dalam PDF. "
            "Isi keterangan bisa diatur di bagian Preview Galeri Foto."
        ),
    )

    extra_h = CAPTION_HEIGHT_MM if enable_captions else 0

    # ── INISIALISASI SEMUA WIDGET KEY SEBELUM APAPUN ─────────────────
    # Wajib dipanggil sebelum tombol Generate maupun expander preview.
    # Ini menjamin session_state[wk] selalu ada saat PDF dibuat,
    # terlepas apakah expander pernah dibuka atau tidak.
    init_all_caption_keys(image_data)

    est_pages = estimate_pages(image_data, extra_h=extra_h)
    st.info(
        f"📷 **{n_photos}** foto siap diproses | "
        f"📄 Estimasi **{est_pages}** halaman PDF"
    )

    # ── Tombol Eksekusi ───────────────────────────────────────────────
    if st.button("✅ Generate PDF", type="primary", use_container_width=True):
        progress_bar = st.progress(0, text="Menyiapkan PDF...")

        pdf = FPDF(unit="mm", format="A4")
        pdf.add_page()
        col_x       = [LEFT_MARGIN_MM + c * (IMG_WIDTH_MM + GAP_MM) for c in range(COLS)]
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

            # Simpan & masukkan gambar ke PDF
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                temp_path = tmp.name
                img.save(temp_path, "JPEG", quality=95)

            pdf.image(temp_path, x=x, y=y, w=IMG_WIDTH_MM, h=h_mm)
            os.remove(temp_path)

            # Border
            pdf.set_draw_color(0, 0, 0)
            pdf.set_line_width(BORDER_MM)
            pdf.rect(x, y, IMG_WIDTH_MM, h_mm)

            # Caption — dibaca langsung dari session_state (satu sumber)
            if enable_captions:
                raw_text = get_caption(i, fname)
                if raw_text:
                    pdf.set_font("Helvetica", size=CAPTION_FONT_PT)
                    pdf.set_text_color(0, 0, 0)
                    final_text = fit_caption(pdf, raw_text, IMG_WIDTH_MM - 2)
                    if final_text:
                        pdf.set_xy(x, y + h_mm + 0.8)
                        pdf.cell(
                            IMG_WIDTH_MM, CAPTION_HEIGHT_MM - 0.8,
                            final_text, align="C"
                        )

            col_heights[min_col] = y + slot_h + GAP_MM
            progress_bar.progress(
                (i + 1) / n_photos,
                text=f"Memproses {i + 1} dari {n_photos} foto...",
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

    # ── Preview Galeri Foto ───────────────────────────────────────────
    with st.expander("👀 Lihat Preview Galeri Foto"):

        if enable_captions:
            hdr_col, btn_col = st.columns([4, 1])
            with hdr_col:
                st.caption(
                    "✏️ Isi keterangan di bawah tiap foto. "
                    "Biarkan kosong untuk tidak menampilkan keterangan."
                )
            with btn_col:
                if st.button(
                    "🔄 Reset",
                    help="Kembalikan semua keterangan ke nama file aslinya",
                    use_container_width=True,
                ):
                    for i, (_, _, fname) in enumerate(image_data):
                        st.session_state[make_widget_key(i, fname)] = (
                            os.path.splitext(fname)[0]
                        )
                    st.rerun()

        # Preview urutan waterfall = urutan PDF
        col_assign  = simulate_waterfall(image_data, extra_h=extra_h)
        cols_photos = [[] for _ in range(COLS)]
        for photo_idx, col_idx in enumerate(col_assign):
            cols_photos[col_idx].append(photo_idx)

        preview_cols = st.columns(COLS)
        for col_idx in range(COLS):
            with preview_cols[col_idx]:
                for photo_idx in cols_photos[col_idx]:
                    img, _, fname = image_data[photo_idx]
                    st.image(img, use_container_width=True)

                    if enable_captions:
                        # Render text_input dengan widget key yang aman.
                        # session_state[wk] sudah di-init oleh
                        # init_all_caption_keys() di atas → nilai selalu ada.
                        st.text_input(
                            label="keterangan",
                            key=make_widget_key(photo_idx, fname),
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
