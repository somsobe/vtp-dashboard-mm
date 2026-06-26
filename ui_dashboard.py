import streamlit as st
import polars as pl
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path
import os

# ─── CONFIG ───────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Dashboard KPI Mạng lưới",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# KPI metadata: id → (tên hiển thị, direction, unit, target fallback nếu không có trong file)
KPI_META = {
    3:  {"name": "Tỷ lệ xuất sạch",        "direction": "gte", "unit": "%",    "fmt": ".2%"},
    4:  {"name": "Thời gian chờ nhập",      "direction": "lte", "unit": "phút", "fmt": ".2f"},
    7:  {"name": "Hiệu quả kết nối",        "direction": "gte", "unit": "kg/km",    "fmt": ".2f"},
    8:  {"name": "Hiệu quả xe (đi)",        "direction": "gte", "unit": "%",    "fmt": ".2%"},
    9:  {"name": "Hiệu quả xe (về)",        "direction": "gte", "unit": "%",    "fmt": ".2%"},
    10: {"name": "Tỷ lệ kết nối đúng đủ",  "direction": "gte", "unit": "%",    "fmt": ".2%"},
}

# KPIs trả về tỷ lệ (0-1) hay giá trị tuyệt đối
KPI_IS_RATIO = {3: True, 4: False, 7: False, 8: True, 9: True, 10: True}

# DATA PATHS
BASE_DIR = Path(__file__).resolve().parent

AGG_DIR = BASE_DIR / "5. Aggregate"
RESOURCE_DIR = BASE_DIR / "1. Resources"

PATH_KPI_TARGET = AGG_DIR / "KPI_Target.csv"

# ─── LOAD DATA ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_data():
    inbound_files = sorted(AGG_DIR.glob("Inbound_T*.csv"))
    actual_files = sorted(AGG_DIR.glob("Actual_KPI_T*.csv"))

    inbound = (
        pl.concat([pl.read_csv(f) for f in inbound_files])
        .with_columns(pl.date(pl.col("year"), pl.col("month"), pl.col("day")).alias("date"))
    )

    actual = (
        pl.concat([pl.read_csv(f) for f in actual_files])
        .with_columns(pl.date(pl.col("year"), pl.col("month"), pl.col("day")).alias("date"))
    )

    target = pl.read_csv(PATH_KPI_TARGET)

    return inbound, actual, target

inbound, actual, target = load_data()

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def fmt_value(val: float, kpi_id: int) -> str:
    if val is None or val != val:
        return "—"
    meta = KPI_META[kpi_id]
    if KPI_IS_RATIO.get(kpi_id) and kpi_id != [4,7]:
        return f"{val*100:.2f}%"
    elif kpi_id == 4:
        return f"{val:.2f} phút"
    elif kpi_id == 7:
        return f"{val:.2f} kg/km"
    return f"{val:.2f}"

def calc_cumulative(df: pl.DataFrame) -> dict:
    """Tính lũy kế đúng: sum(num)/sum(den) theo từng kpi_id."""
    result = {}
    for kpi_id in df["kpi_id"].unique().to_list():
        sub = df.filter(pl.col("kpi_id") == kpi_id)
        total_num = sub["numerator"].sum()
        total_den = sub["denominator"].sum()
        result[kpi_id] = total_num / total_den if total_den else None
    return result

def get_status(value: float, target_val: float, direction: str) -> tuple[str, str]:
    """Trả về (label, color): Đạt / Cận ngưỡng / Không đạt."""
    if value is None or target_val is None:
        return "—", "gray"
    threshold = target_val * 0.02
    delta = value - target_val
    if direction == "gte":
        if delta >= 0:                    return "Đạt", "#1D9E75"
        elif abs(delta) <= threshold:     return "Cận ngưỡng", "#BA7517"
        else:                             return "Không đạt", "#A32D2D"
    else:
        if delta <= 0:                    return "Đạt", "#1D9E75"
        elif abs(delta) <= threshold:     return "Cận ngưỡng", "#BA7517"
        else:                             return "Không đạt", "#A32D2D"

def get_target_for_unit(kpi_id: int, unit: str, month: int, year: int) -> float | None:
    """Lấy target từ KPI_Target, trả về None nếu không có."""
    row = target.filter(
        (pl.col("kpi_id") == kpi_id) &
        (pl.col("unit_id") == unit) &
        (pl.col("month") == month) &
        (pl.col("year") == year)
    )
    if len(row) == 0:
        return None
    return row["target_value"][0]

