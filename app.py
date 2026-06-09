import streamlit as st
from PIL import Image
from fpdf import FPDF
import tempfile
import os
import hashlib
import io
from datetime import datetime

try:
    from streamlit_paste_button import paste_image_button
    PASTE_SUPPORTED = True
except ImportError:
    PASTE_SUPPORTED = False

# ── Page config ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FotoPDF — Lab Print Studio",
    page_icon="🗂️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ────────────────────────────────────────────────────────────
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
MIN_COL_WIDTH_MM  = 20.0


# ═══════════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS  (logic unchanged)
# ═══════════════════════════════════════════════════════════════════════════

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

def mm_to_px(mm: float) -> int:
    return int(mm * DPI / 25.4)

def compute_img_width(a4_w_mm: float, n_cols: int) -> float:
    n_cols = max(1, n_cols)
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

def estimate_header_height(mata, judul, tanggal):
    if not any([mata, judul, tanggal]):
        return 0.0
    y = 1.0
    if mata:    y += 4.0 + 0.5
    if judul:   y += 3.5 + 0.5
    if tanggal: y += 3.0 + 0.5
    y += 1.5
    return y

def draw_header(pdf, mata, judul, tanggal, a4_w_mm):
    if not any([mata, judul, tanggal]):
        return TOP_MARGIN_MM
    y        = 1.0
    line_gap = 0.5
    usable_w = a4_w_mm - 2 * PAGE_MARGIN_MM
    if mata:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(PAGE_MARGIN_MM, y)
        pdf.cell(usable_w, 4.0, mata, align="C")
        y += 4.0 + line_gap
    if judul:
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(50, 50, 50)
        pdf.set_xy(PAGE_MARGIN_MM, y)
        pdf.cell(usable_w, 3.5, judul, align="C")
        y += 3.5 + line_gap
    if tanggal:
        pdf.set_font("Helvetica", "I", 6)
        pdf.set_text_color(90, 90, 90)
        pdf.set_xy(PAGE_MARGIN_MM, y)
        pdf.cell(usable_w, 3.0, f"Tanggal: {tanggal}", align="C")
        y += 3.0 + line_gap
    pdf.set_draw_color(190, 190, 190)
    pdf.set_line_width(0.15)
    pdf.line(PAGE_MARGIN_MM, y, a4_w_mm - PAGE_MARGIN_MM, y)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(BORDER_MM)
    pdf.set_text_color(0, 0, 0)
    y += 1.5
    return y


# ═══════════════════════════════════════════════════════════════════════════
#  GLOBAL STYLES
# ═══════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,400;0,500;0,600;0,700;0,800;1,400&display=swap');

/* ── Reset & base ─────────────────────────────────────────────── */
html, body, .stApp, [class*="css"], [class*="st-"] {
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
}
.stApp {
    background-color: #F1F5F9 !important;
}

/* ── Sidebar — dark control panel ──────────────────────────────── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1E293B 0%, #0F172A 100%) !important;
    border-right: 1px solid #1E293B !important;
}
[data-testid="stSidebar"] > div {
    padding-top: 0 !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] div,
[data-testid="stSidebar"] label {
    color: #CBD5E1 !important;
}
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea,
[data-testid="stSidebar"] .stSelectbox > div > div {
    background-color: #1E293B !important;
    border: 1px solid #334155 !important;
    color: #F1F5F9 !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] input:focus,
[data-testid="stSidebar"] textarea:focus {
    border-color: #4F46E5 !important;
    box-shadow: 0 0 0 2px rgba(79,70,229,0.25) !important;
    outline: none !important;
}
[data-testid="stSidebar"] .stSlider [data-testid="stThumb"] {
    background: #4F46E5 !important;
}
[data-testid="stSidebar"] .stSlider [data-baseweb="slider"] div[role="slider"] {
    background: #4F46E5 !important;
}
[data-testid="stSidebar"] hr {
    border-color: #1E293B !important;
    margin: 4px 0 !important;
}
[data-testid="stSidebar"] .stRadio > div {
    gap: 8px !important;
    flex-direction: row !important;
}

/* ── Sidebar section labels ─────────────────────────────────────── */
.sb-section {
    font-size: 0.65rem;
    font-weight: 700;
    color: #4F46E5 !important;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin: 22px 0 10px 0;
    display: flex;
    align-items: center;
    gap: 7px;
}
.sb-section::after {
    content: '';
    flex: 1;
    height: 1px;
    background: #1E293B;
    margin-left: 4px;
}

