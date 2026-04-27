import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def build_daily_series_with_zero_imputation(df: pd.DataFrame, date_col: str = "order_time") -> pd.DataFrame:
    """
    1) 缺失值补全（Zero-Imputation）
    - 将订单明细聚合为“按天订单量”
    - 对未营业/无订单日期进行 0 填充，保证时间轴连续
    """
    if date_col not in df.columns:
        raise ValueError(f"输入数据缺少日期列: {date_col}")

    work = df.copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=[date_col])
    work["date"] = work[date_col].dt.date

    daily = work.groupby("date", as_index=False).size().rename(columns={"size": "order_count"})
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date")

    full_range = pd.date_range(start=daily["date"].min(), end=daily["date"].max(), freq="D")
    daily = daily.set_index("date").reindex(full_range, fill_value=0).rename_axis("date").reset_index()
    daily["order_count"] = daily["order_count"].astype(int)
    return daily


def smooth_outliers_zscore(
    daily_df: pd.DataFrame,
    value_col: str = "order_count",
    z_thresh: float = 3.0,
    rolling_window: int = 7,
) -> pd.DataFrame:
    """
    2A) 异常值处理（Z-Score）
    - 识别 |z| > z_thresh 的毛刺点
    - 用滚动中位数进行平滑替换，避免过拟合
    """
    out = daily_df.copy()
    x = out[value_col].astype(float)

    std = x.std(ddof=0)
    if std == 0:
        out["is_outlier"] = False
        out[f"{value_col}_smoothed"] = x
        return out

    z = (x - x.mean()) / std
    is_outlier = z.abs() > z_thresh

    median_ref = x.rolling(window=rolling_window, center=True, min_periods=1).median()
    smoothed = x.where(~is_outlier, median_ref)

    out["is_outlier"] = is_outlier
    out[f"{value_col}_smoothed"] = smoothed.round().clip(lower=0).astype(int)
    return out


def smooth_outliers_quantile(
    daily_df: pd.DataFrame,
    value_col: str = "order_count",
    lower_q: float = 0.01,
    upper_q: float = 0.99,
) -> pd.DataFrame:
    """
    2B) 异常值处理（分位数法）
    - 识别低于 lower_q 或高于 upper_q 的极端值
    - 使用 winsorize 思路截断到分位边界
    """
    out = daily_df.copy()
    x = out[value_col].astype(float)

    low = x.quantile(lower_q)
    high = x.quantile(upper_q)
    is_outlier = (x < low) | (x > high)
    smoothed = x.clip(lower=low, upper=high)

    out["is_outlier"] = is_outlier
    out[f"{value_col}_smoothed"] = smoothed.round().clip(lower=0).astype(int)
    return out


def main():
    parser = argparse.ArgumentParser(description="预处理 generated_orders_2023.xlsx：零值填充 + 异常平滑")
    parser.add_argument(
        "--input",
        default="generated_orders_2023.xlsx",
        help="输入 Excel 文件名或路径（默认: generated_orders_2023.xlsx）",
    )
    parser.add_argument(
        "--output",
        default="generated_orders_2023_preprocessed.xlsx",
        help="输出 Excel 文件名或路径（默认: generated_orders_2023_preprocessed.xlsx）",
    )
    parser.add_argument(
        "--method",
        choices=["zscore", "quantile"],
        default="zscore",
        help="异常值处理方法：zscore 或 quantile（默认: zscore）",
    )
    parser.add_argument("--z-thresh", type=float, default=3.0, help="Z-Score 阈值（默认: 3.0）")
    parser.add_argument("--lower-q", type=float, default=0.01, help="分位数法下界（默认: 0.01）")
    parser.add_argument("--upper-q", type=float, default=0.99, help="分位数法上界（默认: 0.99）")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    input_path = (script_dir / args.input).resolve() if not Path(args.input).is_absolute() else Path(args.input)
    output_path = (script_dir / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)

    raw_df = pd.read_excel(input_path)
    daily_df = build_daily_series_with_zero_imputation(raw_df, date_col="order_time")

    if args.method == "zscore":
        processed_df = smooth_outliers_zscore(daily_df, value_col="order_count", z_thresh=args.z_thresh)
    else:
        processed_df = smooth_outliers_quantile(
            daily_df,
            value_col="order_count",
            lower_q=args.lower_q,
            upper_q=args.upper_q,
        )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        raw_df.to_excel(writer, sheet_name="raw_orders", index=False)
        daily_df.to_excel(writer, sheet_name="daily_zero_imputed", index=False)
        processed_df.to_excel(writer, sheet_name="daily_smoothed", index=False)


