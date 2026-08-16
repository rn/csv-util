#! /usr/bin/env python3

"""Main entry point"""

from argparse import ArgumentParser
import io
import re
import sys
from typing import Optional

import pandas as pd


def try_datetime(series: pd.Series, min_success_rate: float = 0.9) -> pd.Series:
    """Try to convert a series to datetime; return converted series if it looks like dates."""
    if not (
        pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)
    ):
        return series

    converted: pd.Series = pd.to_datetime(series, errors="coerce")

    # Only accept if most non-null values successfully converted
    success_rate: float = (
        converted.notna().sum() / series.notna().sum()
        if series.notna().sum() > 0
        else 0
    )

    if success_rate >= min_success_rate:
        return converted
    return series


def args_comma_separated_list(value: str) -> Optional[list[str]]:
    """Convert string to list"""
    if value is None or value.strip() == "":
        return None
    return [item.strip() for item in value.split(",")]


def cols_select(strings: list[str], columns: list[str]) -> list[str]:
    """Return list of selected columns"""
    selected: list[str] = []

    for s in strings:
        if s in columns:
            # Direct name match
            if s not in selected:
                selected.append(s)
        else:
            try:
                idx = int(s)
                if 0 <= idx < len(columns) and columns[idx] not in selected:
                    selected.append(columns[idx])
            except ValueError:
                pass
    return selected


# Matches contains(Column, 'substring'[, case=True|False])
_CONTAINS_RE = re.compile(
    r"contains\(\s*(\w+)\s*,\s*('[^']*'|\"[^\"]*\")\s*(?:,\s*case\s*=\s*(True|False))?\s*\)"
)

# Matches bare dates like 2026-01-01, but not ones already quoted or glued
# to other word characters.
_DATE_RE = re.compile(r"(?<![\"'\w])\d{4}-\d{2}-\d{2}(?![\"'\w])")


def filter_rows(df: pd.DataFrame, expr: str) -> pd.DataFrame:
    """Filter dataframe rows using pandas query"""
    # add quotes around dates so that query works
    safe_expr = _DATE_RE.sub(lambda m: f"'{m.group(0)}'", expr)

    # rewrite "contains" to an expression understood by "qeury"
    def _rewrite_contains(match: "re.Match[str]") -> str:
        column, substring, case = (
            match.group(1),
            match.group(2),
            match.group(3) or "False",
        )
        return f"{column}.astype('string').str.contains({substring}, case={case}, na=False, regex=False)"

    safe_expr = _CONTAINS_RE.sub(_rewrite_contains, safe_expr)

    try:
        return df.query(safe_expr, engine="python")
    except Exception as exc:  # pandas raises several different error types
        print(f"Error evaluating row filter '{expr}': {exc}", file=sys.stderr)
        sys.exit(1)


_ALLOWED_AGG_FUNCS = {
    "sum",
    "mean",
    "median",
    "min",
    "max",
    "count",
    "std",
    "var",
    "nunique",
    "first",
    "last",
}


def parse_agg_spec(specs: list[str], columns: list[str]) -> dict[str, tuple[str, str]]:
    """Parse a list of 'column:function' strings into {out col: (column, function)}."""
    agg_map: dict[str, tuple[str, str]] = {}

    for spec in specs:
        if ":" not in spec:
            print(
                f"Invalid aggregation '{spec}', expected COLUMN:FUNCTION "
                f"(e.g. 'price:sum')",
                file=sys.stderr,
            )
            sys.exit(1)

        col_part, _, func_part = spec.partition(":")
        func = func_part.strip().lower()

        resolved = cols_select([col_part.strip()], columns)
        if not resolved:
            print(
                f"Unknown column '{col_part}' in aggregation '{spec}'", file=sys.stderr
            )
            sys.exit(1)
        col = resolved[0]

        if func not in _ALLOWED_AGG_FUNCS:
            print(
                f"Unsupported aggregation function '{func}'. Choose from: {', '.join(sorted(_ALLOWED_AGG_FUNCS))}",
                file=sys.stderr,
            )
            sys.exit(1)

        # Build a unique output column name, e.g. price_sum, price_sum2, ...
        out_name = f"{col}_{func}"
        suffix = 1
        base = out_name
        while out_name in agg_map:
            suffix += 1
            out_name = f"{base}{suffix}"
        agg_map[out_name] = (col, func)

    return agg_map


def aggregate(
    df: pd.DataFrame, group_cols: Optional[list[str]], agg_specs: list[str]
) -> pd.DataFrame:
    """Group df by group_cols (if any) and apply column:function aggregations."""
    agg_map = parse_agg_spec(agg_specs, df.columns.tolist())
    named_aggs = {
        name: pd.NamedAgg(column=col, aggfunc=func)
        for name, (col, func) in agg_map.items()
    }

    if group_cols:
        resolved_groups = cols_select(group_cols, df.columns.tolist())
        if not resolved_groups:
            print(f"No valid group-by columns found in {group_cols}", file=sys.stderr)
            sys.exit(1)
        result = df.groupby(resolved_groups, dropna=False).agg(**named_aggs)
        return result.reset_index()

    # No grouping: aggregate the whole dataframe into a single summary row.
    values = {name: getattr(df[col], func)() for name, (col, func) in agg_map.items()}
    return pd.DataFrame([values])