/* ── Sidebar brand ──────────────────────────────────────────────── */
.sb-brand {
    background: linear-gradient(135deg, #312E81 0%, #1E1B4B 100%);
    padding: 20px 20px 18px 20px;
    margin-bottom: 6px;
    border-bottom: 1px solid #312E81;
}
.sb-brand-logo {
    width: 40px; height: 40px;
    background: linear-gradient(135deg, #6366F1, #8B5CF6);
    border-radius: 12px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 1.2rem;
    margin-bottom: 12px;
    box-shadow: 0 4px 12px rgba(99,102,241,0.4);
}
.sb-brand-title {
    font-size: 1.05rem;
    font-weight: 800;
    color: #F8FAFC !important;
    letter-spacing: -0.02em;
    line-height: 1.1;
}
.sb-brand-sub {
    font-size: 0.72rem;
    color: #64748B !important;
    margin-top: 2px;
}

/* ── Sidebar footer ─────────────────────────────────────────────── */
.sb-footer {
    font-size: 0.65rem;
    color: #475569 !important;
    text-align: center;
    padding: 16px 0;
    line-height: 1.7;
    border-top: 1px solid #1E293B;
    margin-top: 12px;
}

/* ── Main area ──────────────────────────────────────────────────── */
.main-header {
    padding: 28px 0 6px 0;
    border-bottom: 1px solid #E2E8F0;
    margin-bottom: 28px;
}
.main-title {
    font-size: 1.5rem;
    font-weight: 800;
    color: #0F172A;
    letter-spacing: -0.03em;
    line-height: 1.2;
}
.main-sub {
    font-size: 0.84rem;
    color: #64748B;
    margin-top: 5px;
}

/* ── Step section headers ──────────────────────────────────────── */
.step-wrap {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 14px;
}
.step-num {
    width: 26px; height: 26px;
    background: linear-gradient(135deg, #4F46E5, #7C3AED);
    color: #fff !important;
    border-radius: 8px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.7rem;
    font-weight: 800;
    letter-spacing: 0.05em;
    flex-shrink: 0;
    box-shadow: 0 2px 8px rgba(79,70,229,0.35);
}
.step-title {
    font-size: 0.92rem;
    font-weight: 700;
    color: #0F172A;
    letter-spacing: -0.01em;
}
.step-desc {
    font-size: 0.75rem;
    color: #94A3B8;
    margin-left: 38px;
    margin-top: -8px;
    margin-bottom: 14px;
}

/* ── Card ───────────────────────────────────────────────────────── */
.card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 22px;
    box-shadow: 0 1px 3px rgba(15,23,42,0.05);
}

/* ── Upload zone ────────────────────────────────────────────────── */
[data-testid="stFileUploader"] section {
    border: 2px dashed #C7D2FE !important;
    border-radius: 14px !important;
    background: #FAFBFF !important;
    padding: 36px 24px !important;
    transition: border-color 0.2s, background 0.2s !important;
    cursor: pointer !important;
}
[data-testid="stFileUploader"] section:hover {
    border-color: #6366F1 !important;
    background: #EEF2FF !important;
}
[data-testid="stFileUploader"] section p {
    color: #6B7280 !important;
    font-size: 0.88rem !important;
}
[data-testid="stFileUploader"] section svg {
    color: #A5B4FC !important;
}
[data-testid="stFileUploaderDropzoneInstructions"] small {
    color: #94A3B8 !important;
    font-size: 0.78rem !important;
}

/* ── Sort control ────────────────────────────────────────────────── */
.stSelectbox > div > div {
    background: #F8FAFC !important;
    border-color: #E2E8F0 !important;
    border-radius: 10px !important;
    font-size: 0.88rem !important;
}
.stSelectbox label {
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    color: #64748B !important;
    letter-spacing: 0.05em !important;
    text-transform: uppercase !important;
}

/* ── Metrics row ─────────────────────────────────────────────────── */
.metric-chip {
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 14px 18px;
    text-align: center;
    flex: 1;
    min-width: 0;
}
.metric-val {
    font-size: 1.6rem;
    font-weight: 800;
    color: #0F172A;
    letter-spacing: -0.03em;
    line-height: 1.1;
}
.metric-label {
    font-size: 0.68rem;
    color: #94A3B8;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-top: 3px;
}
.metric-row {
    display: flex;
    gap: 10px;
    margin-bottom: 18px;
}

/* ── Generate button ─────────────────────────────────────────────── */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%) !important;
    border: none !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: 0.95rem !important;
    letter-spacing: 0.01em !important;
    padding: 14px 28px !important;
    color: #FFFFFF !important;
    box-shadow: 0 4px 16px rgba(79,70,229,0.35) !important;
    transition: all 0.18s ease !important;
}
.stButton > button[kind="primary"]:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 24px rgba(79,70,229,0.45) !important;
}
.stButton > button[kind="primary"]:active {
    transform: translateY(0px) !important;
}

