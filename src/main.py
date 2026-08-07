from __future__ import annotations
import re
import textwrap
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)

FILE_MAIN = DATA_DIR / "steel_model_results.xlsx"

OUT_MAIN_PNG = RESULTS_DIR / "knife_steels_main.png"
OUT_PRED_PNG = RESULTS_DIR / "others_predicted_steels.png"
OUT_PRICE_PNG = RESULTS_DIR / "price_vs_quality.png"
OUT_MAIN_QUALITY_TABLE_PNG = RESULTS_DIR / "main_steels_table.png"
OUT_PRED_QUALITY_TABLE_PNG = RESULTS_DIR / "predicted_steels_table.png"
OUT_COMPOSITION_TABLE_PNG = RESULTS_DIR / "steel_composition_table.png"


# results table and graphs theme
THEME = {
    "bg": "#050308",
    "panel": "#11061B",
    "panel_2": "#1B0A2C",
    "grid": "#5C2B8A",
    "spine": "#B67CFF",
    "text": "#F5EEFF",
    "muted": "#D9C6FF",
    "accent": "#8F33F4",
    "accent_soft": "#C183FF",
    "accent_deep": "#5C0C92",
    "accent_mid": "#7421CF",
    "accent_mid2": "#9D57F5",
    "accent_light": "#C997FF",
    "highlight": "#EFE2FF",
    "predicted": "#2A103F",
    "predicted_light": "#3B1660",
}

CORROSION_COLORS = {
    "low": "#b7410e",
    "mid_low": "#BF9084",
    "mid_high": "#C6AAA4",
    "high": "#BFBFBF",
}

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.titleweight": "bold",
    "axes.labelweight": "bold",
})

# Layout spacing
SCATTER_BOTTOM_WITH_COMMENT = 0.1
SCATTER_BOTTOM_STANDARD = 0.10
PRICE_CHART_BOTTOM = 0.13
TABLE_BOTTOM = 0.001
TABLE_HEIGHT = 0.99
FOOTER_Y_WITH_COMMENT = 0.023
FOOTER_Y_STANDARD = 0.020



source_text = (
    "Source for toughness, edge retention, and corrosion resistance values: Blade HQ, "
    '"Knife Steel Guide" (George Muhlestein, Aug. 29, 2022), and Knife Steel Nerds, '
    '"Knife Steels Rated by a Metallurgist – Toughness, Edge Retention, and Corrosion Resistance" '
    "(Larrin Thomas, Oct. 19, 2021)."
)