def get_network_target(kpi_id: int, month: int, year: int) -> float | None:
    """Target trung bình mạng lưới cho KPI."""
    rows = target.filter(
        (pl.col("kpi_id") == kpi_id) &
        (pl.col("month") == month) &
        (pl.col("year") == year)
    )
    if len(rows) == 0:
        return None
    return rows["target_value"].mean()

# ─── KPI CARD HELPERS ─────────────────────────────────────────────────────────
# Tách ra function để dễ maintain; màu chữ phụ dùng #bbb (sáng hơn #888 cũ),
# giá trị chính và số dùng #fff.

def kpi_card_network(name, display_val, tgt_display, delta_display, status_label, status_color, meta):
    delta_color = (
        "#1D9E75" if (delta_display and (
            (meta["direction"] == "gte" and "+" in delta_display) or
            (meta["direction"] == "lte" and "-" in delta_display)
        )) else ("#A32D2D" if delta_display else "#bbb")
    )
    return f"""
    <div style="background:var(--background-color,#1e1e2e);border:0.5px solid #444;border-radius:10px;padding:14px 16px;margin-bottom:10px;">
        <div style="font-size:12px;color:#bbb;margin-bottom:4px;">{name}</div>
        <div style="font-size:26px;font-weight:500;color:#fff;margin-bottom:4px;">{display_val}</div>
        <div style="font-size:12px;color:#bbb;">Mục tiêu: <span style="color:#e0e0e0">{tgt_display}</span></div>
        <div style="font-size:12px;color:#bbb;">Chênh lệch: <span style="color:{delta_color}">{delta_display if delta_display else '—'}</span></div>
        <div style="margin-top:8px;display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;background:{status_color}22;color:{status_color};border:0.5px solid {status_color}55">{status_label}</div>
    </div>
    """

def kpi_card_unit(name, display_val, tgt_display, net_display, delta_str, delta_color, status_label, status_color):
    return f"""
    <div style="background:var(--background-color,#1e1e2e);border:0.5px solid #444;border-radius:10px;padding:14px 16px;margin-bottom:10px;">
        <div style="font-size:12px;color:#bbb;margin-bottom:4px;">{name}</div>
        <div style="font-size:24px;font-weight:500;color:#fff;">{display_val}</div>
        <div style="font-size:11px;color:#bbb;margin-top:4px;">
            Mục tiêu: <span style="color:#e0e0e0">{tgt_display}</span>
            &nbsp;|&nbsp;
            Mạng lưới TB: <span style="color:#e0e0e0">{net_display}</span>
        </div>
        <div style="font-size:11px;margin-top:2px;color:#bbb;">Chênh lệch vs mục tiêu: <span style="color:{delta_color}">{delta_str if delta_str else '—'}</span></div>
        <div style="margin-top:8px;display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;background:{status_color}22;color:{status_color};border:0.5px solid {status_color}55">{status_label}</div>
    </div>
    """

# ─── SIDEBAR FILTERS ──────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📦 KPI Dashboard")
    st.markdown("---")

    # ── CONFIG PATHS EXPANDER ──────────────────────────────────────────────────
    # Liệt kê tất cả file đang được đọc để dễ trace nguồn dữ liệu
    with st.expander("📁 Đường dẫn dữ liệu", expanded=False):
        st.markdown(f"**Thư mục gốc**")
        st.code(str(BASE_DIR), language=None)

        st.markdown(f"**Aggregate** (`{AGG_DIR.name}/`)")
        inbound_files_listed = sorted(AGG_DIR.glob("Inbound_T*.csv"))
        actual_files_listed = sorted(AGG_DIR.glob("KPI_Actual_T*.csv"))
        for f in inbound_files_listed:
            st.caption(f"• `{f.name}`")
        for f in actual_files_listed:
            st.caption(f"• `{f.name}`")

        st.markdown(f"**Resource** (`{RESOURCE_DIR.name}/`)")
        st.caption(f"• `{PATH_KPI_TARGET.name}`")

    st.markdown("---")

    # Date range
    min_date = actual["date"].min()
    max_date = actual["date"].max()
    st.markdown("**Khoảng thời gian**")
    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("Từ", value=min_date, min_value=min_date, max_value=max_date, key="date_from")
    with col2:
        date_to = st.date_input("Đến", value=max_date, min_value=min_date, max_value=max_date, key="date_to")

    st.markdown("---")

    # Branch filter
    branches = sorted(actual["branch"].drop_nulls().unique().to_list())
    selected_branch = st.selectbox("Chi nhánh", ["Tất cả"] + branches)

    # Unit filter (depends on branch)
    if selected_branch != "Tất cả":
        units_avail = sorted(
            actual.filter(pl.col("branch") == selected_branch)["unit"].drop_nulls().unique().to_list()
        )
    else:
        units_avail = sorted(actual["unit"].drop_nulls().unique().to_list())
    selected_unit = st.selectbox("Đơn vị", ["Tất cả"] + units_avail)

    st.markdown("---")
    st.markdown(f"<small style='color:#aaa'>Dữ liệu: {min_date} → {max_date}</small>", unsafe_allow_html=True)