/* Secondary buttons */
.stButton > button[kind="secondary"] {
    border-color: #E2E8F0 !important;
    color: #475569 !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.84rem !important;
    transition: all 0.15s ease !important;
}
.stButton > button[kind="secondary"]:hover {
    background: #F8FAFC !important;
    border-color: #CBD5E1 !important;
}

/* ── Download button ─────────────────────────────────────────────── */
.stDownloadButton > button {
    background: linear-gradient(135deg, #059669 0%, #047857 100%) !important;
    border: none !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: 0.95rem !important;
    color: #FFFFFF !important;
    box-shadow: 0 4px 16px rgba(5,150,105,0.35) !important;
    transition: all 0.18s ease !important;
}
.stDownloadButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 24px rgba(5,150,105,0.45) !important;
}

/* ── Checkbox & caption toggle ──────────────────────────────────── */
.stCheckbox > label {
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    color: #374151 !important;
    gap: 10px !important;
}
.stCheckbox span[data-testid="stMarkdownContainer"] p {
    font-size: 0.88rem !important;
}

/* ── Clipboard badge ─────────────────────────────────────────────── */
.clip-badge {
    display: flex;
    align-items: center;
    gap: 10px;
    background: #EFF6FF;
    border: 1px solid #BFDBFE;
    border-radius: 10px;
    padding: 10px 14px;
    margin: 10px 0 6px 0;
}
.clip-badge-icon { font-size: 1rem; }
.clip-badge-text {
    color: #1D4ED8;
    font-size: 0.82rem;
    font-weight: 600;
    flex: 1;
}