def main():
    """Main entry point"""
    parser = ArgumentParser(
        prog="csv-util",
        description="A CLI utility to deal with CSV (and related) files.",
    )

    parser.add_argument("file", metavar="FILE", help='Input file, use "-" for stdin.')

    filter_args = parser.add_argument_group("Filter arguments")
    filter_args.add_argument(
        "-c",
        "--columns",
        help="Select columns using a comma separated list. Elements can be column names or indices (starting as 0)",
        type=args_comma_separated_list,
        default=None,
    )
    filter_args.add_argument(
        "-r",
        "--rows",
        help=(
            "Filter rows using a boolean expression, e.g. 'Date > 2026-01-01 & Transaction >= 0.0'. Use 'contains(Column, 'text')' for substring match. This is a wrapper around pandas 'query()' "
        ),
        default=None,
    )

    trans_args = parser.add_argument_group("Transformation arguments")
    trans_args.add_argument(
        "--sort",
        help="Sort csv file based on comma separated list of columns. Elements can be column names or indices (starting as 0)",
        type=args_comma_separated_list,
        default=None,
    )
    trans_args.add_argument(
        "--sort-dir",
        help="Sort direction. A list of 'a' (ascending) or 'd' (descending). Default ascending",
        type=args_comma_separated_list,
        default=["a"],
    )
    trans_args.add_argument(
        "--sample",
        help="Re-sample on a time/date based column. Argument is <column>:<freq>, where 'freq' is accepted by pandas resample()",
        default=None,
    )
    trans_args.add_argument(
        "--pivot",
        help="Create a pivot table. Argument is <rows>:<cols>:<vals>:<func>, where '<rows>' are the columns the rows in the pivot table are taking from, '<cols>' are the columns the columns in the pivot table are taken from, '<vals>' are the columns the values are taken from, and 'func' is the aggregation function.<rows>, <cols>, <vals> can be comma separated lists ",
        default=None,
    )
    trans_args.add_argument(
        "--group",
        help="Group rows by comma separated list of columns (names or indices) before aggregating. Requires --agg.",
        type=args_comma_separated_list,
        default=None,
    )
    trans_args.add_argument(
        "--agg",
        help=(
            "Aggregate using a comma separated list of COLUMN:FUNCTION pairs, e.g. 'price:sum,price:mean'. Combine with --group-by to aggregate per group. Functions: "
            + ", ".join(sorted(_ALLOWED_AGG_FUNCS))
        ),
        type=args_comma_separated_list,
        default=None,
    )

    out_args = parser.add_argument_group("Output arguments")
    out_args.add_argument(
        "-f",
        "--format",
        help="Output format",
        choices=["csv", "txt", "tsv", "md"],
        default="txt",
    )

    args = parser.parse_args()

    if args.file == "-":
        args.file = io.StringIO(sys.stdin.read())

    df = pd.read_csv(args.file, skip_blank_lines=True)

    # Attempt to convert to datetime
    for col in df.columns:
        df[col] = try_datetime(df[col])

    #
    # Filtering
    #
    if args.columns is not None:
        selected = cols_select(args.columns, df.columns.tolist())
        if len(selected) > 0:
            df = df[selected]

    if args.rows is not None:
        df = filter_rows(df, args.rows)

    #
    # Transform
    #
    if args.sort is not None:
        selected = cols_select(args.sort, df.columns.tolist())
        if len(selected) > 0:
            order = []
            for i in range(len(selected)):
                dir_value = (
                    args.sort_dir[i] if i < len(args.sort_dir) else args.sort_dir[-1]
                )
                order.append("a" in dir_value)
            df.sort_values(by=selected, ascending=order, inplace=True)

    if args.sample is not None:
        col, freq = args.sample.split(":")
        df = df.resample(freq, on=col).last().reset_index()

    if args.pivot is not None:
        rows, cols, vals, func = args.pivot.split(":")
        df = df.pivot_table(
            index=rows.split(","),
            columns=cols.split(","),
            values=vals.split(","),
            aggfunc=func,
        ).reset_index()

    if args.group is not None and args.agg is None:
        print("--group requires --agg to specify how to aggregate", file=sys.stderr)
        sys.exit(1)

    if args.agg is not None:
        df = aggregate(df, args.group, args.agg)

    #
    # Output
    #
    if args.format == "csv":
        print(df.to_csv(index=False))
    elif args.format == "tsv":
        print(df.to_csv(index=False, sep="\t"))
    elif args.format == "txt":
        print(df.to_string(index=False))
    elif args.format == "md":
        print(df.to_markdown(index=False))


if __name__ == "__main__":
    main()