# ─── FILTER DATA ──────────────────────────────────────────────────────────────

import datetime
date_from = datetime.date(date_from.year, date_from.month, date_from.day) if not isinstance(date_from, datetime.date) else date_from
date_to = datetime.date(date_to.year, date_to.month, date_to.day) if not isinstance(date_to, datetime.date) else date_to

filtered = actual.filter(
    (pl.col("date") >= pl.lit(date_from)) &
    (pl.col("date") <= pl.lit(date_to))
)
if selected_branch != "Tất cả":
    filtered = filtered.filter(pl.col("branch") == selected_branch)
if selected_unit != "Tất cả":
    filtered = filtered.filter(pl.col("unit") == selected_unit)

filtered_inbound = inbound.filter(
    (pl.col("date") >= pl.lit(date_from)) &
    (pl.col("date") <= pl.lit(date_to))
)
if selected_branch != "Tất cả":
    filtered_inbound = filtered_inbound.filter(pl.col("branch") == selected_branch)

# Month/year từ filter (lấy tháng cuối trong range)
ref_month = date_to.month
ref_year = date_to.year

# ─── Page 1: TỔNG QUAN MẠNG LƯỚI ───────────────────────────────────────────

tab1, tab2 = st.tabs(["🌐 Tổng quan mạng lưới", "🏢 Chi tiết theo đơn vị"])

