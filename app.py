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

# ── Page config ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FotoPDF — Lab Print Studio",
    page_icon="🗂️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ─────────────────────────────────────────────────────────────
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
#  HELPER — CORE LOGIC  (unchanged)
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

def fit_caption(pdf, text, max_width_mm):
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
#  HELPER — UI COMPONENTS
#  All use inline styles to sidestep CSS specificity conflicts entirely.
# ═══════════════════════════════════════════════════════════════════════════

def sb_section(icon: str, label: str):
    """Sidebar section header — inline styles, immune to global CSS overrides."""
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:8px;
                margin:22px 0 10px 0;padding-bottom:8px;
                border-bottom:1px solid #334155;">
      <span style="font-size:0.9rem;line-height:1;">{icon}</span>
      <span style="font-size:0.62rem;font-weight:700;color:#818CF8;
                   letter-spacing:0.12em;text-transform:uppercase;">{label}</span>
    </div>
    """, unsafe_allow_html=True)


def step_header(num: str, title: str, desc: str = ""):
    """Numbered step header in the main area."""
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;margin:30px 0 0 0;">
      <div style="width:28px;height:28px;flex-shrink:0;
                  background:linear-gradient(135deg,#4F46E5,#7C3AED);
                  border-radius:8px;display:flex;align-items:center;
                  justify-content:center;font-size:0.68rem;font-weight:800;
                  color:#fff;letter-spacing:0.04em;
                  box-shadow:0 2px 8px rgba(79,70,229,0.32);">{num}</div>
      <div style="font-size:0.95rem;font-weight:700;color:#0F172A;
                  letter-spacing:-0.01em;">{title}</div>
    </div>
    <p style="font-size:0.76rem;color:#94A3B8;margin:5px 0 14px 40px;
              line-height:1.5;">{desc}</p>
    """, unsafe_allow_html=True)


def metric_chip(value, label: str, accent: str = "#4F46E5"):
    """Single metric chip — rendered inside a st.column for reliable flex layout."""
    st.markdown(f"""
    <div style="background:#fff;border:1px solid #E2E8F0;
                border-top:3px solid {accent};border-radius:12px;
                padding:14px 8px;text-align:center;">
      <div style="font-size:1.45rem;font-weight:800;color:#0F172A;
                  letter-spacing:-0.03em;line-height:1.1;">{value}</div>
      <div style="font-size:0.62rem;color:#94A3B8;font-weight:600;
                  letter-spacing:0.08em;text-transform:uppercase;
                  margin-top:4px;">{label}</div>
    </div>
    """, unsafe_allow_html=True)


def success_banner(n_photos: int, est_pages: int, file_size_kb: float):
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:16px;
                background:linear-gradient(135deg,#ECFDF5,#D1FAE5);
                border:1px solid #A7F3D0;border-radius:14px;
                padding:18px 22px;margin-bottom:14px;">
      <div style="font-size:1.9rem;flex-shrink:0;">🎉</div>
      <div>
        <div style="font-size:0.95rem;font-weight:700;color:#065F46;">
          PDF berhasil dibuat!
        </div>
        <div style="font-size:0.78rem;color:#059669;margin-top:3px;">
          {n_photos} foto &nbsp;·&nbsp; {est_pages} halaman &nbsp;·&nbsp; {file_size_kb:.0f} KB
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)