/* ── Or divider ──────────────────────────────────────────────────── */
.or-divider {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 14px 0;
}
.or-line { flex: 1; height: 1px; background: #E2E8F0; }
.or-text {
    color: #94A3B8;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}

/* ── Alert boxes ─────────────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    font-size: 0.84rem !important;
}

/* ── Expander ────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid #E2E8F0 !important;
    border-radius: 14px !important;
    background: #FFFFFF !important;
    overflow: hidden !important;
}
[data-testid="stExpander"] summary {
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    color: #374151 !important;
    padding: 14px 18px !important;
}
[data-testid="stExpander"] summary:hover {
    background: #F8FAFC !important;
}

/* ── Progress bar ────────────────────────────────────────────────── */
.stProgress > div > div > div > div {
    background: linear-gradient(90deg, #4F46E5, #7C3AED) !important;
    border-radius: 4px !important;
}
.stProgress > div > div {
    background: #E2E8F0 !important;
    border-radius: 4px !important;
}

/* ── Success box ─────────────────────────────────────────────────── */
.success-banner {
    display: flex;
    align-items: center;
    gap: 14px;
    background: linear-gradient(135deg, #ECFDF5, #D1FAE5);
    border: 1px solid #A7F3D0;
    border-radius: 14px;
    padding: 18px 20px;
    margin-bottom: 14px;
}
.success-icon {
    font-size: 1.6rem;
    flex-shrink: 0;
}
.success-text-title {
    font-size: 0.95rem;
    font-weight: 700;
    color: #065F46;
}
.success-text-sub {
    font-size: 0.78rem;
    color: #059669;
    margin-top: 2px;
}

/* ── Empty state ─────────────────────────────────────────────────── */
.empty-state {
    text-align: center;
    padding: 56px 24px;
    background: #FFFFFF;
    border: 2px dashed #E2E8F0;
    border-radius: 20px;
}
.empty-state-icon { font-size: 3.2rem; margin-bottom: 12px; }
.empty-state-title {
    font-size: 1.05rem;
    font-weight: 700;
    color: #374151;
    margin-bottom: 6px;
}
.empty-state-sub {
    font-size: 0.82rem;
    color: #9CA3AF;
    line-height: 1.6;
}

/* ── Warning strip ───────────────────────────────────────────────── */
.warn-strip {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    background: #FFFBEB;
    border: 1px solid #FDE68A;
    border-left: 4px solid #F59E0B;
    border-radius: 10px;
    padding: 12px 16px;
    font-size: 0.82rem;
    color: #92400E;
    margin-bottom: 14px;
}

/* ── Hide Streamlit default header ──────────────────────────────── */
[data-testid="stDecoration"] { display: none !important; }
header[data-testid="stHeader"] { display: none !important; }
#MainMenu { visibility: hidden !important; }
footer { visibility: hidden !important; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
#  SIDEBAR — CONTROL PANEL
# ═══════════════════════════════════════════════════════════════════════════

with st.sidebar:
    # Brand header
    st.markdown("""
    <div class="sb-brand">
      <div class="sb-brand-logo">🗂️</div>
      <div class="sb-brand-title">FotoPDF</div>
      <div class="sb-brand-sub">Lab Print Studio</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Identitas Praktikan ───────────────────────────────────────────
    st.markdown('<div class="sb-section">📋 Identitas Praktikan</div>', unsafe_allow_html=True)
    st.caption("Opsional — dicetak sebagai header di halaman pertama PDF.")

    mata_praktikum = st.text_input(
        "Mata Praktikum",
        placeholder="mis. Sistem Kendali Digital",
        key="id_mata",
    )
    judul_modul = st.text_input(
        "Judul Modul",
        placeholder="mis. Modul 1: Kontrol PID",
        key="id_judul",
    )
    tanggal_praktikum = st.text_input(
        "Tanggal Praktikum",
        placeholder="mis. 9 Juni 2026",
        key="id_tanggal",
    )

    # ── Layout ───────────────────────────────────────────────────────
    st.markdown('<div class="sb-section">📐 Layout Halaman</div>', unsafe_allow_html=True)

    orientation = st.radio(
        "Orientasi",
        options=["Portrait", "Landscape"],
        horizontal=True,
        key="page_orientation",
    )

    _cols_default = 4 if orientation == "Landscape" else 3
    if st.session_state.get("_last_orient") != orientation:
        st.session_state["n_cols_slider"] = _cols_default
        st.session_state["_last_orient"]  = orientation

    n_cols = st.slider(
        "Jumlah Kolom",
        min_value=1,
        max_value=10,
        key="n_cols_slider",
        help="Default: Portrait=3, Landscape=4. Kolom ≥8 menghasilkan foto sangat kecil.",
    )

    # ── Output ───────────────────────────────────────────────────────
    st.markdown('<div class="sb-section">🖼️ Kualitas & Output</div>', unsafe_allow_html=True)

    jpeg_quality = st.slider(
        "Kualitas JPEG",
        min_value=10,
        max_value=100,
        value=80,
        step=5,
        key="jpeg_quality_slider",
        help="Lebih tinggi = gambar lebih tajam, ukuran file lebih besar.",
    )
    pdf_name = st.text_input(
        "Nama File PDF",
        value="output_foto",
        key="pdf_name_input",
    )

    # Footer
    st.markdown("""
    <div class="sb-footer">
        Format A4 · JPG / JPEG / PNG<br>
        Waterfall layout · Print-ready
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN AREA
# ═══════════════════════════════════════════════════════════════════════════

# Constrain width with padding columns
_, main, _ = st.columns([0.08, 1, 0.08])

with main:

    # ── Page heading ──────────────────────────────────────────────────
    st.markdown("""
    <div class="main-header">
      <div class="main-title">Cetak Foto Praktikum</div>
      <div class="main-sub">
        Upload foto, atur urutan, dan ekspor ke PDF siap cetak dengan
        <em>waterfall layout</em> yang rapi.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════
    # STEP 01 — UPLOAD
    # ══════════════════════════════════════════════════════════════════
    st.markdown("""
    <div class="step-wrap">
      <div class="step-num">01</div>
      <div class="step-title">Upload Foto</div>
    </div>
    <div class="step-desc">Seret &amp; lepas, klik, atau tempel dari clipboard</div>
    """, unsafe_allow_html=True)

    # Session state for clipboard
    if "clipboard_images" not in st.session_state:
        st.session_state.clipboard_images = []

    upload_col, info_col = st.columns([3, 1], gap="medium")

    with upload_col:
        uploaded_files = st.file_uploader(
            "Pilih foto (JPG, JPEG, PNG)",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )

        if PASTE_SUPPORTED:
            st.markdown("""
            <div class="or-divider">
              <div class="or-line"></div>
              <span class="or-text">atau</span>
              <div class="or-line"></div>
            </div>
            """, unsafe_allow_html=True)

            paste_result = paste_image_button(
                label="📋  Tempel dari Clipboard",
                background_color="#4F46E5",
                hover_background_color="#4338CA",
            )
            if paste_result and paste_result.image_data is not None:
                buf = io.BytesIO()
                paste_result.image_data.save(buf, format="PNG")
                fname_clip = f"clipboard_{len(st.session_state.clipboard_images) + 1}.png"
                st.session_state.clipboard_images.append((buf.getvalue(), fname_clip))

        else:
            st.markdown("""
            <div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:10px;
                        padding:10px 14px;margin-top:10px;font-size:0.79rem;color:#92400E;
                        display:flex;align-items:center;gap:8px;">
              💡 Install <code>streamlit-paste-button</code> untuk aktifkan tempel dari clipboard.
            </div>
            """, unsafe_allow_html=True)

    with info_col:
        st.markdown("""
        <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:14px;
                    padding:18px 14px;font-size:0.76rem;color:#64748B;line-height:1.8;">
          <strong style="color:#374151;font-size:0.8rem;">Format didukung</strong><br>
          📷 JPG / JPEG<br>
          🖼️ PNG<br>
          📋 Clipboard paste<br><br>
          <strong style="color:#374151;font-size:0.8rem;">Output PDF</strong><br>
          📄 A4 · Print-ready<br>
          🖨️ 300 DPI<br>
          🔢 Waterfall layout
        </div>
        """, unsafe_allow_html=True)

    # Clipboard badge & clear button
    if st.session_state.clipboard_images:
        n_clip = len(st.session_state.clipboard_images)
        bcol1, bcol2 = st.columns([4, 1])
        with bcol1:
            st.markdown(f"""
            <div class="clip-badge">
              <span class="clip-badge-icon">✅</span>
              <span class="clip-badge-text">{n_clip} gambar dari clipboard siap diproses</span>
            </div>
            """, unsafe_allow_html=True)
        with bcol2:
            if st.button("🗑️ Hapus", key="btn_del_clipboard", use_container_width=True):
                st.session_state.clipboard_images = []
                st.rerun()

    # Merge all sources
    all_file_items: list[tuple[bytes, str]] = []
    for f in (uploaded_files or []):
        all_file_items.append((f.getvalue(), f.name))
    for img_bytes, fname in st.session_state.clipboard_images:
        all_file_items.append((img_bytes, fname))

    # ──────────────────────────────────────────────────────────────────
    # STEPS 02 & 03 — only when files are present
    # ──────────────────────────────────────────────────────────────────
    if all_file_items:

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        # ══════════════════════════════════════════════════════════════
        # STEP 02 — SORT & CONFIGURE
        # ══════════════════════════════════════════════════════════════
        st.markdown("""
        <div class="step-wrap">
          <div class="step-num">02</div>
          <div class="step-title">Atur Urutan & Keterangan</div>
        </div>
        <div class="step-desc">Pilih urutan tampilan dan aktifkan keterangan jika diperlukan</div>
        """, unsafe_allow_html=True)

        sort_col, cap_col = st.columns([1, 1], gap="medium")

        with sort_col:
            sort_mode = st.selectbox(
                "Urutan foto",
                options=[
                    "Sesuai Urutan Upload",
                    "Nama File A → Z",
                    "Nama File Z → A",
                    "Waktu Pengambilan (Exif)",
                ],
                key="sort_mode_select",
            )

        with cap_col:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            enable_captions = st.checkbox(
                "🏷️  Tambahkan keterangan pada setiap foto",
                value=False,
                help="Teks keterangan dicetak di bawah tiap foto dalam PDF.",
                key="enable_captions_cb",
            )

        # Apply sort
        if sort_mode == "Nama File A → Z":
            all_file_items = sorted(all_file_items, key=lambda x: x[1].lower())
        elif sort_mode == "Nama File Z → A":
            all_file_items = sorted(all_file_items, key=lambda x: x[1].lower(), reverse=True)
        elif sort_mode == "Waktu Pengambilan (Exif)":
            all_file_items = sorted(all_file_items, key=lambda x: get_exif_date(x[0]))

        # Compute layout geometry
        if orientation == "Landscape":
            A4_W = A4_H_PORTRAIT
            A4_H = A4_W_PORTRAIT
        else:
            A4_W = A4_W_PORTRAIT
            A4_H = A4_H_PORTRAIT

        IMG_WIDTH_MM   = compute_img_width(A4_W, n_cols)
        LEFT_MARGIN_MM = PAGE_MARGIN_MM
        col_x          = [LEFT_MARGIN_MM + c * (IMG_WIDTH_MM + GAP_MM) for c in range(n_cols)]
        extra_h        = CAPTION_HEIGHT_MM if enable_captions else 0

        # Process images
        image_data: list[tuple] = []
        for file_bytes, fname in all_file_items:
            img, h_mm = process_image_data(file_bytes, IMG_WIDTH_MM)
            if img:
                image_data.append((img, h_mm, fname))

        n_photos = len(image_data)
        init_captions(image_data)

        # Estimate pages
        has_header    = any([mata_praktikum, judul_modul, tanggal_praktikum])
        page1_start_y = (
            estimate_header_height(mata_praktikum, judul_modul, tanggal_praktikum)
            if has_header else TOP_MARGIN_MM
        )
        est_pages = estimate_pages(
            image_data, n_cols, A4_H, extra_h=extra_h, page1_start_y=page1_start_y
        )

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        # ── Metrics row ───────────────────────────────────────────────
        col_width_label = f"{IMG_WIDTH_MM:.1f}mm"
        orient_label    = "Portrait" if orientation == "Portrait" else "Landscape"

        st.markdown(f"""
        <div class="metric-row">
          <div class="metric-chip">
            <div class="metric-val">{n_photos}</div>
            <div class="metric-label">Foto</div>
          </div>
          <div class="metric-chip">
            <div class="metric-val">{est_pages}</div>
            <div class="metric-label">Halaman</div>
          </div>
          <div class="metric-chip">
            <div class="metric-val">{n_cols}</div>
            <div class="metric-label">Kolom</div>
          </div>
          <div class="metric-chip">
            <div class="metric-val">{col_width_label}</div>
            <div class="metric-label">Lebar Kolom</div>
          </div>
          <div class="metric-chip">
            <div class="metric-val">{jpeg_quality}</div>
            <div class="metric-label">Kualitas JPEG</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Column width warning
        if IMG_WIDTH_MM < MIN_COL_WIDTH_MM:
            st.markdown(f"""
            <div class="warn-strip">
              <span>⚠️</span>
              <span><strong>Kolom sangat sempit ({IMG_WIDTH_MM:.1f}mm)</strong> — foto mungkin tidak terbaca.
              Kurangi jumlah kolom atau pilih orientasi <strong>Landscape</strong> di panel kiri.</span>
            </div>
            """, unsafe_allow_html=True)

        # ══════════════════════════════════════════════════════════════
        # STEP 03 — GENERATE PDF
        # ══════════════════════════════════════════════════════════════
        st.markdown("""
        <div class="step-wrap">
          <div class="step-num">03</div>
          <div class="step-title">Generate &amp; Unduh PDF</div>
        </div>
        <div class="step-desc">Buat file PDF lalu unduh langsung ke perangkat kamu</div>
        """, unsafe_allow_html=True)

        if st.button("✅  Buat PDF Sekarang", type="primary", use_container_width=True):
            progress_bar = st.progress(0, text="Menyiapkan halaman PDF...")

            fpdf_orient = "L" if orientation == "Landscape" else "P"
            pdf = FPDF(orientation=fpdf_orient, unit="mm", format="A4")
            pdf.add_page()

            max_y = A4_H - BOTTOM_MARGIN_MM

            if has_header:
                first_y = draw_header(pdf, mata_praktikum, judul_modul, tanggal_praktikum, A4_W)
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
                    text=f"Memproses foto {i + 1} dari {n_photos}..."
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

            # Success state
            st.markdown(f"""
            <div class="success-banner">
              <div class="success-icon">🎉</div>
              <div>
                <div class="success-text-title">PDF berhasil dibuat!</div>
                <div class="success-text-sub">
                  {n_photos} foto · {est_pages} halaman · {len(pdf_bytes)/1024:.0f} KB
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            st.download_button(
                label=f"📥  Unduh  {output_fname}",
                data=pdf_bytes,
                file_name=output_fname,
                mime="application/pdf",
                use_container_width=True,
            )

        # ── Preview gallery ────────────────────────────────────────────
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        with st.expander("👀  Lihat Preview Galeri Foto"):
            if enable_captions:
                hdr_c, btn_c = st.columns([5, 1])
                with hdr_c:
                    st.caption("✏️  Isi keterangan di bawah tiap foto. Kosongkan jika tidak perlu.")
                with btn_c:
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
                            st.markdown(
                                f"<p style='font-size:0.72rem;color:#9CA3AF;"
                                f"text-align:center;margin-top:-6px;'>"
                                f"[{photo_idx + 1}] {fname}</p>",
                                unsafe_allow_html=True,
                            )

    else:
        # Empty state
        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div class="empty-state">
          <div class="empty-state-icon">📂</div>
          <div class="empty-state-title">Belum ada foto yang diupload</div>
          <div class="empty-state-sub">
            Klik area upload di atas untuk memilih file,<br>
            atau seret foto langsung ke area tersebut.<br><br>
            <strong>Format:</strong> JPG · JPEG · PNG
          </div>
        </div>
        """, unsafe_allow_html=True)
