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
# ────────────────────────────────────────────────────────────────────────
if "clipboard_images" not in st.session_state:
    st.session_state.clipboard_images = []

if PASTE_SUPPORTED:
    paste_result = paste_image_button(
        label="📋 Tempel dari Clipboard (Ctrl+V / Cmd+V)",
        background_color="#f0f2f6",
        hover_background_color="#dce0e8",
    )
    # Setiap kali ada gambar baru dari clipboard, simpan ke session state
    if paste_result and paste_result.image_data is not None:
        buf = io.BytesIO()
        paste_result.image_data.save(buf, format="PNG")
        fname_clip = f"clipboard_{len(st.session_state.clipboard_images) + 1}.png"
        st.session_state.clipboard_images.append((buf.getvalue(), fname_clip))

    # Tampilkan info & tombol hapus jika ada gambar dari clipboard
    if st.session_state.clipboard_images:
        c1, c2 = st.columns([4, 1])
        with c1:
            st.caption(
                f"📋 {len(st.session_state.clipboard_images)} gambar dari clipboard ditambahkan."
            )
        with c2:
            if st.button("🗑️ Hapus Semua", use_container_width=True):
                st.session_state.clipboard_images = []
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
        # Foto tanpa Exif → datetime.min → muncul di awal, tidak crash
        all_file_items = sorted(all_file_items, key=lambda x: get_exif_date(x[0]))

    # ════════════════════════════════════════════════════════════════════
    #  ⚙️ Pengaturan Lanjutan (semua fitur opsional)
    # ════════════════════════════════════════════════════════════════════
    with st.expander("⚙️ Pengaturan Lanjutan"):

        # ── Fitur 2: Orientasi Halaman ────────────────────────────────
        st.subheader("📐 Layout Halaman")
        orientation = st.radio(
            "Orientasi Halaman:",
            options=["Portrait", "Landscape"],
            horizontal=True,
            key="page_orientation",
        )

        # ── Fitur 3: Jumlah Kolom Dinamis (reaktif terhadap orientasi) ─
        # Saat orientasi berubah → reset slider ke default yang sesuai
        _cols_default = 4 if orientation == "Landscape" else 3
        if st.session_state.get("_last_orient") != orientation:
            st.session_state["n_cols_slider"] = _cols_default
            st.session_state["_last_orient"]  = orientation

        n_cols = st.slider(
            "Jumlah Kolom:",
            min_value=1,
            max_value=4,
            key="n_cols_slider",
            help="Otomatis berubah ke 4 saat Landscape dipilih, 3 saat Portrait.",
        )

        st.divider()

        # ── Fitur 4: Kualitas JPEG / Kompresi ────────────────────────
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

    # ── Hitung dimensi halaman berdasarkan orientasi (Fitur 2) ────────
    if orientation == "Landscape":
        A4_W = A4_H_PORTRAIT   # 297mm → jadi lebar saat landscape
        A4_H = A4_W_PORTRAIT   # 210mm → jadi tinggi saat landscape
    else:
        A4_W = A4_W_PORTRAIT   # 210mm
        A4_H = A4_H_PORTRAIT   # 297mm

    # IMG_WIDTH_MM dihitung dinamis → selalu valid, tidak pernah negatif
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

        # Setup FPDF sesuai orientasi
        fpdf_orient = "L" if orientation == "Landscape" else "P"
        pdf = FPDF(orientation=fpdf_orient, unit="mm", format="A4")
        pdf.add_page()

        max_y = A4_H - BOTTOM_MARGIN_MM

        # Cetak header identitas di halaman pertama (jika ada isian)
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

            # Simpan gambar ke file sementara lalu sisipkan ke PDF
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                temp_path = tmp.name
                img.save(temp_path, "JPEG", quality=jpeg_quality)   # Fitur 4

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
                        # Gunakan cap_key yang SAMA dengan yang dibaca saat generate PDF
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