if __name__ == "__main__":
    main()

# ============================================================
# 核心功能代码定位（只读说明，不参与运行逻辑）
# ============================================================
# 1) 缺失值补全（Zero-Imputation）核心：
#    函数：build_daily_series_with_zero_imputation
#    关键语句：
#    - 按天聚合订单量：
#      daily = work.groupby("date", as_index=False).size().rename(columns={"size": "order_count"})
#    - 构造连续日期索引并零填充：
#      full_range = pd.date_range(start=daily["date"].min(), end=daily["date"].max(), freq="D")
#      daily = daily.set_index("date").reindex(full_range, fill_value=0)
#
# 2) 异常值处理（Z-Score）核心：
#    函数：smooth_outliers_zscore
#    关键语句：
#    - 计算 Z 分数并识别异常：
#      z = (x - x.mean()) / std
#      is_outlier = z.abs() > z_thresh
#    - 用滚动中位数平滑：
#      median_ref = x.rolling(window=rolling_window, center=True, min_periods=1).median()
#      smoothed = x.where(~is_outlier, median_ref)
#
# 3) 异常值处理（分位数法）核心：
#    函数：smooth_outliers_quantile
#    关键语句：
#    - 分位边界识别异常：
#      low = x.quantile(lower_q)
#      high = x.quantile(upper_q)
#      is_outlier = (x < low) | (x > high)
#    - 截断平滑（winsorize 思路）：
#      smoothed = x.clip(lower=low, upper=high)
#
# 4) 主流程编排核心：
#    函数：main
#    关键步骤：
#    - 读取 Excel：raw_df = pd.read_excel(input_path)
#    - 连续化日序列：daily_df = build_daily_series_with_zero_imputation(raw_df, date_col="order_time")
#    - 二选一异常处理：processed_df = smooth_outliers_zscore(...) / smooth_outliers_quantile(...)
#    - 输出结果到多 sheet Excel：raw_orders / daily_zero_imputed / daily_smoothed


# =========================
# 核心功能代码（便于展示/引用）
# =========================
def core_preprocess_pipeline(
    input_path: str = "generated_orders_2023.xlsx",
    output_path: str = "generated_orders_2023_preprocessed.xlsx",
    method: str = "zscore",
):
    """
    核心流程：
    1) 读取订单 Excel
    2) 按天聚合 + Zero-Imputation（补齐无订单日期为 0）
    3) 异常值识别与平滑（Z-Score / 分位数法）
    4) 导出处理结果
    """
    script_dir = Path(__file__).resolve().parent
    in_file = (script_dir / input_path).resolve() if not Path(input_path).is_absolute() else Path(input_path)
    out_file = (script_dir / output_path).resolve() if not Path(output_path).is_absolute() else Path(output_path)

    raw_df = pd.read_excel(in_file)
    daily_df = build_daily_series_with_zero_imputation(raw_df, date_col="order_time")

    if method == "quantile":
        final_df = smooth_outliers_quantile(daily_df, value_col="order_count", lower_q=0.01, upper_q=0.99)
    else:
        final_df = smooth_outliers_zscore(daily_df, value_col="order_count", z_thresh=3.0)

    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:
        daily_df.to_excel(writer, sheet_name="daily_zero_imputed", index=False)
        final_df.to_excel(writer, sheet_name="daily_smoothed", index=False)

    return final_df
