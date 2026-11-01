# File: scripts/ci0_bench/bench_python.py
"""CI.0 part 2 (python side), a throwaway measurement script, not product code: fingerprint cost and reduction timings on a 1M-row, 20-column Parquet frame.
Each method runs in its own process so peak memory is attributable.
Usage: python bench_python.py make | run | method <name> | reductions"""

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROWS = 1_000_000
PATH = os.path.join(tempfile.gettempdir(), "ci0_bench_1m.parquet")


def make(n):
    rng = np.random.default_rng(0)
    c = {}
    for i in range(8):
        c[f"f{i}"] = rng.lognormal(3, 1, n) if i % 2 else rng.normal(0, 1, n)
    for i in range(4):
        c[f"i{i}"] = rng.integers(0, 10 ** (i + 2), n)
    for name, k in (("cat5", 5), ("cat50", 50), ("cat5k", 5000)):
        c[name] = np.array([f"{name}_{j}" for j in range(k)])[rng.integers(0, k, n)]
    c["id"] = np.char.add("u", np.arange(n).astype(str))
    c["ts"] = pd.date_range("2024-01-01", periods=n, freq="min")
    c["ts2"] = pd.Timestamp("2020-01-01") + pd.to_timedelta(
        rng.integers(0, 10**8, n), unit="s"
    )
    c["flag"] = rng.random(n) < 0.1
    c["sparse"] = np.where(rng.random(n) < 0.9, np.nan, rng.normal(size=n))
    return pd.DataFrame(c)


def q(name):
    """Quote an identifier: column names are tenant text."""
    return '"' + name.replace('"', '""') + '"'


def duck():
    con = duckdb.connect(
        ":memory:",
        config={
            "enable_external_access": False,
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        },
    )
    con.execute("SET lock_configuration=true")
    return con


def stats_sql(schema):
    parts = ["count(*) AS n"]
    for f in schema:
        c = q(f.name)
        parts.append(f"count(*) FILTER (WHERE {c} IS NULL) AS {q(f.name + '|nulls')}")
        parts.append(f"approx_count_distinct({c}) AS {q(f.name + '|ndv')}")
        if pa.types.is_floating(f.type) or pa.types.is_integer(f.type):
            parts.append(
                f"min({c}), max({c}), avg({c}), stddev_samp({c}), skewness({c}), "
                f"kurtosis({c}), quantile_cont({c}, [0.25,0.5,0.75])"
            )
        elif pa.types.is_timestamp(f.type):
            parts.append(f"min({c}), max({c})")
    return "SELECT " + ", ".join(parts) + " FROM t"


def pandas_stats(df):
    out = {}
    for c in df.columns:
        s = df[c]
        d = {"nulls": int(s.isna().sum()), "ndv": int(s.nunique())}
        if pd.api.types.is_numeric_dtype(s) and s.dtype != bool:
            d.update(
                min=s.min(),
                max=s.max(),
                mean=s.mean(),
                std=s.std(),
                skew=s.skew(),
                kurt=s.kurt(),
                q=s.quantile([0.25, 0.5, 0.75]).tolist(),
            )
        elif pd.api.types.is_datetime64_any_dtype(s):
            d.update(min=s.min(), max=s.max())
        out[c] = d
    return out


def stream_reader(pf, cols, batch=65536):
    schema = pa.schema([pf.schema_arrow.field(c) for c in cols])
    return pa.RecordBatchReader.from_batches(
        schema, pf.iter_batches(batch_size=batch, columns=cols)
    )


def peak_working_set_bytes():
    """Peak resident memory of this process (Windows working set, elsewhere ru_maxrss), 0 if unknown."""
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as w

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", w.DWORD),
                ("PageFaultCount", w.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        k32, ps = ctypes.windll.kernel32, ctypes.windll.psapi
        k32.GetCurrentProcess.restype = w.HANDLE
        ps.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(PMC), w.DWORD]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        ps.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return pmc.PeakWorkingSetSize
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # KiB on Linux


def run_method(m):
    t0 = time.perf_counter()
    t_read = 0.0
    if m == "pandas_full":
        df = pq.read_table(PATH).to_pandas()
        t_read = time.perf_counter() - t0
        pandas_stats(df)
    elif m == "duckdb_table":
        tbl = pq.read_table(PATH)
        t_read = time.perf_counter() - t0
        con = duck()
        con.register("t", tbl)
        con.execute(stats_sql(tbl.schema)).fetchall()
    elif m == "duckdb_stream":
        pf = pq.ParquetFile(PATH)
        cols = pf.schema_arrow.names
        con = duck()
        con.register("t", stream_reader(pf, cols))
        con.execute(stats_sql(pf.schema_arrow)).fetchall()
    elif m == "stream_sample_pandas":
        pf = pq.ParquetFile(PATH)
        rng = np.random.default_rng(1)
        keep = []
        total = pf.metadata.num_rows
        for b in pf.iter_batches(batch_size=65536):
            k = max(1, round(100_000 * b.num_rows / total))
            idx = rng.choice(b.num_rows, size=min(k, b.num_rows), replace=False)
            keep.append(b.take(pa.array(idx)))
        t_read = time.perf_counter() - t0
        pandas_stats(pa.Table.from_batches(keep).to_pandas())
    elif m == "proj_duckdb_stream":
        pf = pq.ParquetFile(PATH)
        con = duck()
        con.register("t", stream_reader(pf, ["cat50", "f1"]))
        con.execute(
            'SELECT "cat50", sum("f1"), median("f1") FROM t GROUP BY 1'
        ).fetchall()
    elif m == "proj_pandas":
        df = pq.read_table(PATH, columns=["cat50", "f1"]).to_pandas()
        df.groupby("cat50")["f1"].agg(["sum", "median"])
    elif m == "footer_only":
        md = pq.ParquetFile(PATH).metadata
        for rg in range(md.num_row_groups):
            for ci in range(md.num_columns):
                st = md.row_group(rg).column(ci).statistics
                _ = st.min if st is not None and st.has_min_max else None
    total = time.perf_counter() - t0
    peak = pa.default_memory_pool().max_memory()
    ws = peak_working_set_bytes()
    print(
        json.dumps(
            {
                "method": m,
                "total_s": round(total, 2),
                "read_s": round(t_read, 2),
                "arrow_peak_mb": round(peak / 2**20),
                "peak_working_set_mb": round(ws / 2**20) if ws else None,
            }
        )
    )