with tab1:
    st.markdown("### Tổng quan mạng lưới")

    # ── 1. TỔNG SẢN LƯỢNG NHẬP ──
    st.markdown("#### 1. Tổng quan sản lượng nhập")
    total_vol = filtered_inbound["previous_inbound_vol"].sum()
    total_ton = filtered_inbound["previous_inbound_ton"].sum()

    c1, c2 = st.columns(2)
    with c1:
        st.metric("Sản lượng nhập", f"{total_vol:,.0f}")
    with c2:
        st.metric("Trọng lượng nhập (tấn)", f"{total_ton:,.2f}")

    # Chart sản lượng theo ngày
    daily_vol = (
        filtered_inbound
        .group_by("date")
        .agg(pl.sum("previous_inbound_vol").alias("vol"))
        .sort("date")
    )
    fig_vol = go.Figure()
    fig_vol.add_trace(go.Bar(
        x=daily_vol["date"].to_list(),
        y=daily_vol["vol"].to_list(),
        marker_color="#378ADD",
        name="Sản lượng"
    ))
    fig_vol.update_layout(
        height=220, margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title=None, yaxis_title=None,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
        showlegend=False,
    )
    st.plotly_chart(fig_vol, use_container_width=True)

    st.markdown("---")

    # ── 2. 6 KPI CARDS LŨY KẾ ──
    st.markdown("#### 2. Các chỉ số lũy kế đến hiện tại")
    cumulative = calc_cumulative(filtered)
    kpi_cols = st.columns(3)

    for idx, (kpi_id, meta) in enumerate(KPI_META.items()):
        val = cumulative.get(kpi_id)
        tgt_val = get_network_target(kpi_id, ref_month, ref_year)

        if val is not None and KPI_IS_RATIO.get(kpi_id) and kpi_id != [4,7]:
            display_val = f"{val*100:.2f}%"
            tgt_display = f"≥ {tgt_val*100:.2f}%" if tgt_val and meta["direction"] == "gte" else (f"≤ {tgt_val*100:.2f}%" if tgt_val else "—")
            delta_display = f"{(val - tgt_val)*100:+.2f}%" if tgt_val else ""
        elif kpi_id == 4:
            display_val = f"{val:.2f} phút" if val else "—"
            tgt_display = f"≤ {tgt_val:.2f} phút" if tgt_val else "—"
            delta_display = f"{val - tgt_val:+.2f} phút" if tgt_val and val else ""
        elif kpi_id == 7:
            display_val = f"{val:.2f} kg/km" if val else "—"
            tgt_display = f"≤ {tgt_val:.2f} kg/km" if tgt_val else "—"
            delta_display = f"{val - tgt_val:+.2f} kg/km" if tgt_val and val else ""
        else:
            display_val = f"{val:.2f}" if val else "—"
            tgt_display = "—"
            delta_display = ""

        status_label, status_color = get_status(val, tgt_val, meta["direction"]) if val and tgt_val else ("—", "gray")

        col = kpi_cols[idx % 3]
        with col:
            st.markdown(
                kpi_card_network(meta["name"], display_val, tgt_display, delta_display, status_label, status_color, meta),
                unsafe_allow_html=True
            )

    st.markdown("---")

    # ── 3. LEADERBOARD ĐƠN VỊ DƯỚI KPI ──
    st.markdown("#### 3. Đơn vị dưới mục tiêu KPI")
    kpi_options = {meta["name"]: kpi_id for kpi_id, meta in KPI_META.items()}
    selected_kpi_name = st.selectbox("Chọn chỉ số", list(kpi_options.keys()), key="lb_kpi")
    selected_kpi_id = kpi_options[selected_kpi_name]
    meta = KPI_META[selected_kpi_id]

    kpi_sub = filtered.filter(pl.col("kpi_id") == selected_kpi_id)
    unit_cum = (
        kpi_sub
        .group_by("unit")
        .agg([
            pl.sum("numerator").alias("num"),
            pl.sum("denominator").alias("den"),
        ])
        .with_columns(
            (pl.col("num") / pl.col("den")).alias("val")
        )
        .sort("val", descending=(meta["direction"] == "gte"))
    )

    # Join target
    tgt_month = target.filter(
        (pl.col("kpi_id") == selected_kpi_id) &
        (pl.col("month") == ref_month) &
        (pl.col("year") == ref_year)
    ).select(["unit_id", "target_value"])

    unit_cum = unit_cum.join(
        tgt_month.rename({"unit_id": "unit"}),
        on="unit", how="left"
    )

    # Chỉ show đơn vị có target và dưới mục tiêu
    if meta["direction"] == "gte":
        under = unit_cum.filter(
            pl.col("target_value").is_not_null() &
            (pl.col("val") < pl.col("target_value"))
        ).sort("val")
    else:
        under = unit_cum.filter(
            pl.col("target_value").is_not_null() &
            (pl.col("val") > pl.col("target_value"))
        ).sort("val", descending=True)

    if len(under) == 0:
        st.success("Tất cả đơn vị có target đều đạt mục tiêu!")
    else:
        top20 = under.head(20)
        vals = top20["val"].to_list()
        tgts = top20["target_value"].to_list()
        units_lb = top20["unit"].to_list()

        if KPI_IS_RATIO.get(selected_kpi_id) and selected_kpi_id != 4:
            vals_disp = [v * 100 for v in vals]
            tgts_disp = [t * 100 for t in tgts]
            delta_disp = [v - t for v, t in zip(vals_disp, tgts_disp)]
            suffix = "%"
        else:
            vals_disp = vals
            tgts_disp = tgts
            delta_disp = [v - t for v, t in zip(vals_disp, tgts_disp)]
            suffix = " phút" if selected_kpi_id == 4 else ""

        colors = ["#A32D2D" if abs(d) > abs(t) * 0.02 else "#BA7517"
                  for d, t in zip(delta_disp, tgts_disp)]

        fig_lb = go.Figure()
        fig_lb.add_trace(go.Bar(
            x=delta_disp,
            y=units_lb,
            orientation="h",
            marker_color=colors,
            text=[f"{d:+.2f}{suffix}" for d in delta_disp],
            textposition="outside",
        ))
        fig_lb.update_layout(
            height=max(300, len(units_lb) * 28),
            margin=dict(l=0, r=60, t=10, b=0),
            xaxis_title=f"Chênh lệch vs mục tiêu ({suffix.strip()})",
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
        )
        st.plotly_chart(fig_lb, use_container_width=True)
        st.caption(f"Hiển thị {len(under)} đơn vị dưới mục tiêu (trong tổng {len(unit_cum)} đơn vị có dữ liệu)")

    st.markdown("---")

    # ── 4. TOP INBOUND ──
    st.markdown("#### 4. Top đơn vị theo sản lượng nhập (N-1)")
    top_inbound = (
        filtered_inbound
        .group_by(["unit", "branch"])
        .agg(pl.sum("previous_inbound_vol").alias("vol"))
        .sort("vol", descending=True)
        .head(20)
    )
    fig_top = go.Figure()
    fig_top.add_trace(go.Bar(
        x=top_inbound["vol"].to_list(),
        y=top_inbound["unit"].to_list(),
        orientation="h",
        marker_color="#378ADD",
        text=[f"{v:,.0f}" for v in top_inbound["vol"].to_list()],
        textposition="outside",
    ))
    fig_top.update_layout(
        height=max(300, len(top_inbound) * 28),
        margin=dict(l=0, r=80, t=10, b=0),
        xaxis_title="Sản lượng nhập",
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
    )
    st.plotly_chart(fig_top, use_container_width=True)