def warn_strip(message: str):
    st.markdown(f"""
    <div style="display:flex;align-items:flex-start;gap:10px;
                background:#FFFBEB;border:1px solid #FDE68A;
                border-left:4px solid #F59E0B;
                border-radius:0 10px 10px 0;padding:12px 16px;
                font-size:0.81rem;color:#92400E;margin:10px 0;line-height:1.55;">
      <span style="flex-shrink:0;font-size:1rem;">⚠️</span>
      <span>{message}</span>
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
#  GLOBAL CSS
#  Scope: only layout, branding, and Streamlit widget chrome.
#  No blanket * overrides. Sidebar text/color handled via inline styles above.
# ═══════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* ── Base ───────────────────────────────────────────────────────── */
html, body, .stApp {
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
    background-color: #F1F5F9 !important;
}

/* ── Remove default Streamlit chrome ────────────────────────────── */
[data-testid="stDecoration"] { display: none !important; }
[data-testid="stHeader"]     { display: none !important; }
#MainMenu                    { display: none !important; }
footer                       { display: none !important; }

/* ═════════════════════════════════════════════════════════════════
   SIDEBAR — dark control panel
   Rule: only target the container + specific leaf elements.
   Never use descendant wildcard (*) here.
═══════════════════════════════════════════════════════════════════ */
section[data-testid="stSidebar"],
section[data-testid="stSidebar"] > div,
section[data-testid="stSidebar"] > div > div {
    background-color: #1E293B !important;
}

/* Widget labels */
section[data-testid="stSidebar"] label {
    color: #94A3B8 !important;
    font-size: 0.76rem !important;
    font-weight: 500 !important;
}

/* Markdown paragraph text in sidebar */
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    color: #64748B !important;
    font-size: 0.75rem !important;
    line-height: 1.55 !important;
}

/* Text inputs */
section[data-testid="stSidebar"] input[type="text"],
section[data-testid="stSidebar"] input[type="number"] {
    background-color: #0F172A !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    color: #E2E8F0 !important;
    font-size: 0.84rem !important;
}
section[data-testid="stSidebar"] input[type="text"]:focus,
section[data-testid="stSidebar"] input[type="number"]:focus {
    border-color: #6366F1 !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.18) !important;
    outline: none !important;
}

/* Slider tick labels */
section[data-testid="stSidebar"] [data-testid="stSlider"] p {
    color: #64748B !important;
    font-size: 0.72rem !important;
}

/* Radio labels */
section[data-testid="stSidebar"] [data-testid="stRadio"] label p {
    color: #94A3B8 !important;
    font-size: 0.82rem !important;
}

/* ═════════════════════════════════════════════════════════════════
   MAIN AREA — Upload zone
═══════════════════════════════════════════════════════════════════ */
[data-testid="stFileUploader"] section {
    border: 2px dashed #C7D2FE !important;
    border-radius: 14px !important;
    background-color: #FAFBFF !important;
    padding: 40px 20px !important;
    transition: border-color 0.2s ease, background-color 0.2s ease !important;
    cursor: pointer !important;
}
[data-testid="stFileUploader"] section:hover {
    border-color: #6366F1 !important;
    background-color: #EEF2FF !important;
}
[data-testid="stFileUploader"] section > div > p {
    color: #6B7280 !important;
    font-size: 0.88rem !important;
}

/* ═════════════════════════════════════════════════════════════════
   BUTTONS
═══════════════════════════════════════════════════════════════════ */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #4F46E5, #7C3AED) !important;
    border: none !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: 0.92rem !important;
    color: #fff !important;
    padding: 13px 24px !important;
    box-shadow: 0 4px 14px rgba(79,70,229,0.35) !important;
    transition: transform 0.18s ease, box-shadow 0.18s ease !important;
    letter-spacing: 0.01em !important;
}
.stButton > button[kind="primary"]:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 24px rgba(79,70,229,0.45) !important;
}
.stButton > button[kind="primary"]:active {
    transform: translateY(0) !important;
}

.stButton > button[kind="secondary"] {
    border-color: #E2E8F0 !important;
    color: #64748B !important;
    border-radius: 10px !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    transition: background 0.15s ease, border-color 0.15s ease !important;
}
.stButton > button[kind="secondary"]:hover {
    background: #F8FAFC !important;
    border-color: #CBD5E1 !important;
    color: #374151 !important;
}

/* ── Download button ─────────────────────────────────────────── */
.stDownloadButton > button {
    background: linear-gradient(135deg, #059669, #047857) !important;
    border: none !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: 0.92rem !important;
    color: #fff !important;
    box-shadow: 0 4px 14px rgba(5,150,105,0.35) !important;
    transition: transform 0.18s ease, box-shadow 0.18s ease !important;
}
.stDownloadButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 24px rgba(5,150,105,0.45) !important;
}

/* ═════════════════════════════════════════════════════════════════
   EXPANDER
═══════════════════════════════════════════════════════════════════ */
[data-testid="stExpander"] {
    background: #FFFFFF !important;
    border: 1px solid #E2E8F0 !important;
    border-radius: 14px !important;
    overflow: hidden !important;
}
[data-testid="stExpander"] summary {
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    color: #374151 !important;
    padding: 14px 18px !important;
    background: #F8FAFC !important;
    border-bottom: 1px solid #F1F5F9 !important;
}
[data-testid="stExpander"] summary:hover {
    background: #F1F5F9 !important;
}

/* ═════════════════════════════════════════════════════════════════
   CHECKBOX & SELECTBOX
═══════════════════════════════════════════════════════════════════ */
.stCheckbox label p {
    font-size: 0.88rem !important;
    color: #374151 !important;
}
.stSelectbox label {
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    color: #64748B !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
}

/* ═════════════════════════════════════════════════════════════════
   PROGRESS BAR  — target the fill div, not the outer wrapper
═══════════════════════════════════════════════════════════════════ */
[data-testid="stProgressBar"] div[role="progressbar"] > div {
    background: linear-gradient(90deg, #4F46E5, #7C3AED) !important;
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
#  SIDEBAR — CONTROL PANEL
# ═══════════════════════════════════════════════════════════════════════════

with st.sidebar:

    # ── Brand header (inline styles — safe from CSS override) ─────────
    st.markdown("""
    <div style="background:linear-gradient(160deg,#312E81,#1E1B4B);
                padding:22px 20px 18px;margin:-1rem -1rem 0;
                border-bottom:1px solid #312E81;">
      <div style="width:42px;height:42px;
                  background:linear-gradient(135deg,#6366F1,#8B5CF6);
                  border-radius:12px;display:flex;align-items:center;
                  justify-content:center;font-size:1.25rem;margin-bottom:12px;
                  box-shadow:0 4px 14px rgba(99,102,241,0.45);">🗂️</div>
      <div style="font-size:1.05rem;font-weight:800;color:#F8FAFC;
                  letter-spacing:-0.02em;line-height:1.1;">FotoPDF</div>
      <div style="font-size:0.72rem;color:#6366F1;margin-top:3px;
                  font-weight:500;">Lab Print Studio</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Identitas Praktikan ───────────────────────────────────────────
    sb_section("📋", "Identitas Praktikan")
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

    # ── Layout ────────────────────────────────────────────────────────
    sb_section("📐", "Layout Halaman")

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

    # ── Output ────────────────────────────────────────────────────────
    sb_section("🖼️", "Kualitas & Output")

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
    <div style="font-size:0.65rem;color:#334155;text-align:center;
                padding:18px 0 4px;border-top:1px solid #334155;margin-top:16px;
                line-height:1.8;">
      Format A4 &nbsp;·&nbsp; JPG / JPEG / PNG<br>
      Waterfall layout &nbsp;·&nbsp; 300 DPI
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN AREA
# ═══════════════════════════════════════════════════════════════════════════

# Page heading
st.markdown("""
<div style="padding:20px 0 18px;border-bottom:2px solid #E2E8F0;margin-bottom:4px;">
  <div style="font-size:1.5rem;font-weight:800;color:#0F172A;
              letter-spacing:-0.03em;line-height:1.1;">
    Cetak Foto Praktikum
  </div>
  <div style="font-size:0.83rem;color:#64748B;margin-top:6px;line-height:1.5;">
    Upload foto, atur urutan, dan ekspor ke PDF siap cetak dengan
    <em>waterfall layout</em> yang rapi.
  </div>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# STEP 01 — UPLOAD
# ══════════════════════════════════════════════════════════════════

step_header("01", "Upload Foto", "Seret &amp; lepas, klik, atau tempel dari clipboard")

if "clipboard_images" not in st.session_state:
    st.session_state.clipboard_images = []

uploaded_files = st.file_uploader(
    "Pilih foto (JPG, JPEG, PNG)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

# Paste from clipboard
if PASTE_SUPPORTED:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;margin:12px 0;">
      <div style="flex:1;height:1px;background:#E2E8F0;"></div>
      <span style="font-size:0.68rem;font-weight:700;color:#9CA3AF;
                   letter-spacing:0.1em;text-transform:uppercase;white-space:nowrap;">atau</span>
      <div style="flex:1;height:1px;background:#E2E8F0;"></div>
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

# Clipboard badge + clear
if st.session_state.clipboard_images:
    n_clip = len(st.session_state.clipboard_images)
    badge_col, clear_col = st.columns([5, 1])
    with badge_col:
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:10px;
                    background:#EFF6FF;border:1px solid #BFDBFE;
                    border-radius:10px;padding:10px 14px;margin:10px 0;
                    font-size:0.82rem;font-weight:600;color:#1D4ED8;">
          ✅ &nbsp;{n_clip} gambar dari clipboard siap diproses
        </div>
        """, unsafe_allow_html=True)
    with clear_col:
        st.write("")
        if st.button("🗑️ Hapus", key="btn_del_clipboard", use_container_width=True):
            st.session_state.clipboard_images = []
            st.rerun()

# ── Merge all sources ─────────────────────────────────────────────
all_file_items: list[tuple[bytes, str]] = []
for f in (uploaded_files or []):
    all_file_items.append((f.getvalue(), f.name))
for img_bytes, fname in st.session_state.clipboard_images:
    all_file_items.append((img_bytes, fname))


# ══════════════════════════════════════════════════════════════════
# STEPS 02 & 03 — only when files are present
# ══════════════════════════════════════════════════════════════════

if all_file_items:

    # ── STEP 02 — SORT & CONFIGURE ───────────────────────────────────
    step_header("02", "Atur Urutan & Keterangan",
                "Pilih urutan tampilan dan aktifkan keterangan jika diperlukan")

    sort_col, cap_col = st.columns([1, 1])
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

    # ── Compute geometry ──────────────────────────────────────────────
    if orientation == "Landscape":
        A4_W, A4_H = A4_H_PORTRAIT, A4_W_PORTRAIT
    else:
        A4_W, A4_H = A4_W_PORTRAIT, A4_H_PORTRAIT

    IMG_WIDTH_MM   = compute_img_width(A4_W, n_cols)
    LEFT_MARGIN_MM = PAGE_MARGIN_MM
    col_x          = [LEFT_MARGIN_MM + c * (IMG_WIDTH_MM + GAP_MM) for c in range(n_cols)]
    extra_h        = CAPTION_HEIGHT_MM if enable_captions else 0

    # ── Process images ────────────────────────────────────────────────
    image_data: list[tuple] = []
    failed_count = 0
    for file_bytes, fname in all_file_items:
        img, h_mm = process_image_data(file_bytes, IMG_WIDTH_MM)
        if img:
            image_data.append((img, h_mm, fname))
        else:
            failed_count += 1

    n_photos = len(image_data)
    init_captions(image_data)

    # ── Estimate pages ────────────────────────────────────────────────
    has_header    = any([mata_praktikum, judul_modul, tanggal_praktikum])
    page1_start_y = (
        estimate_header_height(mata_praktikum, judul_modul, tanggal_praktikum)
        if has_header else TOP_MARGIN_MM
    )
    est_pages = estimate_pages(
        image_data, n_cols, A4_H, extra_h=extra_h, page1_start_y=page1_start_y
    )

    # ── Metric chips — one per st.column (reliable, no flex hack) ─────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1: metric_chip(n_photos, "Foto")
    with m2: metric_chip(est_pages, "Halaman")
    with m3: metric_chip(n_cols, "Kolom")
    with m4: metric_chip(f"{IMG_WIDTH_MM:.1f}mm", "Lebar Kolom", "#0EA5E9")
    with m5: metric_chip(jpeg_quality, "Kualitas JPEG", "#F59E0B")

    # Show failed count if any
    if failed_count:
        warn_strip(
            f"<strong>{failed_count} file gagal diproses</strong> dan tidak akan "
            f"disertakan dalam PDF. Pastikan file tidak rusak."
        )

    # Column width warning
    if IMG_WIDTH_MM < MIN_COL_WIDTH_MM:
        warn_strip(
            f"Lebar kolom saat ini <strong>{IMG_WIDTH_MM:.1f}mm</strong> — terlalu sempit "
            f"dan foto mungkin tidak terbaca. Kurangi jumlah kolom atau pilih orientasi "
            f"<strong>Landscape</strong> di panel kiri."
        )

    # ── STEP 03 — GENERATE PDF ────────────────────────────────────────
    step_header("03", "Generate &amp; Unduh PDF",
                "Buat file PDF lalu unduh langsung ke perangkat kamu")

    if st.button("✅  Buat PDF Sekarang", type="primary", use_container_width=True):

        progress_bar = st.progress(0, text="Menyiapkan halaman PDF...")

        fpdf_orient = "L" if orientation == "Landscape" else "P"
        pdf         = FPDF(orientation=fpdf_orient, unit="mm", format="A4")
        pdf.add_page()

        max_y = A4_H - BOTTOM_MARGIN_MM

        first_y = draw_header(pdf, mata_praktikum, judul_modul, tanggal_praktikum, A4_W) \
                  if has_header else TOP_MARGIN_MM

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

        # Build output bytes
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

        success_banner(n_photos, est_pages, len(pdf_bytes) / 1024)
        st.download_button(
            label=f"📥  Unduh  {output_fname}",
            data=pdf_bytes,
            file_name=output_fname,
            mime="application/pdf",
            use_container_width=True,
        )

    # ── Preview gallery ───────────────────────────────────────────────
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    with st.expander("👀  Lihat Preview Galeri Foto"):

        if enable_captions:
            cap_label_col, cap_reset_col = st.columns([5, 1])
            with cap_label_col:
                st.caption("✏️  Isi keterangan di bawah tiap foto. Kosongkan jika tidak perlu.")
            with cap_reset_col:
                if st.button("🔄 Reset", key="btn_reset_caps", use_container_width=True):
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
                            f"<p style='font-size:0.71rem;color:#9CA3AF;"
                            f"text-align:center;margin-top:-4px;'>"
                            f"[{photo_idx + 1}] {fname}</p>",
                            unsafe_allow_html=True,
                        )

else:
    # Empty state
    st.markdown("""
    <div style="text-align:center;padding:60px 24px;background:#fff;
                border:2px dashed #E2E8F0;border-radius:20px;margin-top:16px;">
      <div style="font-size:3.5rem;margin-bottom:14px;">📂</div>
      <div style="font-size:1.05rem;font-weight:700;color:#374151;margin-bottom:8px;">
        Belum ada foto yang diupload
      </div>
      <div style="font-size:0.82rem;color:#9CA3AF;line-height:1.75;">
        Klik area upload di atas untuk memilih file,<br>
        atau seret foto langsung ke sana.<br><br>
        <strong style="color:#CBD5E1;">Format: JPG &nbsp;·&nbsp; JPEG &nbsp;·&nbsp; PNG</strong>
      </div>
    </div>
    """, unsafe_allow_html=True)