def med(fn, n=3):
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append(time.perf_counter() - t)
    return round(statistics.median(xs) * 1000)


def reductions():
    tbl = pq.read_table(PATH, columns=["cat50", "f1", "f0", "ts"])
    df = tbl.to_pandas()
    con = duck()
    con.register("t", tbl)
    res = {}
    res["groupby_sum_cat50_pandas_ms"] = med(lambda: df.groupby("cat50")["f1"].sum())
    res["groupby_sum_cat50_duckdb_ms"] = med(
        lambda: con.execute('SELECT "cat50", sum("f1") FROM t GROUP BY 1').fetchall()
    )
    res["groupby_median_cat50_pandas_ms"] = med(
        lambda: df.groupby("cat50")["f1"].median()
    )
    res["groupby_median_cat50_duckdb_ms"] = med(
        lambda: con.execute('SELECT "cat50", median("f1") FROM t GROUP BY 1').fetchall()
    )
    res["hist50_numpy_ms"] = med(lambda: np.histogram(df["f1"].to_numpy(), bins=50))
    res["hist50_duckdb_ms"] = med(
        lambda: con.execute(
            'WITH r AS (SELECT min("f1") lo, max("f1") hi FROM t) '
            'SELECT least(49, floor(("f1"-lo)/((hi-lo)/50)))::INT b, count(*) '
            "FROM t, r GROUP BY 1"
        ).fetchall()
    )
    x = df["ts"].astype("int64").to_numpy() / 1e9
    y = df["f0"].to_numpy()

    def m4_numpy():
        b = np.minimum(((x - x[0]) / (x[-1] - x[0]) * 1250).astype(int), 1249)
        order = np.argsort(b, kind="stable")
        cuts = np.flatnonzero(np.diff(b[order])) + 1
        out = []
        for seg in np.split(order, cuts):
            ys = y[seg]
            out.append((seg[0], seg[-1], seg[ys.argmin()], seg[ys.argmax()]))
        return out

    res["m4_1250buckets_numpy_ms"] = med(m4_numpy)
    res["m4_1250buckets_duckdb_ms"] = med(
        lambda: con.execute(
            'WITH r AS (SELECT min(epoch("ts")) lo, max(epoch("ts")) hi FROM t) '
            'SELECT least(1249, floor((epoch("ts")-lo)/((hi-lo)/1250)))::INT b, '
            'min("ts"), max("ts"), min("f0"), max("f0"), arg_min("f0","ts"), '
            'arg_max("f0","ts") FROM t, r GROUP BY 1'
        ).fetchall()
    )
    a = df.groupby("cat50")["f1"].sum().sort_index()
    d = (
        pd.DataFrame(
            con.execute('SELECT "cat50", sum("f1") FROM t GROUP BY 1').fetchall(),
            columns=["k", "s"],
        )
        .set_index("k")
        .sort_index()["s"]
    )
    res["groupby_sum_max_rel_diff"] = float(
        np.max(np.abs(a.to_numpy() - d.to_numpy()) / np.abs(a.to_numpy()))
    )
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "make":
        t = time.perf_counter()
        frame = make(ROWS)
        pq.write_table(
            pa.Table.from_pandas(frame, preserve_index=False),
            PATH,
            row_group_size=100_000,
        )
        print(
            json.dumps(
                {
                    "rows": ROWS,
                    "cols": frame.shape[1],
                    "file_mb": round(os.path.getsize(PATH) / 2**20, 1),
                    "make_s": round(time.perf_counter() - t, 1),
                    "frame_mem_mb": round(frame.memory_usage(deep=True).sum() / 2**20),
                }
            )
        )
    elif mode == "method":
        run_method(sys.argv[2])
    elif mode == "reductions":
        reductions()
    elif mode == "run":
        for name in (
            "footer_only",
            "pandas_full",
            "duckdb_table",
            "duckdb_stream",
            "stream_sample_pandas",
        ):
            out = subprocess.run(
                [sys.executable, __file__, "method", name],
                capture_output=True,
                text=True,
            )
            print(out.stdout.strip() or out.stderr.strip()[-300:])
        out = subprocess.run(
            [sys.executable, __file__, "reductions"], capture_output=True, text=True
        )
        print(out.stdout.strip() or out.stderr.strip()[-400:])