# ─── TRANG 2: CHI TIẾT THEO ĐƠN VỊ ──────────────────────────────────────────

with tab2:
    st.markdown("### Chi tiết theo đơn vị")

    all_units = sorted(actual["unit"].drop_nulls().unique().to_list())
    unit_detail = st.selectbox("Chọn đơn vị", all_units, key="unit_detail")

    unit_data = actual.filter(
        (pl.col("unit") == unit_detail) &
        (pl.col("date") >= pl.lit(date_from)) &
        (pl.col("date") <= pl.lit(date_to))
    )

    if len(unit_data) == 0:
        st.warning("Không có dữ liệu cho đơn vị này trong khoảng thời gian đã chọn.")
        st.stop()

    # Branch của unit này
    branch_of_unit = unit_data["branch"].drop_nulls().unique().to_list()
    branch_str = branch_of_unit[0] if branch_of_unit else "—"

    # Inbound
    unit_inbound = inbound.filter(
        (pl.col("unit") == unit_detail) &
        (pl.col("date") >= pl.lit(date_from)) &
        (pl.col("date") <= pl.lit(date_to))
    )
    total_vol_unit = unit_inbound["previous_inbound_vol"].sum() if len(unit_inbound) > 0 else 0
    total_ton_unit = unit_inbound["previous_inbound_ton"].sum() if len(unit_inbound) > 0 else 0

    col_h1, col_h2, col_h3 = st.columns([2, 1, 1])
    with col_h1:
        st.markdown(f"**{unit_detail}** · Chi nhánh: {branch_str}")
    with col_h2:
        st.metric("Sản lượng nhập", f"{total_vol_unit:,.0f}")
    with col_h3:
        st.metric("Trọng lượng nhập (tấn)", f"{total_ton_unit:,.2f}")

    st.markdown("---")

    # ── KPI MINI CARDS ──
    st.markdown("#### Các chỉ số KPI")
    unit_cum = calc_cumulative(unit_data)
    network_cum = calc_cumulative(filtered)
    kpi_cols2 = st.columns(3)

    for idx, (kpi_id, meta) in enumerate(KPI_META.items()):
        val = unit_cum.get(kpi_id)
        tgt_val = get_target_for_unit(kpi_id, unit_detail, ref_month, ref_year)
        net_val = network_cum.get(kpi_id)

        if val is not None and KPI_IS_RATIO.get(kpi_id) and kpi_id != [4,7]:
            display_val = f"{val*100:.2f}%"
            tgt_display = f"{tgt_val*100:.2f}%" if tgt_val else "—"
            net_display = f"{net_val*100:.2f}%" if net_val else "—"
            delta = (val - tgt_val) * 100 if tgt_val else None
        elif kpi_id == 4:
            display_val = f"{val:.2f} phút" if val else "—"
            tgt_display = f"{tgt_val:.2f} phút" if tgt_val else "—"
            net_display = f"{net_val:.2f} phút" if net_val else "—"
            delta = (val - tgt_val) if tgt_val and val else None
        elif kpi_id == 7:
            display_val = f"{val:.2f} kg/km" if val else "—"
            tgt_display = f"{tgt_val:.2f} kg/km" if tgt_val else "—"
            net_display = f"{net_val:.2f} kg/km" if net_val else "—"
            delta = (val - tgt_val) if tgt_val and val else None
        else:
            display_val = f"{val:.2f}" if val else "—"
            tgt_display = "—"
            net_display = "—"
            delta = None

        status_label, status_color = get_status(val, tgt_val, meta["direction"]) if val and tgt_val else ("—", "white")
        delta_str = f"{delta:+.2f}" if delta is not None else ""
        delta_color = (
            "#1D9E75" if (delta is not None and (
                (meta["direction"] == "gte" and delta >= 0) or
                (meta["direction"] == "lte" and delta <= 0)
            )) else ("#A32D2D" if delta is not None else "#bbb")
        )

        col = kpi_cols2[idx % 3]
        with col:
            st.markdown(
                kpi_card_unit(meta["name"], display_val, tgt_display, net_display, delta_str, delta_color, status_label, status_color),
                unsafe_allow_html=True
            )

    st.markdown("---")

    # ── 6 LINE CHARTS TREND THEO NGÀY ──
    st.markdown("#### Xu hướng theo ngày")

    chart_cols = st.columns(2)
    for idx, (kpi_id, meta) in enumerate(KPI_META.items()):
        kpi_daily = (
            unit_data.filter(pl.col("kpi_id") == kpi_id)
            .group_by("date")
            .agg([pl.sum("numerator").alias("num"), pl.sum("denominator").alias("den")])
            .with_columns((pl.col("num") / pl.col("den")).alias("val"))
            .sort("date")
        )
        if len(kpi_daily) == 0:
            continue

        dates = kpi_daily["date"].to_list()
        vals_raw = kpi_daily["val"].to_list()
        tgt_val = get_target_for_unit(kpi_id, unit_detail, ref_month, ref_year)

        if KPI_IS_RATIO.get(kpi_id) and kpi_id != [4,7]:
            vals_plot = [v * 100 if v else None for v in vals_raw]
            tgt_plot = tgt_val * 100 if tgt_val else None
            y_suffix = "%"
        elif kpi_id == 4:
            vals_plot = vals_raw
            tgt_plot = tgt_val
            y_suffix = " phút"
        elif kpi_id == 7:
            vals_plot = vals_raw
            tgt_plot = tgt_val
            y_suffix = " kg/km"
        else:
            vals_plot = vals_raw
            tgt_plot = tgt_val
            y_suffix = ""

        fig_line = go.Figure()
        fig_line.add_trace(go.Scatter(
            x=dates, y=vals_plot,
            mode="lines+markers",
            line=dict(color="#378ADD", width=2),
            marker=dict(size=4),
            name=unit_detail,
        ))
        if tgt_plot:
            fig_line.add_trace(go.Scatter(
                x=[dates[0], dates[-1]],
                y=[tgt_plot, tgt_plot],
                mode="lines",
                line=dict(color="#888", dash="dash", width=1),
                name="Mục tiêu",
            ))
        fig_line.update_layout(
            title=dict(text=meta["name"], font=dict(size=12), x=0),
            height=200,
            margin=dict(l=0, r=0, t=30, b=0),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(size=10),
            showlegend=False,
            yaxis=dict(ticksuffix=y_suffix),
        )
        col = chart_cols[idx % 2]
        with col:
            st.plotly_chart(fig_line, use_container_width=True)

    st.markdown("---")

    # ── SO SÁNH VỚI MẠNG LƯỚI ──
    st.markdown("#### So sánh với mạng lưới")
    compare_rows = []
    for kpi_id, meta in KPI_META.items():
        val = unit_cum.get(kpi_id)
        net = network_cum.get(kpi_id)
        if val is None:
            continue
        if KPI_IS_RATIO.get(kpi_id) and kpi_id != [4,7]:
            val_d = f"{val*100:.2f}%"
            net_d = f"{net*100:.2f}%" if net else "—"
            delta_d = f"{(val-net)*100:+.2f}%" if net else "—"
        elif kpi_id == 4:
            val_d = f"{val:.2f} phút"
            net_d = f"{net:.2f} phút" if net else "—"
            delta_d = f"{val-net:+.2f} phút" if net else "—"
        elif kpi_id == 7:
            val_d = f"{val:.2f} kg/km"
            net_d = f"{net:.2f} kg/km" if net else "—"
            delta_d = f"{val-net:+.2f} kg/km" if net else "—"
        else:
            val_d = f"{val:.4f}"
            net_d = f"{net:.4f}" if net else "—"
            delta_d = f"{val-net:+.4f}" if net else "—"
        compare_rows.append({
            "KPI": meta["name"],
            f"Đơn vị ({unit_detail})": val_d,
            "Mạng lưới TB": net_d,
            "Chênh lệch": delta_d,
        })

    if compare_rows:
        import pandas as pd
        df_compare = pd.DataFrame(compare_rows)
        st.dataframe(df_compare, use_container_width=True, hide_index=True)