import streamlit as st
import polars as pl
from pathlib import Path
from datetime import datetime, date
import re
import io
import traceback

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="KPI Pipeline",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
/* ── reset to clean white ── */
html, body, [data-testid="stAppViewContainer"] { background: #ffffff !important; }
[data-testid="stSidebar"] { background: #f7f8fa !important; }
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; }

/* ── tabs ── */
.stTabs [data-baseweb="tab-list"] {
    border-bottom: 2px solid #e5e7eb; gap: 0;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: #6b7280;
    font-size: 14px; font-weight: 500;
    padding: 10px 20px;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
}
.stTabs [aria-selected="true"] {
    color: #1d4ed8 !important;
    border-bottom: 2px solid #1d4ed8 !important;
    background: transparent !important;
}

/* ── metrics ── */
div[data-testid="stMetric"] {
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 14px 18px;
}
div[data-testid="stMetricValue"] { font-size: 24px; color: #111827; }
div[data-testid="stMetricLabel"] { font-size: 12px; color: #6b7280; }

/* ── section header ── */
.sec-header {
    font-size: 11px; font-weight: 700; letter-spacing: 1.2px;
    text-transform: uppercase; color: #6b7280;
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 6px; margin: 18px 0 10px 0;
}

/* ── status badges ── */
.badge-ok   { display:inline-block; background:#dcfce7; color:#166534;
              border-radius:99px; padding:2px 10px; font-size:12px; font-weight:600; }
.badge-wait { display:inline-block; background:#fef9c3; color:#854d0e;
              border-radius:99px; padding:2px 10px; font-size:12px; font-weight:600; }
.badge-err  { display:inline-block; background:#fee2e2; color:#991b1b;
              border-radius:99px; padding:2px 10px; font-size:12px; font-weight:600; }

/* ── log box ── */
.log-box {
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;
    padding: 12px 14px; font-family: 'Courier New', monospace; font-size: 11.5px;
    max-height: 260px; overflow-y: auto; white-space: pre-wrap; line-height: 1.6;
}

/* ── pipeline diagram ── */
.flow-row { display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin: 8px 0; }
.flow-box {
    background:#eff6ff; border:1px solid #bfdbfe; border-radius:6px;
    padding:6px 14px; font-size:13px; font-weight:500; color:#1e40af;
}
.flow-box.lookup {
    background:#f0fdf4; border-color:#bbf7d0; color:#166534;
}
.flow-box.out {
    background:#faf5ff; border-color:#e9d5ff; color:#6b21a8;
}
.flow-arrow { color:#9ca3af; font-size:18px; }

/* ── path input ── */
.stTextInput input {
    font-family: monospace; font-size: 13px;
    border-radius: 6px;
}

/* ── button ── */
.stButton > button {
    background: #1d4ed8; color: white; border: none;
    border-radius: 6px; padding: 8px 20px; font-weight: 600;
}
.stButton > button:hover { background: #1e40af; }

/* hide default footer */
footer { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ─── Session state ─────────────────────────────────────────────────────────
for key in ["logs", "df_clean", "df_agg", "run_status"]:
    if key not in st.session_state:
        if key == "logs":
            st.session_state[key] = []
        elif key == "run_status":
            st.session_state[key] = {}
        else:
            st.session_state[key] = {}


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    color = {"INFO": "#16a34a", "WARN": "#b45309", "ERROR": "#dc2626"}.get(level, "#374151")
    st.session_state.logs.append(f'<span style="color:{color}">[{ts}] [{level}] {msg}</span>')


def render_log():
    if st.session_state.logs:
        html = "<br>".join(st.session_state.logs[-100:])
        st.markdown(f'<div class="log-box">{html}</div>', unsafe_allow_html=True)


def badge(text, kind="ok"):
    return f'<span class="badge-{kind}">{text}</span>'


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def read_file(p: Path) -> pl.DataFrame:
    if p.suffix.lower() == ".csv":
        df = pl.read_csv(p, infer_schema_length=1000)
    elif p.suffix.lower() in (".xlsx", ".xlsm"):
        df = pl.read_excel(p)
    else:
        raise ValueError(f"Không hỗ trợ định dạng: {p.suffix}")
    return df.rename({c: c.strip() for c in df.columns})


def extract_date_from_name(name: str) -> date:
    for pat, fmt in [(r"_(\d{2}-\d{2}-\d{4})", "%d-%m-%Y"), (r"_(\d{8})", "%Y%m%d"), (r"_(\d{8})", "%d%m%Y")]:
        m = re.search(pat, name)
        if m:
            return datetime.strptime(m.group(1), fmt).date()
    raise ValueError(f"Không lấy được ngày từ tên file: {name}")


def scan_folder(folder: Path, exts=(".csv",".xlsx",".xlsm")) -> list[Path]:
    """Liệt kê file trong folder, sort mới nhất trước (theo mtime)."""
    if not folder.exists():
        return []
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in exts]
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)

def read_clean_folder(folder: Path, exts=(".csv", ".xlsx", ".xlsm")) -> pl.DataFrame:
    """
    Đọc toàn bộ file clean trong folder rồi concat lại.
    Dùng riêng cho bước aggregate.
    """
    files = scan_folder(folder, exts=exts)

    if not files:
        raise FileNotFoundError(f"Không tìm thấy file clean trong folder: {folder}")

    frames = []

    for f in files:
        df = read_file(f)
        frames.append(df)

    return pl.concat(frames, how="vertical_relaxed").unique()


def file_dropdown(label: str, folder: Path, key: str,
                  exts=(".csv",".xlsx",".xlsm"),
                  filter_fn=None,
                  ) -> Path | None:
    """
    Render selectbox với danh sách file trong folder.
    Mặc định chọn file mới nhất. Trả về Path hoặc None.
    """
    files = scan_folder(folder, exts)
    if filter_fn:
        files = [f for f in files if filter_fn(f)]
    if not files:
        st.warning(f"Không tìm thấy file nào trong: {folder}", icon="⚠️")
        return None
    names = [f.name for f in files]
    # tìm index đang được lưu trong session (nếu có), giữ selection khi rerun
    saved = st.session_state.get(key)
    default_idx = 0
    if saved and saved in names:
        default_idx = names.index(saved)
    chosen = st.selectbox(label, names, index=default_idx, key=key)
    return folder / chosen if chosen else None


# ═══════════════════════════════════════════════════════════════════════════════
# CLEAN FUNCTIONS  
# ═══════════════════════════════════════════════════════════════════════════════

def clean_xuatsach(raidich_path: Path, ketnoi_path: Path, mapping_route_path: Path):
    SELECT_COLS = [
        "ma_phieugui","don_vi_khaithac","ma_buucuc_goc","ma_buucuc_phat",
        "trong_luong","loai_dv","tg_nhap_buucuc","tg_laixe_nhan","deadline",
        "report_date","chi_nhanh_HUB","chi_nhanh_phat","Result_p",
        "ca_xuat","tuyen_xuat","ngay_xuat","timedelta",
    ]
    RENAME_MAP = {"chi_nhanh_HUB":"tinh_khaithac","Result_p":"danh_gia","chi_nhanh_phat":"tinh_phat"}
    TIME_COLS  = ["tg_nhap_buucuc","tg_laixe_nhan","deadline"]

    def prep(p: Path):
        fd = extract_date_from_name(p.name)
        df = read_file(p)
        missing = [c for c in SELECT_COLS if c not in df.columns]
        df = df.with_columns([pl.lit(None).alias(c) for c in missing])
        df = (
            df.filter((pl.col("don_hoan")==0) & pl.col("Result_p").is_in(["Đúng","Sai hẹn"]))
            .select(SELECT_COLS).rename(RENAME_MAP)
            .with_columns([
                pl.col(c).cast(pl.Utf8)
                .str.strptime(pl.Datetime, format="%Y-%m-%dT%H:%M:%S%.f", strict=False).alias(c)
                for c in TIME_COLS
            ])
            .with_columns([
                pl.lit(fd).cast(pl.Date).alias("date"),
                (
                    pl.col("timedelta").cast(pl.Utf8).str.extract(r"^(\d+)\.",1).cast(pl.Float64)*24
                    + pl.col("timedelta").cast(pl.Utf8).str.extract(r"\.(\d+):",1).cast(pl.Float64)
                    + pl.col("timedelta").cast(pl.Utf8).str.extract(r":(\d+):",1).cast(pl.Float64)/60
                ).alias("timedelta"),
            ])
        )
        return df, fd

    df_rd, date_rd = prep(raidich_path)
    df_kn, date_kn = prep(ketnoi_path)
    if date_rd != date_kn:
        raise ValueError(f"Ngày không khớp: RaiDich={date_rd}, KetNoi={date_kn}")

    df = pl.concat([df_rd, df_kn], how="vertical_relaxed")
    lookup = (
        pl.read_excel(mapping_route_path, sheet_name="2_route_type")
        .unique(subset=["province_source","province_dest"])
    )
    df = (
        df.join(
            lookup.select(["province_source","province_dest","ttkt_source","ttkt_dest","loai_ket_noi"]),
            left_on=["tinh_khaithac","tinh_phat"], right_on=["province_source","province_dest"], how="left"
        )
        .with_columns(
            pl.when(pl.col("danh_gia")=="Đúng").then(pl.lit("Đúng"))
            .when(pl.col("timedelta")<2).then(pl.lit("Xuất trễ"))
            .otherwise(pl.lit("Trượt ca")).alias("nguyen_nhan")
        )
        .rename({"ttkt_source":"ttkt_goc","ttkt_dest":"ttkt_dich"})
    )
    return df, date_rd

def clean_15s(folder_path: Path):
    dfs = []
    for file in folder_path.glob("*_*.xlsx"):
        if file.name.startswith("~$"):
            continue
        m = re.search(r"_(\d{8})\.xlsx$", file.name, flags=re.IGNORECASE)
        if not m:
            continue

        date_str = m.group(1)
        file_date = pl.Series([date_str]).str.strptime(pl.Date, "%d%m%Y")[0]

        temp = pl.read_excel(
            file,
            read_options={
                "skip_rows": 3
            }
        )

        df = (
            temp
            .select([
                pl.col(temp.columns[1]).alias("Đơn vị"),                # cột 2
                pl.col(temp.columns[5]).alias("Số tải kiện nhập"),           # cột 6
                pl.col(temp.columns[12]).alias("Tỷ lệ nhập đúng giờ")   # cột 13
            ])
            .with_columns(
                pl.lit(file_date).alias("date")
            )
        )

        dfs.append(df)

    if not dfs:
        raise FileNotFoundError(f"Không tìm thấy file 15s hợp lệ trong: {folder_path}")

    return pl.concat(dfs, how="vertical")


def clean_chonhap(file_path: Path, lookup_route_path: Path) -> pl.DataFrame:
    TIME_COLS   = ["tg_xe_check_in","tg_nhap_tai_kien_dau_tien","tg_xe_check_out","tg_du_kien_den"]
    NUM_COLS    = ["tong_tai_kien_nhap","trong_luong_nhap"]
    SELECT_COLS = [
        "date","chi_nhanh","don_vi","tuyen_xe","chuyen_xe",
        "tong_tai_kien_nhap","trong_luong_nhap",
        "tg_xe_check_in","tg_xe_check_out","tg_nhap_tai_kien_dau_tien","tg_chonhap",
    ]
    df      = read_file(file_path)
    lookup  = pl.read_excel(lookup_route_path, sheet_name="lookup_route")
    return (
        df
        .with_columns([
            pl.col(c).cast(pl.Utf8, strict=False).str.strip_chars().str.replace_all("-","/")
            .str.to_datetime("%d/%m/%Y %H:%M:%S", strict=False).alias(c)
            for c in TIME_COLS
        ])
        .with_columns([pl.col(c).cast(pl.Float64, strict=False).alias(c) for c in NUM_COLS])
        .with_columns([
            pl.col("tg_nhap_tai_kien_dau_tien").dt.date().alias("date"),
            (pl.col("tg_nhap_tai_kien_dau_tien")-pl.col("tg_xe_check_in")).alias("tg_chonhap"),
        ])
        .filter(
            pl.col("tg_chonhap").is_not_null()
            & (pl.col("tg_chonhap") > pl.duration(seconds=0))
            & (~pl.col("tuyen_xe").str.starts_with("PH"))
            & (pl.col("tong_tai_kien_nhap") > 10)
            & (pl.col("tg_nhap_tai_kien_dau_tien") > pl.col("tg_xe_check_in"))
            & (pl.col("tg_nhap_tai_kien_dau_tien") < pl.col("tg_xe_check_out"))
        )
        .select(SELECT_COLS)
        .with_columns((pl.col("tg_chonhap").dt.total_seconds()/60).alias("tg_chonhap"))
        .join(lookup.select(["Tên tuyến","Loại hành trình"]), left_on="tuyen_xe", right_on="Tên tuyến", how="left")
        .unique()
    )


def clean_kndd(file_path: Path, lookup_route_path: Path, lookup_dvc_path: Path) -> pl.DataFrame:
    SELECT_COLS = [
        "Mã chuyến xe","Tên tuyến","Mã đơn vị vận chuyển","Chiều","Lái xe","Biển số xe",
        "Số điện thoại","Mã điểm kết nối","Thời gian xuất phát quy định",
        "Chênh lệch thời gian xuất phát","Thời gian đến quy định","Thời gian checkin",
        "Chênh lệch thời gian đến","Thời gian checkout","Thời gian NVKT quét nhận",
    ]
    file_date     = extract_date_from_name(file_path.name)
    df            = read_file(file_path)
    lookup_route  = pl.read_excel(lookup_route_path, sheet_name="lookup_route")
    lookup_dvc    = read_file(lookup_dvc_path)
    return (
        df.select(SELECT_COLS)
        .filter(
            pl.col("Thời gian checkin").is_not_null()
            & (pl.col("Thời gian checkin").cast(pl.Utf8).str.strip_chars() != "")
        )
        .join(lookup_route.select(["Tên tuyến","Loại hành trình"]), on="Tên tuyến", how="left")
        .with_columns([
            pl.col("Thời gian checkin").cast(pl.Utf8,strict=False).str.strip_chars()
            .str.to_datetime("%H:%M %d-%m-%Y", strict=False),
            pl.col("Thời gian đến quy định").cast(pl.Utf8,strict=False).str.strip_chars()
            .str.to_datetime("%H:%M %d-%m-%Y", strict=False),
        ])
        .with_columns((pl.col("Thời gian checkin")-pl.col("Thời gian đến quy định")).alias("Chênh lệch thời gian"))
        .with_columns(
            pl.when(pl.col("Chênh lệch thời gian")>pl.duration(minutes=15))
            .then(pl.lit("Sai")).otherwise(pl.lit("Đúng")).alias("Đánh giá đúng giờ")
        )
        .with_columns(pl.col("Chênh lệch thời gian").dt.total_seconds()/60)
        .with_columns(pl.col("Thời gian checkin").dt.date().alias("date"))
        .join(lookup_dvc.select(["donvi_vanchuyen","branch"]), left_on="Mã đơn vị vận chuyển", right_on="donvi_vanchuyen", how="left")
        .filter(pl.col("date") <= file_date)
        .unique()
    )


def clean_hqx(file_path: Path, lookup_route_path: Path) -> pl.DataFrame:
    SELECT_COLS = [
        "Mã chuyến xe","Đơn vị vận chuyển","Mã hành trình","Loại hành trình","Chiều",
        "Tên tuyến","Biển số xe","Loại phương tiện","Đối tác",
        "Khối lượng hàng hóa (kg)","Trọng tải xe (kg)","TG khởi hành","TG kết thúc",
        "Km hành trình","date",
    ]
    TIME_COLS    = ["TG khởi hành","TG kết thúc"]
    df           = read_file(file_path)
    lookup_route = pl.read_excel(lookup_route_path, sheet_name="lookup_route")

    def prep(route_types, km_lim):
        return (
            df.filter(pl.col("Loại hành trình").is_in(route_types))
            .with_columns([
                pl.col(c).str.to_datetime(format="%H:%M:%S %d/%m/%Y", strict=False).alias(c)
                for c in TIME_COLS
            ])
            .with_columns(pl.col("TG khởi hành").dt.date().alias("date"))
            .with_columns(((pl.col("TG kết thúc")-pl.col("TG khởi hành"))<pl.duration(minutes=10)).alias("_ao"))
            .filter((~pl.col("_ao")) & (pl.col("Khối lượng hàng hóa (kg)")!=0) & (pl.col("Km hành trình")<km_lim))
            .drop(["_ao"])
            .select(SELECT_COLS)
            .join(lookup_route[["Tên tuyến","branch","unit"]], on="Tên tuyến", how="left")
        )

    return pl.concat([prep(["Nội tỉnh","Nội thành"], 1000), prep(["Nội miền","Liên miền"], 5000)], how="vertical")


# ═══════════════════════════════════════════════════════════════════════════════
# AGG FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

AGG_COLS = ["kpi_name","kpi_id","branch","unit","date","year","month","day","numerator","denominator"]

HQX_CONFIG = {
    "Hiệu quả xe nội tỉnh chiều đi":  {"route_type":["Nội tỉnh","Nội thành"],"direction":"Đi", "num":"Khối lượng hàng hóa (kg)","den":"Trọng tải xe (kg)","kpi_id":8},
    "Hiệu quả xe nội tỉnh chiều về":  {"route_type":["Nội tỉnh","Nội thành"],"direction":"Về", "num":"Khối lượng hàng hóa (kg)","den":"Trọng tải xe (kg)","kpi_id":9},
    "Hiệu quả kết nối nội tỉnh":      {"route_type":["Nội tỉnh","Nội thành"],"direction":None, "num":"Khối lượng hàng hóa (kg)","den":"Km hành trình","kpi_id":7},
    "Hiệu quả xe nội miền chiều đi":  {"route_type":["Nội miền"],            "direction":"Đi", "num":"Khối lượng hàng hóa (kg)","den":"Trọng tải xe (kg)","kpi_id":15},
    "Hiệu quả xe nội miền chiều về":  {"route_type":["Nội miền"],            "direction":"Về", "num":"Khối lượng hàng hóa (kg)","den":"Trọng tải xe (kg)","kpi_id":16},
    "Hiệu quả xe liên miền":          {"route_type":["Liên miền"],           "direction":None, "num":"Khối lượng hàng hóa (kg)","den":"Trọng tải xe (kg)","kpi_id":18},
    "Hiệu quả kết nối nội miền":      {"route_type":["Nội miền"],            "direction":None, "num":"Khối lượng hàng hóa (kg)","den":"Km hành trình","kpi_id":17},
}


def add_date_parts(df): return df.with_columns([pl.col("date").dt.year().alias("year"), pl.col("date").dt.month().alias("month"), pl.col("date").dt.day().alias("day")])

def agg_xuatsach(df, lb):
    return (df.rename({"don_vi_khaithac":"unit"}).group_by(["date","unit"])
        .agg([pl.col("ma_phieugui").filter(pl.col("danh_gia")=="Đúng").count().alias("numerator"), pl.col("ma_phieugui").count().alias("denominator")])
        .pipe(add_date_parts).with_columns([pl.lit("Tỷ lệ xuất sạch").alias("kpi_name"),pl.lit(3).alias("kpi_id")])
        .join(lb,on="unit",how="left").select(AGG_COLS).filter(pl.col("branch").is_not_null()))

def agg_15s(df, lb):
    return (df.rename({"Đơn vị":"unit","Số tải kiện nhập":"denominator","Tỷ lệ nhập đúng giờ":"value"}).join(lb.select(["unit","branch"]), on = "unit",how = "left")
    .with_columns(
    [
        pl.lit("Tỷ lệ nhập đúng tải kiện 12.5s").alias("kpi_name"),
        pl.lit(5).alias("kpi_id"),
        pl.col("date").dt.year().alias("year"),
        pl.col("date").dt.month().alias("month"),
        pl.col("date").dt.day().alias("day"),
        (pl.col("value")*pl.col("denominator")/100).alias("numerator")

    ]
    )
    .select(["kpi_name","kpi_id","branch","unit","date","year","month","day","numerator","denominator"])
    .filter(pl.col("branch").is_not_null()))

def agg_chonhap(df, lb):
    return (df.group_by(["date","don_vi"])
        .agg([pl.col("tg_chonhap").sum().alias("numerator"),pl.col("chuyen_xe").count().alias("denominator")])
        .pipe(add_date_parts).with_columns([pl.lit("Thời gian chờ nhập").alias("kpi_name"),pl.lit(4).alias("kpi_id")])
        .rename({"don_vi":"unit"}).join(lb,on="unit",how="left").select(AGG_COLS).filter(pl.col("branch").is_not_null())).filter(~((pl.col("kpi_id")==4)
              &(pl.col("branch").is_in(["CNKT1","CNKT2","CNKT3","CNKT4","CNKT5"]))))

def agg_kndd(df, lb):
    return (df.group_by(["date","Mã đơn vị vận chuyển"])
        .agg([pl.col("Mã điểm kết nối").filter(pl.col("Đánh giá đúng giờ")=="Đúng").count().alias("numerator"), pl.col("Mã điểm kết nối").count().alias("denominator")])
        .pipe(add_date_parts).with_columns([pl.lit("Tỷ lệ kết nối đúng giờ").alias("kpi_name"),pl.lit(10).alias("kpi_id")])
        .rename({"Mã đơn vị vận chuyển":"unit"}).join(lb,on="unit",how="left").select(AGG_COLS).filter(pl.col("branch").is_not_null()))

def agg_hqx_mode(df, lb, mode):
    cfg = HQX_CONFIG[mode]
    fexpr = pl.col("Loại hành trình").is_in(cfg["route_type"])
    if cfg["direction"]: fexpr = fexpr & (pl.col("Chiều")==cfg["direction"])
    return (df.filter(fexpr)
        .with_columns([pl.col(cfg["num"]).cast(pl.Float64,strict=False),pl.col(cfg["den"]).cast(pl.Float64,strict=False)])
        .group_by(["date","unit"]).agg([pl.col(cfg["num"]).sum().alias("numerator"),pl.col(cfg["den"]).sum().alias("denominator")])
        .pipe(add_date_parts).with_columns([pl.lit(mode).alias("kpi_name"),pl.lit(cfg["kpi_id"]).cast(pl.Int64).alias("kpi_id")])
        .join(lb,on="unit",how="left").select(AGG_COLS).filter(pl.col("branch").is_not_null()))


# ═══════════════════════════════════════════════════════════════════════════════
# UI — 4 TABS
# ═══════════════════════════════════════════════════════════════════════════════

st.title("🚚 KPI Pipeline")

tab_cfg, tab_run, tab_flow, tab_result = st.tabs([
    "⚙️  Cấu hình", "▶  Xử lý", "📋  Mô tả luồng", "📊  Kết quả"
])


# ══════════════════════════════════════════════════════
# TAB 1 — CẤU HÌNH
# ══════════════════════════════════════════════════════
with tab_cfg:
    st.markdown("### Cấu hình đường dẫn & chọn file")
    st.caption("Nhập đường dẫn thư mục — app sẽ quét và liệt kê file để chọn. File mới nhất được chọn mặc định.")

    # ── Row 1: thư mục gốc ──────────────────────────────────────────────────
    st.markdown('<div class="sec-header">📁 Thư mục gốc</div>', unsafe_allow_html=True)
    dc1, dc2, dc3, dc4 = st.columns(4)
    with dc1:
        raw_dir = st.text_input("Raw", value=r"D:\Project - KPI Monitor\2. Raw",           key="raw_dir")
    with dc2:
        clean_dir = st.text_input("Clean", value=r"D:\Project - KPI Monitor\3. Clean",     key="clean_dir")
    with dc3:
        agg_dir = st.text_input("Aggregate", value=r"D:\Project - KPI Monitor\5. Aggregate", key="agg_dir")
    with dc4:
        lk_dir = st.text_input("Lookup", value=r"D:\Project - KPI Monitor\1. Resources\Lookup", key="lk_dir")

    # ── Resolve paths ────────────────────────────────────────────────────────
    RAW_P  = Path(st.session_state.raw_dir)
    LK_P   = Path(st.session_state.lk_dir)
    # LK_MAPPINGROUT = Path(st.session_state)

    # ── Row 2: thư mục con raw ───────────────────────────────────────────────
    st.markdown('<div class="sec-header">📂 Thư mục con (Raw)</div>', unsafe_allow_html=True)
    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    with sc1:
        sub_xs  = st.text_input("Xuất Sạch", value=r"XuatSach\T7", key="sub_xs")
    with sc2:
        sub_cn  = st.text_input("Chờ Nhập",  value=r"ChoNhap",     key="sub_cn")
    with sc3:
        sub_hqx = st.text_input("HQX",       value=r"HieuQuaXe",   key="sub_hqx")
    with sc4:
        sub_kd  = st.text_input("KNDD",      value=r"KNDD",         key="sub_kd")
    with sc5:
        sub_15s = st.text_input("12.5s",     value=r"15s\T7",          key="sub_15s")

    st.markdown("---")

    # ── File selectors — 1 block per KPI ─────────────────────────────────────
    st.markdown('<div class="sec-header">📄 Chọn file Raw</div>', unsafe_allow_html=True)

    # XuatSach — 2 files (RaiDich + KetNoi)
    xs_dir = RAW_P / st.session_state.sub_xs
    with st.expander("📦 Xuất Sạch — chọn 2 file", expanded=True):
        run_xs = st.checkbox("Bật Xuất Sạch", value=True, key="run_xs")
        if run_xs:
            xsc1, xsc2 = st.columns(2)
            with xsc1:
                _rd = file_dropdown(
                    "RaiDich file", xs_dir, "sel_rd",
                    filter_fn=lambda f: "raidich" in f.name.lower()
                )
                if _rd:
                    st.caption(f"📅 {datetime.fromtimestamp(_rd.stat().st_mtime).strftime('%d/%m/%Y %H:%M')}")
            with xsc2:
                _kn = file_dropdown(
                    "KetNoi file", xs_dir, "sel_kn",
                    filter_fn=lambda f: "ketnoi" in f.name.lower()
                )
                if _kn:
                    st.caption(f"📅 {datetime.fromtimestamp(_kn.stat().st_mtime).strftime('%d/%m/%Y %H:%M')}")

    # ChoNhap
    cn_dir = RAW_P / st.session_state.sub_cn
    with st.expander("⏱ Chờ Nhập — chọn file", expanded=True):
        run_cn = st.checkbox("Bật Chờ Nhập", value=True, key="run_cn")
        if run_cn:
            _cn = file_dropdown("ChoNhap file", cn_dir, "sel_cn")
            if _cn:
                st.caption(f"📅 {datetime.fromtimestamp(_cn.stat().st_mtime).strftime('%d/%m/%Y %H:%M')}")

    # KNDD
    kd_dir = RAW_P / st.session_state.sub_kd
    with st.expander("🔗 KNDD — chọn file", expanded=True):
        run_kd = st.checkbox("Bật KNDD", value=True, key="run_kd")
        if run_kd:
            _kd = file_dropdown("KNDD file", kd_dir, "sel_kd", exts=(".xlsx",".xlsm",".csv"))
            if _kd:
                st.caption(f"📅 {datetime.fromtimestamp(_kd.stat().st_mtime).strftime('%d/%m/%Y %H:%M')}")

    # HQX
    hqx_dir = RAW_P / st.session_state.sub_hqx
    with st.expander("🚛 HQX / HQKN — chọn file", expanded=True):
        run_hqx = st.checkbox("Bật HQX", value=True, key="run_hqx")
        if run_hqx:
            _hx = file_dropdown("HQX file", hqx_dir, "sel_hx", exts=(".xlsx",".xlsm",".csv"))
            if _hx:
                st.caption(f"📅 {datetime.fromtimestamp(_hx.stat().st_mtime).strftime('%d/%m/%Y %H:%M')}")

    # 12.5s — đọc toàn bộ thư mục (nhiều file *_ddmmyyyy.xlsx)
    s15_dir = RAW_P / st.session_state.sub_15s
    with st.expander("📥 Tỷ lệ nhập đúng tải kiện 12.5s — chọn thư mục", expanded=True):
        run_15s = st.checkbox("Bật 12.5s", value=True, key="run_15s")
        if run_15s:
            files_15s = scan_folder(s15_dir, exts=(".xlsx",))
            if files_15s:
                st.caption(f"📁 {s15_dir}  —  {len(files_15s)} file (mỗi ngày 1 file dạng `*_ddmmyyyy.xlsx`)")
                with st.expander("Xem danh sách file", expanded=False):
                    for f in files_15s:
                        st.caption(f"• {f.name}  ({datetime.fromtimestamp(f.stat().st_mtime).strftime('%d/%m/%Y %H:%M')})")
            else:
                st.warning(f"Không tìm thấy file .xlsx nào trong: {s15_dir}", icon="⚠️")

    # ── Lookup files ─────────────────────────────────────────────────────────
    st.markdown('<div class="sec-header">📄 Chọn file Lookup</div>', unsafe_allow_html=True)
    lkc1, lkc2, lkc3, lkc4 = st.columns(4)
    with lkc1:
        _lk_mr  = file_dropdown("MappingRoute",  LK_P, "sel_lk_mr",  exts=(".xlsx",".xlsm"))
    with lkc2:
        _lk_ht  = file_dropdown("HanhTrinhHQX",  LK_P, "sel_lk_ht",  exts=(".xlsx",".xlsm"))
    with lkc3:
        _lk_dvc = file_dropdown("DanhSachDVC",   LK_P, "sel_lk_dvc", exts=(".xlsx",".xlsm"))
    with lkc4:
        _lk_du  = file_dropdown("dim_unit",       LK_P, "sel_lk_du",  exts=(".csv",".xlsx"))

    # ── Tham số tháng ────────────────────────────────────────────────────────
    st.markdown('<div class="sec-header">🗓 Tham số tháng</div>', unsafe_allow_html=True)
    pm1, pm2, _ = st.columns([1, 1, 4])
    with pm1:
        proc_month = st.text_input("Nhãn tháng", value="T7",   key="proc_month")
    with pm2:
        proc_year  = st.text_input("Năm",         value="2026", key="proc_year")

    # ── Path status ──────────────────────────────────────────────────────────
    st.markdown('<div class="sec-header">Trạng thái đường dẫn</div>', unsafe_allow_html=True)
    pc1, pc2, pc3, pc4 = st.columns(4)
    for col, label, p in [
        (pc1, "Raw", RAW_P),
        (pc2, "Clean", Path(st.session_state.clean_dir)),
        (pc3, "Agg",   Path(st.session_state.agg_dir)),
        (pc4, "Lookup", LK_P),
    ]:
        with col:
            ok = p.exists()
            st.markdown(
                f"**{label}**<br>{badge('✓ Có', 'ok') if ok else badge('✗ Không tìm thấy', 'err')}",
                unsafe_allow_html=True
            )
            st.caption(str(p))


# ══════════════════════════════════════════════════════
# TAB 2 — XỬ LÝ
# ══════════════════════════════════════════════════════
with tab_run:
    st.markdown("### Xử lý pipeline")

    # ── Status board ──
    kpi_keys = ["xuatsach","chonhap","kndd","hqx","15s"]
    kpi_labels = {"xuatsach":"Xuất sạch","chonhap":"Chờ nhập","kndd":"KNDD","hqx":"HQX/HQKN","15s":"12.5s"}
    status_cols = st.columns(6)
    for i, k in enumerate(kpi_keys):
        s = st.session_state.run_status.get(k, "pending")
        bk = {"ok":"ok","error":"err","skip":"wait"}.get(s, "wait")
        label = {"ok":"✓ Xong","error":"✗ Lỗi","skip":"— Bỏ qua","pending":"· Chờ"}.get(s, "· Chờ")
        status_cols[i].markdown(
            f"**{kpi_labels[k]}**<br>{badge(label, bk)}",
            unsafe_allow_html=True
        )
    agg_s = st.session_state.run_status.get("agg","pending")
    status_cols[5].markdown(
        f"**Aggregate**<br>{badge({'ok':'✓ Xong','error':'✗ Lỗi','pending':'· Chờ'}.get(agg_s,'· Chờ'), {'ok':'ok','error':'err'}.get(agg_s,'wait'))}",
        unsafe_allow_html=True
    )

    st.markdown("---")

    run_col, _ = st.columns([1, 3])
    with run_col:
        run_all = st.button("▶  Chạy tất cả", width = 'stretch', key="btn_run_all")

    if run_all:
        st.session_state.logs = []
        st.session_state.df_clean = {}
        st.session_state.df_agg = {}
        st.session_state.run_status = {}

        RAW     = Path(st.session_state.raw_dir)
        LOOKUP  = Path(st.session_state.lk_dir)
        CLEAN   = Path(st.session_state.clean_dir)
        AGG_OUT = Path(st.session_state.agg_dir)

        # Đọc file đã chọn từ config tab (sel_* keys)
        def sel(key, base: Path = None):
            v = st.session_state.get(key)
            if not v:
                return None
            p = (base / v) if base else Path(v)
            return p if p.exists() else None

        lk_mr  = sel("sel_lk_mr",  LOOKUP)
        lk_ht  = sel("sel_lk_ht",  LOOKUP)
        lk_dvc = sel("sel_lk_dvc", LOOKUP)
        lk_du  = sel("sel_lk_du",  LOOKUP)

        prog = st.progress(0, text="Bắt đầu...")
        steps = sum([st.session_state.get("run_xs", True),
                     st.session_state.get("run_cn", True),
                     st.session_state.get("run_kd", True),
                     st.session_state.get("run_hqx", True),
                     st.session_state.get("run_15s", True)]) + 1
        done = 0

        # ── XuatSach ──
        if st.session_state.get("run_xs", True):
            prog.progress(done/steps, text="Đang xử lý Xuất Sạch...")
            try:
                month_label = st.session_state.get("proc_month", "T7")

                xs_dir = RAW / st.session_state.get("sub_xs", rf"XuatSach\{month_label}")
                rd_path = sel("sel_rd", xs_dir)
                kn_path = sel("sel_kn", xs_dir)

                if not rd_path or not kn_path or not lk_mr:
                    raise FileNotFoundError("Chưa chọn đủ file: RaiDich / KetNoi / MappingRoute")

                log(f"XuatSach clean latest/input: {rd_path.name}, {kn_path.name}")

                df, rep_date = clean_xuatsach(rd_path, kn_path, lk_mr)

                st.session_state.df_clean["xuatsach"] = df

                out = CLEAN / "XuatSach" / month_label
                out.mkdir(parents=True, exist_ok=True)

                # Nếu chạy lại cùng ngày thì replace file clean cũ
                clean_out_path = out / f"XuatSachHUB_{rep_date.strftime('%d%m%Y')}.csv"
                df.write_csv(clean_out_path)

                st.session_state.run_status["xuatsach"] = "ok"

                log(f"XuatSach CLEAN OK — {df.height:,} rows, date={rep_date}, output={clean_out_path}")

            except Exception as e:
                st.session_state.run_status["xuatsach"] = "error"
                log(f"XuatSach ERROR: {e}", "ERROR")

            done += 1
        else:
            st.session_state.run_status["xuatsach"] = "skip"

        # ── ChoNhap ──
        if st.session_state.get("run_cn", True):
            prog.progress(done/steps, text="Đang xử lý Chờ Nhập...")
            try:
                cn_dir  = RAW / st.session_state.get("sub_cn", "ChoNhap")
                cn_path = sel("sel_cn", cn_dir)
                if not cn_path or not lk_ht:
                    raise FileNotFoundError("Chưa chọn đủ file: ChoNhap / HanhTrinhHQX")
                log(f"ChoNhap: {cn_path.name}")
                df = clean_chonhap(cn_path, lk_ht)
                st.session_state.df_clean["chonhap"] = df
                out = CLEAN / "ChoNhap"; out.mkdir(parents=True, exist_ok=True)
                df.write_csv(out / f"ChoNhap_{st.session_state.get('proc_month','T6')}.csv")
                st.session_state.run_status["chonhap"] = "ok"
                log(f"ChoNhap OK — {df.height:,} rows")
            except Exception as e:
                st.session_state.run_status["chonhap"] = "error"
                log(f"ChoNhap ERROR: {e}", "ERROR")
            done += 1
        else:
            st.session_state.run_status["chonhap"] = "skip"

        # ── KNDD ──
        if st.session_state.get("run_kd", True):
            prog.progress(done/steps, text="Đang xử lý KNDD...")
            try:
                kd_dir  = RAW / st.session_state.get("sub_kd", "KNDD")
                kd_path = sel("sel_kd", kd_dir)
                if not kd_path or not lk_ht or not lk_dvc:
                    raise FileNotFoundError("Chưa chọn đủ file: KNDD / HanhTrinhHQX / DanhSachDVC")
                log(f"KNDD: {kd_path.name}")
                df = clean_kndd(kd_path, lk_ht, lk_dvc)
                st.session_state.df_clean["kndd"] = df
                out = CLEAN / "KNDD"; out.mkdir(parents=True, exist_ok=True)
                df.write_csv(out / f"KNDD_{st.session_state.get('proc_month','T6')}.csv")
                st.session_state.run_status["kndd"] = "ok"
                log(f"KNDD OK — {df.height:,} rows")
            except Exception as e:
                st.session_state.run_status["kndd"] = "error"
                log(f"KNDD ERROR: {e}", "ERROR")
            done += 1
        else:
            st.session_state.run_status["kndd"] = "skip"

        # ── HQX ──
        if st.session_state.get("run_hqx", True):
            prog.progress(done/steps, text="Đang xử lý HQX...")
            try:
                hqx_dir = RAW / st.session_state.get("sub_hqx", "HieuQuaXe")
                hx_path = sel("sel_hx", hqx_dir)
                if not hx_path or not lk_ht:
                    raise FileNotFoundError("Chưa chọn đủ file: HQX / HanhTrinhHQX")
                log(f"HQX: {hx_path.name}")
                df = clean_hqx(hx_path, lk_ht)
                st.session_state.df_clean["hqx"] = df
                out = CLEAN / "HQX"; out.mkdir(parents=True, exist_ok=True)
                df.write_csv(out / f"HQX_{st.session_state.get('proc_month','T6')}.csv")
                st.session_state.run_status["hqx"] = "ok"
                log(f"HQX OK — {df.height:,} rows")
            except Exception as e:
                st.session_state.run_status["hqx"] = "error"
                log(f"HQX ERROR: {e}", "ERROR")
            done += 1
        else:
            st.session_state.run_status["hqx"] = "skip"

        # ── 12.5s ──
        if st.session_state.get("run_15s", True):
            prog.progress(done/steps, text="Đang xử lý 12.5s...")
            try:
                s15_dir = RAW / st.session_state.get("sub_15s", "15s")
                if not s15_dir.exists():
                    raise FileNotFoundError(f"Không tìm thấy thư mục: {s15_dir}")
                log(f"12.5s: đọc thư mục {s15_dir}")
                df = clean_15s(s15_dir)
                st.session_state.df_clean["15s"] = df
                out = CLEAN / "15s"; out.mkdir(parents=True, exist_ok=True)
                df.write_csv(out / f"15s_{st.session_state.get('proc_month','T6')}.csv")
                st.session_state.run_status["15s"] = "ok"
                log(f"12.5s OK — {df.height:,} rows")
            except Exception as e:
                st.session_state.run_status["15s"] = "error"
                log(f"12.5s ERROR: {e}", "ERROR")
            done += 1
        else:
            st.session_state.run_status["15s"] = "skip"

        # ── Aggregate ──
        prog.progress(done/steps, text="Đang Aggregate...")
        try:
            if not lk_du:
                raise FileNotFoundError("Chưa chọn file dim_unit")
            lb = pl.read_csv(lk_du).select(["unit","branch"])
            frames = []

            month_label = st.session_state.get("proc_month", "T6")

            xs_clean_dir = CLEAN / "XuatSach" / month_label

            if xs_clean_dir.exists():
                df_xs_all = read_clean_folder(xs_clean_dir, exts=(".csv", ".xlsx", ".xlsm"))

                frames.append(
                    agg_xuatsach(
                        df_xs_all.with_columns(pl.col("date").cast(pl.Date)),
                        lb
                    )
                )

                log(
                    f"Agg XuatSach OK — đọc toàn bộ clean folder: "
                    f"{xs_clean_dir}, rows={df_xs_all.height:,}"
                )
            else:
                log(f"Agg XuatSach SKIP — chưa có folder clean: {xs_clean_dir}", "WARN")

            # if "xuatsach" in st.session_state.df_clean:
            #     frames.append(agg_xuatsach(st.session_state.df_clean["xuatsach"].with_columns(pl.col("date").cast(pl.Date)), lb))
            #     log("Agg XuatSach OK")
            if "chonhap" in st.session_state.df_clean:
                frames.append(agg_chonhap(st.session_state.df_clean["chonhap"].with_columns(pl.col("date").cast(pl.Date)), lb))
                log("Agg ChoNhap OK")
            if "kndd" in st.session_state.df_clean:
                frames.append(agg_kndd(st.session_state.df_clean["kndd"].with_columns(pl.col("date").cast(pl.Date)), lb))
                log("Agg KNDD OK")
            if "hqx" in st.session_state.df_clean:
                df_h = st.session_state.df_clean["hqx"].with_columns(pl.col("date").cast(pl.Date))
                for mode in HQX_CONFIG:
                    try:
                        frames.append(agg_hqx_mode(df_h, lb, mode))
                        log(f"Agg {mode} OK")
                    except Exception as ex:
                        log(f"Agg {mode} SKIP: {ex}", "WARN")
            if "15s" in st.session_state.df_clean:
                try:
                    frames.append(agg_15s(st.session_state.df_clean["15s"].with_columns(pl.col("date").cast(pl.Date)), lb))
                    log("Agg 12.5s OK")
                except Exception as ex:
                    log(f"Agg 12.5s SKIP: {ex}", "WARN")
            if frames:
                df_final = pl.concat(frames, how="vertical_relaxed")
                st.session_state.df_agg = df_final
                AGG_OUT.mkdir(parents=True, exist_ok=True)
                month_label = st.session_state.get("proc_month", "T6")
                df_final.write_csv(AGG_OUT / f"Actual_KPI_{month_label}.csv")
                st.session_state.run_status["agg"] = "ok"
                log(f"Aggregate DONE — {df_final.height:,} rows, {df_final['kpi_name'].n_unique()} KPIs")
            else:
                log("Aggregate: không có frame nào", "WARN")
                st.session_state.run_status["agg"] = "error"
        except Exception as e:
            st.session_state.run_status["agg"] = "error"
            log(f"Aggregate ERROR: {e}", "ERROR")
        
        prog.progress(1.0, text="Hoàn thành!")
        st.rerun()

    render_log()


# ══════════════════════════════════════════════════════
# TAB 3 — MÔ TẢ LUỒNG
# ══════════════════════════════════════════════════════
with tab_flow:
    st.markdown("### Mô tả luồng xử lý")

    flows = [
        {
            "kpi": "📦 Xuất Sạch",
            "desc": "Tính tỷ lệ đơn hàng xuất đúng hẹn theo đơn vị khai thác.",
            "steps": [
                ("Input", ["XuatsachHUBRaiDich_*.csv", "XuatsachHUBKetNoi_*.csv"]),
                ("Lookup", ["MappingRoute.xlsx (sheet: 2_route_type)"]),
                ("Xử lý", ["Filter: don_hoan=0, Result_p ∈ {Đúng, Sai hẹn}", "Parse datetime các cột tg_*", "Tính timedelta → giờ", "Join lookup province → loai_ket_noi", "Phân loại nguyen_nhan: Đúng / Xuất trễ / Trượt ca"]),
                ("Output", ["XuatSachHUB_{ddmmyyyy}.csv"]),
            ],
            "agg": "Nhóm theo date × don_vi_khaithac → count(Đúng) / count(all)",
            "kpi_id": "kpi_id=3",
        },
        {
            "kpi": "⏱ Chờ Nhập",
            "desc": "Đo thời gian xe chờ nhập tại bưu cục (tg_nhap_tai_kien_dau_tien − tg_xe_check_in).",
            "steps": [
                ("Input", ["BC_tổng_hợp_chuyến_xe_nhập_xuất_đúng_giờ_TTKT_lũy_kế_tháng_*.csv"]),
                ("Lookup", ["HanhTrinhHQX.xlsx (sheet: lookup_route)"]),
                ("Xử lý", ["Parse datetime, loại tuyến PH, lọc tong_tai_kien > 10", "Tính tg_chonhap = tg_nhap - tg_check_in (phút)", "Join lookup_route → Loại hành trình"]),
                ("Output", ["ChoNhap_T{n}.csv"]),
            ],
            "agg": "Nhóm theo date × don_vi → sum(tg_chonhap) / count(chuyen_xe)",
            "kpi_id": "kpi_id=4",
        },
        {
            "kpi": "🔗 Kết Nối Đúng Giờ (KNDD)",
            "desc": "Tỷ lệ chuyến xe đến điểm kết nối đúng giờ (chênh lệch ≤ 15 phút).",
            "steps": [
                ("Input", ["bcketnoidunggio_*.xlsx"]),
                ("Lookup", ["HanhTrinhHQX.xlsx (sheet: lookup_route)", "DanhSachDVC.xlsx"]),
                ("Xử lý", ["Filter: Thời gian checkin không null", "Parse %H:%M %d-%m-%Y", "Tính Chênh lệch = checkin − đến quy định", "Đánh giá: ≤15 phút → Đúng, ngược lại Sai", "Join DVC → branch"]),
                ("Output", ["KNDD_T{n}.csv"]),
            ],
            "agg": "Nhóm theo date × Mã_DVC → count(Đúng) / count(all)",
            "kpi_id": "kpi_id=10",
        },
        {
            "kpi": "🚛 Hiệu Quả Xe / Kết Nối (HQX)",
            "desc": "7 KPI phái sinh từ 1 file HieuQuaXe, phân tách theo loại hành trình & chiều.",
            "steps": [
                ("Input", ["Bao_cao_chi_tiet_hieu_qua_xe_*.xlsx"]),
                ("Lookup", ["HanhTrinhHQX.xlsx (sheet: lookup_route)"]),
                ("Xử lý", ["Tách Nội tỉnh/Nội thành (km<1000) & Nội miền/Liên miền (km<5000)", "Loại chuyến ảo (TG kết thúc − TG khởi hành < 10 phút)", "Loại chuyến hàng 0 kg", "Join lookup → branch, unit"]),
                ("Output", ["HQX_T{n}.csv"]),
            ],
            "agg": "7 mode: HQX nội tỉnh đi/về, HQKN nội tỉnh, HQX nội miền đi/về, HQKN nội miền, HQX liên miền → sum(kg)/sum(tải) hoặc sum(kg)/sum(km)",
            "kpi_id": "kpi_id: 7,8,9,15,16,17,18",
        },
        {
            "kpi": "📥 Tỷ lệ nhập đúng tải kiện 12.5s",
            "desc": "Tỷ lệ tải kiện nhập đúng giờ tại các điểm 12.5s, tổng hợp theo đơn vị mỗi ngày.",
            "steps": [
                ("Input", ["Thư mục 15s/: 1 file .xlsx mỗi ngày, tên dạng *_ddmmyyyy.xlsx"]),
                ("Lookup", ["dim_unit.csv (unit → branch)"]),
                ("Xử lý", ["Đọc từng file, bỏ qua file tạm (~$)", "Parse ngày từ tên file", "Bỏ 3 dòng header, lấy cột Đơn vị / Số tải kiện nhập / Tỷ lệ nhập đúng giờ", "Concat toàn bộ file trong thư mục"]),
                ("Output", ["Clean/15s/15s_{month}.csv"]),
            ],
            "agg": "numerator = value% × denominator / 100, nhóm theo date × unit → join branch",
            "kpi_id": "kpi_id=5",
        },
    ]

    for flow in flows:
        with st.expander(f"{flow['kpi']}  —  {flow['desc']}", expanded=False):
            for step_name, items in flow["steps"]:
                color = {"Input":"#eff6ff","Lookup":"#f0fdf4","Xử lý":"#fafafa","Output":"#faf5ff"}.get(step_name,"#fff")
                border = {"Input":"#bfdbfe","Lookup":"#bbf7d0","Xử lý":"#e5e7eb","Output":"#e9d5ff"}.get(step_name,"#ddd")
                text_c = {"Input":"#1e40af","Lookup":"#166534","Xử lý":"#374151","Output":"#6b21a8"}.get(step_name,"#000")
                items_html = "".join(f"<li style='margin:2px 0'>{i}</li>" for i in items)
                st.markdown(f"""
                <div style="border:1px solid {border}; background:{color}; border-radius:8px; padding:10px 14px; margin:6px 0">
                  <div style="font-size:11px;font-weight:700;color:{text_c};text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">{step_name}</div>
                  <ul style="margin:0;padding-left:18px;color:#374151;font-size:13px">{items_html}</ul>
                </div>""", unsafe_allow_html=True)

            st.markdown(f"""
            <div style="background:#fefce8;border:1px solid #fde68a;border-radius:6px;padding:8px 14px;margin-top:8px;font-size:13px">
              <span style="font-weight:700;color:#92400e">Aggregate:</span> {flow['agg']}<br>
              <span style="font-size:11px;color:#9ca3af">{flow['kpi_id']}</span>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### Cấu trúc thư mục")
    st.code("""
Project - KPI Monitor/
├── 1. Resources/Lookup/
│   ├── MappingRoute.xlsx        ← route type lookup cho XuatSach
│   ├── HanhTrinhHQX.xlsx        ← lookup_route dùng chung ChoNhap/KNDD/HQX
│   ├── DanhSachDVC.xlsx         ← mã đơn vị vận chuyển → branch
│   └── dim_unit.csv             ← unit → branch cho aggregate
├── 2. Raw/
│   ├── XuatSach/T6/
│   ├── ChoNhap/
│   ├── HieuQuaXe/
│   └── KNDD/
├── 3. Clean/
│   ├── XuatSach/T6/
│   ├── ChoNhap/
│   ├── HQX/
│   └── KNDD/
└── 5. Aggregate/
    └── Actual_KPI_T6.csv        ← output cuối cùng
    """, language="")

    st.markdown("### Schema output Aggregate")
    schema_df = pl.DataFrame({
        "Cột":      ["kpi_name","kpi_id","branch","unit","date","year","month","day","numerator","denominator"],
        "Kiểu":     ["Utf8","Int64","Utf8","Utf8","Date","Int32","Int8","Int8","Float64","Float64"],
        "Mô tả":    [
            "Tên KPI","ID KPI","Chi nhánh / MegaHUB","Mã đơn vị",
            "Ngày báo cáo","Năm","Tháng","Ngày",
            "Tử số (đúng hẹn / kg hàng / phút chờ)","Mẫu số (tổng đơn / tải / chuyến)",
        ],
    })
    st.dataframe(schema_df.to_pandas(), width='stretch', hide_index=True)


# ══════════════════════════════════════════════════════
# TAB 4 — KẾT QUẢ
# ══════════════════════════════════════════════════════
with tab_result:
    st.markdown("### Kết quả sau khi chạy")

    if not st.session_state.run_status:
        st.info("Chưa chạy pipeline. Sang tab **Xử lý** và nhấn Chạy tất cả.")
    else:
        # ── Summary metrics ──
        m_cols = st.columns(6)
        for i, k in enumerate(kpi_keys):
            s = st.session_state.run_status.get(k,"pending")
            rows = st.session_state.df_clean.get(k)
            val  = f"{rows.height:,}" if rows is not None else "—"
            m_cols[i].metric(kpi_labels[k], val, delta={"ok":"✓","error":"✗","skip":"—"}.get(s,""))
        agg_df = st.session_state.df_agg
        agg_rows = agg_df.height if isinstance(agg_df, pl.DataFrame) else 0
        m_cols[5].metric("Aggregate rows", f"{agg_rows:,}")

        st.markdown("---")

        # ── Per-KPI preview ──
        for k in kpi_keys:
            df = st.session_state.df_clean.get(k)
            if df is None: continue
            with st.expander(f"**{kpi_labels[k]}** — {df.height:,} rows"):
                st.dataframe(df.head(100).to_pandas(), width='stretch')
                buf = io.BytesIO(); df.write_csv(buf)
                st.download_button(
                    f"⬇ Download {k}.csv", buf.getvalue(),
                    f"{k}_{st.session_state.proc_month}.csv", "text/csv", key=f"dl_{k}"
                )

        # ── Aggregate result ──
        if isinstance(agg_df, pl.DataFrame) and agg_df.height > 0:
            st.markdown("#### Aggregate — breakdown theo KPI")
            summary = agg_df.group_by("kpi_name").agg([
                pl.len().alias("rows"),
                pl.col("unit").n_unique().alias("units"),
                pl.col("date").n_unique().alias("ngày"),
            ]).sort("kpi_name")
            st.dataframe(summary.to_pandas(), width = 'stretch', hide_index=True)

            with st.expander("Preview Aggregate (100 rows)"):
                st.dataframe(agg_df.head(100).to_pandas(), width= 'stretch')

            buf = io.BytesIO(); agg_df.write_csv(buf)
            st.download_button(
                "⬇ Download Actual_KPI.csv", buf.getvalue(),
                f"Actual_KPI_{st.session_state.proc_month}.csv", "text/csv",
                width='stretch', key="dl_agg"
            )