# Utilities
def normalize_colname(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def corrosion_color(score: float) -> str:
    if score <= 5.5:
        return CORROSION_COLORS["low"]
    elif score <= 7.4:
        return CORROSION_COLORS["mid_low"]
    elif score < 9.0:
        return CORROSION_COLORS["mid_high"]
    return CORROSION_COLORS["high"]


def get_composition_columns(df: pd.DataFrame) -> list[str]:
    wanted = ["C", "Cr", "Mo", "V", "W", "Co", "Ni", "Mn", "Si", "S", "P", "Cu", "Nb", "N"]
    return [c for c in wanted if c in df.columns]


def find_required_columns(df: pd.DataFrame) -> dict[str, str | None]:
    colmap = {normalize_colname(c): c for c in df.columns}

    steel_col = colmap.get("steel")
    tough_col = None
    edge_col = None
    corr_col = None
    quality_col = None
    mean_price_col = None
    mean_fixed_col = None
    mean_folding_col = None
    mean_both_col = None
    tech_col = None

    for c in df.columns:
        nc = normalize_colname(c)

        if steel_col is None and nc == "steel":
            steel_col = c

        if tough_col is None and "toughness" in nc:
            tough_col = c
        elif edge_col is None and "edgeretention" in nc:
            edge_col = c
        elif corr_col is None and "corrosionresistance" in nc:
            corr_col = c
        elif quality_col is None and ("qualityscore" in nc or "qualityscore2" in nc):
            quality_col = c
        elif mean_price_col is None and nc in {"meanprice", "averageprice", "avgprice"}:
            mean_price_col = c
        elif mean_fixed_col is None and nc == "meanfixed":
            mean_fixed_col = c
        elif mean_folding_col is None and nc == "meanfolding":
            mean_folding_col = c
        elif mean_both_col is None and nc == "meanboth":
            mean_both_col = c
        elif tech_col is None and nc == "tech":
            tech_col = c

    found = {
        "steel": steel_col,
        "toughness": tough_col,
        "edge": edge_col,
        "corrosion": corr_col,
        "quality": quality_col,
        "mean_price": mean_price_col,
        "mean_fixed": mean_fixed_col,
        "mean_folding": mean_folding_col,
        "mean_both": mean_both_col,
        "tech": tech_col,
    }

    required = ["steel", "toughness", "edge", "corrosion", "quality"]
    missing = [k for k in required if found[k] is None]
    if missing:
        raise ValueError(
            f"Columns not found: {missing}\n"
            f"Columns found: {list(df.columns)}"
        )

    return found


def load_steel_csv(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        df = pd.read_excel(path, sheet_name=0)
    else:
        df = pd.read_csv(path, sep=";", decimal=",")
    df.columns = [c.strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.contains("^Unnamed", case=False)].copy()

    cols = find_required_columns(df)
    composition_cols = get_composition_columns(df)

    selected_cols = [
        cols["steel"],
        cols["toughness"],
        cols["edge"],
        cols["corrosion"],
        cols["quality"],
    ]

    if cols["tech"] is not None:
        selected_cols.append(cols["tech"])

    selected_cols.extend(composition_cols)

    for price_key in ["mean_price", "mean_fixed", "mean_folding", "mean_both"]:
        if cols.get(price_key) is not None:
            selected_cols.append(cols[price_key])

    out = df[selected_cols].copy()

    rename_map = {
        cols["steel"]: "Steel",
        cols["toughness"]: "Toughness",
        cols["edge"]: "Edge Retention",
        cols["corrosion"]: "Corrosion Resistance",
        cols["quality"]: "Global Quality Score",
    }

    if cols["tech"] is not None:
        rename_map[cols["tech"]] = "Tech"

    if cols.get("mean_price") is not None:
        rename_map[cols["mean_price"]] = "Average Price Raw"
    if cols.get("mean_fixed") is not None:
        rename_map[cols["mean_fixed"]] = "Price Fixed"
    if cols.get("mean_folding") is not None:
        rename_map[cols["mean_folding"]] = "Price Folding"
    if cols.get("mean_both") is not None:
        rename_map[cols["mean_both"]] = "Price Both"

    out = out.rename(columns=rename_map)

    numeric_cols = [
        "Toughness",
        "Edge Retention",
        "Corrosion Resistance",
        "Global Quality Score",
        "Average Price Raw",
        "Price Fixed",
        "Price Folding",
        "Price Both",
        *composition_cols,
    ]

    for c in numeric_cols:
        if c in out.columns:
            out[c] = (
                out[c]
                .astype(str)
                .str.replace(",", ".", regex=False)
                .str.strip()
            )
            out[c] = pd.to_numeric(out[c], errors="coerce")

    price_candidates = [
        c for c in ["Average Price Raw", "Price Fixed", "Price Folding", "Price Both"]
        if c in out.columns
    ]
    if price_candidates:
        out["Average Price"] = out[price_candidates].mean(axis=1, skipna=True)
    else:
        out["Average Price"] = np.nan

    out["Steel"] = out["Steel"].astype(str).str.strip()

    if "Tech" in out.columns:
        out["Tech"] = out["Tech"].astype(str).str.strip()
    else:
        out["Tech"] = ""

    out = out.dropna(
        subset=[
            "Steel",
            "Toughness",
            "Edge Retention",
            "Corrosion Resistance",
            "Global Quality Score",
        ]
    ).copy()

    out["Predicted"] = out["Steel"].str.contains(r"\(predicted\)", case=False, regex=True)
    out["Color"] = out["Corrosion Resistance"].apply(corrosion_color)

    ordered_cols = [
        "Steel",
        "Toughness",
        "Edge Retention",
        "Corrosion Resistance",
        "Global Quality Score",
        "Average Price",
        "Tech",
        *composition_cols,
        "Color",
        "Predicted",
    ]
    ordered_cols = [c for c in ordered_cols if c in out.columns]

    return out[ordered_cols].copy()


def move_text_by_pixels(ax, text_obj, dx_pix=0, dy_pix=0):
    x_old, y_old = text_obj.get_position()
    x_disp, y_disp = ax.transData.transform((x_old, y_old))
    x_new, y_new = ax.transData.inverted().transform((x_disp + dx_pix, y_disp + dy_pix))
    text_obj.set_position((x_new, y_new))


def repel_labels(
    fig,
    ax,
    label_items,
    x_min: float,
    x_max: float,
    base_label_drop: float,
    max_iter: int,
    shift_x_pixels: int,
    shift_y_pixels: int,
) -> None:
    def keep_label_below_reference(item):
        txt = item["text"]
        tx, ty = txt.get_position()

        min_allowed_y = item["anchor_y"] - base_label_drop * 0.90
        if ty > min_allowed_y:
            ty = min_allowed_y

        tx = max(tx, x_min)
        tx = min(tx, x_max)
        txt.set_position((tx, ty))

    fig.canvas.draw()

    for _ in range(max_iter):
        moved = False
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()

        bboxes = [
            item["text"].get_window_extent(renderer=renderer).expanded(1.14, 1.30)
            for item in label_items
        ]

        for i in range(len(label_items)):
            for j in range(i + 1, len(label_items)):
                if bboxes[i].overlaps(bboxes[j]):
                    moved = True

                    ci_x = 0.5 * (bboxes[i].x0 + bboxes[i].x1)
                    cj_x = 0.5 * (bboxes[j].x0 + bboxes[j].x1)

                    if ci_x <= cj_x:
                        move_text_by_pixels(ax, label_items[i]["text"], dx_pix=-shift_x_pixels, dy_pix=shift_y_pixels)
                        move_text_by_pixels(ax, label_items[j]["text"], dx_pix=+shift_x_pixels, dy_pix=shift_y_pixels)
                    else:
                        move_text_by_pixels(ax, label_items[i]["text"], dx_pix=+shift_x_pixels, dy_pix=shift_y_pixels)
                        move_text_by_pixels(ax, label_items[j]["text"], dx_pix=-shift_x_pixels, dy_pix=shift_y_pixels)

        for item in label_items:
            keep_label_below_reference(item)

        if not moved:
            break


def style_axes(ax):
    ax.set_facecolor(THEME["panel"])
    for spine in ax.spines.values():
        spine.set_color(THEME["spine"])
        spine.set_linewidth(1.15)
    ax.tick_params(colors=THEME["text"], labelsize=11)
    ax.xaxis.label.set_color(THEME["text"])
    ax.yaxis.label.set_color(THEME["text"])
    ax.title.set_color(THEME["highlight"])
    ax.grid(True, linestyle="--", linewidth=0.8, alpha=0.35, color=THEME["grid"])


def style_legend(legend):
    frame = legend.get_frame()
    frame.set_facecolor(THEME["panel_2"])
    frame.set_edgecolor(THEME["accent_soft"])
    frame.set_alpha(0.96)

    legend.get_title().set_color(THEME["highlight"])
    for txt in legend.get_texts():
        txt.set_color(THEME["text"])


def add_footer(fig, *, include_comment: bool = False) -> None:
    wrapped_source = textwrap.fill(source_text, width=190)

    if include_comment:
        fig.text(
            0.08,
            FOOTER_Y_WITH_COMMENT,
            wrapped_source,
            ha="left",
            va="bottom",
            fontsize=6.4,
            color=THEME["accent_light"],
            style="italic",
        )
    else:
        fig.text(
            0.08,
            FOOTER_Y_STANDARD,
            wrapped_source,
            ha="left",
            va="bottom",
            fontsize=6.6,
            color=THEME["accent_light"],
            style="italic",
        )


def make_scatter_chart(
    df: pd.DataFrame,
    title: str,
    output_path: Path,
    top_n: int = 5,
    include_comment: bool = False,
) -> None:
    if df.empty:
        print(f"Skipped empty chart: {output_path}")
        return

    FIG_W = 22
    FIG_H = 14
    POINT_SIZE = 430
    SCORE_FONTSIZE = 8
    LABEL_FONTSIZE = 7

    BASE_LABEL_DROP = 0.40
    MAX_ITER = 450
    SHIFT_X_PIXELS = 20
    SHIFT_Y_PIXELS = -14
    MIN_DIST_FOR_ARROW_PIXELS = 6

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    fig.patch.set_facecolor(THEME["bg"])
    style_axes(ax)

    ax.scatter(
        df["Edge Retention"],
        df["Toughness"],
        s=POINT_SIZE,
        c=df["Color"],
        edgecolors=THEME["highlight"],
        linewidths=1.1,
        alpha=0.98,
        zorder=2,
    )

    for _, row in df.iterrows():
        ax.text(
            row["Edge Retention"],
            row["Toughness"],
            f"{row['Global Quality Score']:.2f}",
            ha="center",
            va="center",
            fontsize=SCORE_FONTSIZE,
            fontweight="bold",
            color=THEME["highlight"],
            zorder=3,
        )

    x = df["Edge Retention"].to_numpy()
    y = df["Toughness"].to_numpy()

    x_min, x_max = x.min(), x.max()
    y_min, y_max = y.min(), y.max()
    y_range = y_max - y_min if y_max > y_min else 1.0

    ax.set_title(title, fontsize=20, fontweight="bold", pad=16)
    ax.set_xlabel("Edge Retention", fontsize=16)
    ax.set_ylabel("Toughness", fontsize=16)

    ax.set_xlim(x_min - 0.8, x_max + 1.4)
    ax.set_ylim(y_min - 1.55, y_max + 1.0)

    label_items = []

    for _, row in df.iterrows():
        x_anchor = row["Edge Retention"]
        y_anchor = row["Toughness"]

        x_text = x_anchor
        y_text = y_anchor - BASE_LABEL_DROP

        txt = ax.text(
            x_text,
            y_text,
            row["Steel"],
            ha="center",
            va="top",
            fontsize=LABEL_FONTSIZE,
            fontweight="bold",
            color=THEME["text"],
            bbox=dict(
                boxstyle="round,pad=0.22",
                facecolor=THEME["panel_2"],
                edgecolor=THEME["accent_soft"],
                linewidth=0.7,
                alpha=0.97,
            ),
            zorder=4,
            clip_on=False,
        )

        label_items.append(
            {
                "text": txt,
                "anchor_x": x_anchor,
                "anchor_y": y_anchor,
                "orig_x": x_text,
                "orig_y": y_text,
            }
        )

    repel_labels(
        fig=fig,
        ax=ax,
        label_items=label_items,
        x_min=x_min - 0.2,
        x_max=x_max + 0.8,
        base_label_drop=BASE_LABEL_DROP,
        max_iter=MAX_ITER,
        shift_x_pixels=SHIFT_X_PIXELS,
        shift_y_pixels=SHIFT_Y_PIXELS,
    )

    fig.canvas.draw()
    for item in label_items:
        txt = item["text"]
        tx, ty = txt.get_position()

        x0_disp, y0_disp = ax.transData.transform((item["orig_x"], item["orig_y"]))
        x1_disp, y1_disp = ax.transData.transform((tx, ty))
        dist_pix = ((x1_disp - x0_disp) ** 2 + (y1_disp - y0_disp) ** 2) ** 0.5

        if dist_pix >= MIN_DIST_FOR_ARROW_PIXELS:
            ax.annotate(
                "",
                xy=(item["anchor_x"], item["anchor_y"] - 0.03 * y_range),
                xytext=(tx, ty),
                arrowprops=dict(
                    arrowstyle="->",
                    color=THEME["accent_light"],
                    lw=0.9,
                    alpha=0.85,
                    shrinkA=3,
                    shrinkB=5,
                ),
                zorder=1,
            )

    top_n_df = df.sort_values("Global Quality Score", ascending=False).head(top_n)
    bottom_n_df = df.sort_values("Global Quality Score", ascending=True).head(top_n)

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", label="Corrosion ≤ 5.5",
               markerfacecolor=CORROSION_COLORS["low"], markeredgecolor=THEME["highlight"], markersize=12),
        Line2D([0], [0], marker="o", color="w", label="Corrosion 5.6 to 7.4",
               markerfacecolor=CORROSION_COLORS["mid_low"], markeredgecolor=THEME["highlight"], markersize=12),
        Line2D([0], [0], marker="o", color="w", label="Corrosion 7.5 to 8.9",
               markerfacecolor=CORROSION_COLORS["mid_high"], markeredgecolor=THEME["highlight"], markersize=12),
        Line2D([0], [0], marker="o", color="w", label="Corrosion ≥ 9.0",
               markerfacecolor=CORROSION_COLORS["high"], markeredgecolor=THEME["highlight"], markersize=12),
        Line2D([], [], linestyle="None", label=""),
        Line2D([], [], linestyle="None", label=f"Top {top_n} Global Quality Score"),
    ]

    for _, row in top_n_df.iterrows():
        legend_elements.append(
            Line2D(
                [0], [0],
                marker="o",
                color="w",
                label=f"{row['Steel']} : {row['Global Quality Score']:.2f}",
                markerfacecolor=row["Color"],
                markeredgecolor=THEME["highlight"],
                markersize=8,
            )
        )

    legend_elements.extend([
        Line2D([], [], linestyle="None", label=""),
        Line2D([], [], linestyle="None", label=f"Bottom {top_n} Global Quality Score"),
    ])

    for _, row in bottom_n_df.iterrows():
        legend_elements.append(
            Line2D(
                [0], [0],
                marker="o",
                color="w",
                label=f"{row['Steel']} : {row['Global Quality Score']:.2f}",
                markerfacecolor=row["Color"],
                markeredgecolor=THEME["highlight"],
                markersize=8,
            )
        )

    legend = ax.legend(
        handles=legend_elements,
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        frameon=True,
        title="Legend",
        fontsize=11,
        title_fontsize=14,
    )
    style_legend(legend)

    for txt in legend.get_texts():
        if txt.get_text() == f"Top {top_n} Global Quality Score":
            txt.set_color("#83FFB2")
            txt.set_fontweight("bold")
        elif txt.get_text() == f"Bottom {top_n} Global Quality Score":
            txt.set_color("#FF93C7")
            txt.set_fontweight("bold")

    if include_comment:
        plt.subplots_adjust(left=0.08, right=0.76, top=0.90, bottom=SCATTER_BOTTOM_WITH_COMMENT)
    else:
        plt.subplots_adjust(left=0.08, right=0.76, top=0.90, bottom=SCATTER_BOTTOM_STANDARD)

    add_footer(fig, include_comment=include_comment)
    fig.savefig(output_path, dpi=320, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def make_price_quality_chart(df: pd.DataFrame, output_path: Path) -> None:
    price_df = df.dropna(subset=["Average Price"]).copy()
    if price_df.empty:
        raise ValueError("No steel with price available for the price vs. score chart.")

    FIG_W = 18
    FIG_H = 11
    POINT_SIZE = 390
    SCORE_FONTSIZE = 8
    LABEL_FONTSIZE = 7

    BASE_LABEL_DROP = 0.20
    MAX_ITER = 450
    SHIFT_X_PIXELS = 22
    SHIFT_Y_PIXELS = -12
    MIN_DIST_FOR_ARROW_PIXELS = 6

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    fig.patch.set_facecolor(THEME["bg"])
    style_axes(ax)

    ax.scatter(
        price_df["Average Price"],
        price_df["Global Quality Score"],
        s=POINT_SIZE,
        c=price_df["Color"],
        edgecolors=THEME["highlight"],
        linewidths=1.1,
        alpha=0.98,
        zorder=2,
    )

    for _, row in price_df.iterrows():
        ax.text(
            row["Average Price"],
            row["Global Quality Score"],
            f"{row['Global Quality Score']:.2f}",
            ha="center",
            va="center",
            fontsize=SCORE_FONTSIZE,
            fontweight="bold",
            color=THEME["highlight"],
            zorder=3,
        )

    x = price_df["Average Price"].to_numpy()
    y = price_df["Global Quality Score"].to_numpy()

    x_min, x_max = x.min(), x.max()
    y_min, y_max = y.min(), y.max()
    x_range = x_max - x_min if x_max > x_min else 1.0
    y_range = y_max - y_min if y_max > y_min else 1.0

    ax.set_title("Average Price vs Global Quality Score", fontsize=19, fontweight="bold", pad=14)
    ax.set_xlabel("Average Price", fontsize=15)
    ax.set_ylabel("Global Quality Score", fontsize=15)

    ax.set_xlim(x_min - 0.08 * x_range, x_max + 0.20 * x_range)
    ax.set_ylim(y_min - 0.90, y_max + 0.70)

    label_items = []

    for _, row in price_df.iterrows():
        x_anchor = row["Average Price"]
        y_anchor = row["Global Quality Score"]

        x_text = x_anchor
        y_text = y_anchor - BASE_LABEL_DROP

        txt = ax.text(
            x_text,
            y_text,
            row["Steel"],
            ha="center",
            va="top",
            fontsize=LABEL_FONTSIZE,
            fontweight="bold",
            color=THEME["text"],
            bbox=dict(
                boxstyle="round,pad=0.22",
                facecolor=THEME["panel_2"],
                edgecolor=THEME["accent_soft"],
                linewidth=0.7,
                alpha=0.97,
            ),
            zorder=4,
            clip_on=False,
        )

        label_items.append(
            {
                "text": txt,
                "anchor_x": x_anchor,
                "anchor_y": y_anchor,
                "orig_x": x_text,
                "orig_y": y_text,
            }
        )

    repel_labels(
        fig=fig,
        ax=ax,
        label_items=label_items,
        x_min=x_min - 0.03 * x_range,
        x_max=x_max + 0.14 * x_range,
        base_label_drop=BASE_LABEL_DROP,
        max_iter=MAX_ITER,
        shift_x_pixels=SHIFT_X_PIXELS,
        shift_y_pixels=SHIFT_Y_PIXELS,
    )

    fig.canvas.draw()
    for item in label_items:
        txt = item["text"]
        tx, ty = txt.get_position()

        x0_disp, y0_disp = ax.transData.transform((item["orig_x"], item["orig_y"]))
        x1_disp, y1_disp = ax.transData.transform((tx, ty))
        dist_pix = ((x1_disp - x0_disp) ** 2 + (y1_disp - y0_disp) ** 2) ** 0.5

        if dist_pix >= MIN_DIST_FOR_ARROW_PIXELS:
            ax.annotate(
                "",
                xy=(item["anchor_x"], item["anchor_y"] - 0.03 * y_range),
                xytext=(tx, ty),
                arrowprops=dict(
                    arrowstyle="->",
                    color=THEME["accent_light"],
                    lw=0.9,
                    alpha=0.85,
                    shrinkA=3,
                    shrinkB=5,
                ),
                zorder=1,
            )

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", label="Corrosion ≤ 5.5",
               markerfacecolor=CORROSION_COLORS["low"], markeredgecolor=THEME["highlight"], markersize=12),
        Line2D([0], [0], marker="o", color="w", label="Corrosion 5.6 to 7.4",
               markerfacecolor=CORROSION_COLORS["mid_low"], markeredgecolor=THEME["highlight"], markersize=12),
        Line2D([0], [0], marker="o", color="w", label="Corrosion 7.5 to 8.9",
               markerfacecolor=CORROSION_COLORS["mid_high"], markeredgecolor=THEME["highlight"], markersize=12),
        Line2D([0], [0], marker="o", color="w", label="Corrosion ≥ 9.0",
               markerfacecolor=CORROSION_COLORS["high"], markeredgecolor=THEME["highlight"], markersize=12),
        Line2D([], [], linestyle="None", label=""),
        Line2D([], [], linestyle="None", label=f"Steels with available prices: {len(price_df)}"),
    ]

    legend = ax.legend(
        handles=legend_elements,
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        frameon=True,
        title="Legend",
        fontsize=11,
        title_fontsize=14,
    )
    style_legend(legend)

    plt.subplots_adjust(left=0.08, right=0.76, top=0.90, bottom=PRICE_CHART_BOTTOM)
    add_footer(fig, include_comment=False)
    fig.savefig(output_path, dpi=320, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def build_quality_table(df_all: pd.DataFrame) -> pd.DataFrame:
    quality = df_all[
        [
            "Steel",
            "Toughness",
            "Edge Retention",
            "Corrosion Resistance",
            "Global Quality Score",
            "Average Price",
            "Predicted",
        ]
    ].copy()

    quality = quality.sort_values(
        by=["Global Quality Score", "Edge Retention", "Toughness"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    return quality


def build_composition_table(df_all: pd.DataFrame) -> pd.DataFrame:
    composition_cols = [c for c in get_composition_columns(df_all) if c in df_all.columns]

    comp = df_all[
        [
            "Steel",
            "Tech",
            *composition_cols,
            "Global Quality Score",
            "Edge Retention",
            "Toughness",
            "Predicted",
        ]
    ].copy()

    comp = comp.sort_values(
        by=["Global Quality Score", "Edge Retention", "Toughness"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    keep_cols = ["Steel", "Tech", *composition_cols, "Predicted"]
    return comp[keep_cols]


def format_quality_table(df_table: pd.DataFrame) -> pd.DataFrame:
    display_df = df_table.copy()

    for col in ["Toughness", "Edge Retention", "Corrosion Resistance", "Global Quality Score"]:
        display_df[col] = display_df[col].map(lambda x: f"{x:.2f}")

    display_df["Average Price"] = display_df["Average Price"].map(
        lambda x: "" if pd.isna(x) else f"${x:,.2f}"
    )

    return display_df


def fmt_comp(x):
    if pd.isna(x):
        return ""
    return f"{x:.3f}".rstrip("0").rstrip(".")


def format_composition_table(df_table: pd.DataFrame) -> pd.DataFrame:
    display_df = df_table.copy()

    for col in display_df.columns:
        if col not in {"Steel", "Tech", "Predicted"}:
            display_df[col] = display_df[col].map(fmt_comp)

    return display_df


def style_table_cells(
    table,
    display_df: pd.DataFrame,
    predicted_col_name: str = "Predicted",
    highlight_predicted_rows: bool = True,
) -> None:
    header_bg = THEME["accent_deep"]
    header_fg = THEME["highlight"]
    grid_color = "#7C49B8"

    zebra_a = THEME["panel"]
    zebra_b = THEME["panel_2"]

    predicted_bg = THEME["predicted_light"]

    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor(grid_color)
        cell.set_linewidth(0.65)

        if row == 0:
            cell.set_facecolor(header_bg)
            cell.get_text().set_color(header_fg)
            cell.get_text().set_weight("bold")
            continue

        is_predicted = bool(
            display_df.iloc[row - 1][predicted_col_name]
        )

        if highlight_predicted_rows and is_predicted:
            cell.set_facecolor(predicted_bg)
        else:
            cell.set_facecolor(
                zebra_a if row % 2 == 1 else zebra_b
            )

        if col == 0:
            cell.get_text().set_ha("left")
            cell.PAD = 0.02
            cell.get_text().set_weight("bold")
        else:
            cell.get_text().set_ha("center")

        cell.get_text().set_color(THEME["text"])


def export_quality_table_png(
    df_table: pd.DataFrame,
    output_path: Path,
    title: str,
    subtitle: str,
) -> None:
    display_df = format_quality_table(df_table)

    columns = [
        "Steel",
        "Toughness",
        "Edge Retention",
        "Corrosion Resistance",
        "Global Quality Score",
        "Average Price",
    ]

    cell_text = display_df[columns].values.tolist()
    n_rows = len(display_df)

    fig_h = max(16, 0.34 * (n_rows + 5))
    fig_w = 18

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(THEME["bg"])
    ax.set_facecolor(THEME["bg"])
    ax.axis("off")

    ax.text(
        0.01,
        1.02,
        title,
        transform=ax.transAxes,
        fontsize=20,
        fontweight="bold",
        va="bottom",
        ha="left",
        color=THEME["highlight"],
    )

    ax.text(
        0.01,
        0.995,
        subtitle,
        transform=ax.transAxes,
        fontsize=9.5,
        va="bottom",
        ha="left",
        color=THEME["muted"],
    )

    col_widths = [0.31, 0.10, 0.13, 0.17, 0.15, 0.14]

    table = ax.table(
        cellText=cell_text,
        colLabels=columns,
        colLoc="center",
        cellLoc="center",
        colWidths=col_widths,
        bbox=[0.0, TABLE_BOTTOM, 1.0, TABLE_HEIGHT],
    )

    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.25)

    style_table_cells(
        table,
        display_df,
        predicted_col_name="Predicted",
        highlight_predicted_rows=False,
    )
    add_footer(fig, include_comment=False)
    fig.savefig(output_path, dpi=320, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def export_composition_table_png(df_table: pd.DataFrame, output_path: Path) -> None:
    display_df = format_composition_table(df_table)

    columns = [c for c in display_df.columns if c != "Predicted"]
    cell_text = display_df[columns].values.tolist()
    n_rows = len(display_df)

    fig_h = max(16, 0.31 * (n_rows + 6))
    fig_w = max(24, 1.55 * len(columns))

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(THEME["bg"])
    ax.set_facecolor(THEME["bg"])
    ax.axis("off")

    ax.text(
        0.005,
        1.02,
        "Knife Steels — Composition + Process Table",
        transform=ax.transAxes,
        fontsize=21,
        fontweight="bold",
        va="bottom",
        ha="left",
        color=THEME["highlight"],
    )

    ax.text(
        0.005,
        0.995,
        "Tech indicates PM, ingot, or mixed production as recorded in the source workbook.",
        transform=ax.transAxes,
        fontsize=9.5,
        va="bottom",
        ha="left",
        color=THEME["muted"],
    )

    col_widths = []
    for c in columns:
        if c == "Steel":
            col_widths.append(0.22)
        elif c == "Tech":
            col_widths.append(0.10)
        else:
            col_widths.append(0.047)

    table = ax.table(
        cellText=cell_text,
        colLabels=columns,
        colLoc="center",
        cellLoc="center",
        colWidths=col_widths,
        bbox=[0.0, TABLE_BOTTOM, 1.0, TABLE_HEIGHT],
    )

    table.auto_set_font_size(False)
    table.set_fontsize(8.2)
    table.scale(1, 1.18)

    style_table_cells(table, display_df, predicted_col_name="Predicted")
    add_footer(fig, include_comment=False)
    fig.savefig(output_path, dpi=320, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    df_all = load_steel_csv(FILE_MAIN)

    df_main = df_all[~df_all["Predicted"]].copy()
    df_pred = df_all[df_all["Predicted"]].copy()

    make_scatter_chart(
        df=df_main,
        title="Knife Steels: Edge Retention vs Toughness",
        output_path=OUT_MAIN_PNG,
        top_n=5,
        include_comment=False,
    )

    make_scatter_chart(
        df=df_pred,
        title="Other Predicted Steels",
        output_path=OUT_PRED_PNG,
        top_n=5,
        include_comment=False,
    )

    make_price_quality_chart(
        df=df_main,
        output_path=OUT_PRICE_PNG,
    )

    df_quality_main = build_quality_table(df_main)

    export_quality_table_png(
        df_quality_main,
        OUT_MAIN_QUALITY_TABLE_PNG,
        title="Observed Knife Steels — Performance Table",
        subtitle=(
            "Observed steels only; "
            "sorted by global quality score."
        ),
    )

    df_quality_pred = build_quality_table(df_pred)

    export_quality_table_png(
        df_quality_pred,
        OUT_PRED_QUALITY_TABLE_PNG,
        title="Predicted Knife Steels — Performance Table",
        subtitle=(
            "Model-predicted steels only; "
            "sorted by global quality score."
        ),
    )

    df_composition = build_composition_table(df_all)
    export_composition_table_png(df_composition, OUT_COMPOSITION_TABLE_PNG)

    print(f"Saved: {OUT_MAIN_PNG}")
    print(f"Saved: {OUT_PRED_PNG}")
    print(f"Saved: {OUT_PRICE_PNG}")
    print(
        f"Saved: {OUT_MAIN_QUALITY_TABLE_PNG}"
    )

    print(
        f"Saved: {OUT_PRED_QUALITY_TABLE_PNG}"
    )
    print(f"Saved: {OUT_COMPOSITION_TABLE_PNG}")


if __name__ == "__main__":
    main()
