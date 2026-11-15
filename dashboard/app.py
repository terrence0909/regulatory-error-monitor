"""
Regulatory Error Monitor: dashboard (phase 8).

Reads the finished tables (marts schema) and the audit log. It never touches raw data.
Run it with:   docker compose up -d dashboard       then open http://localhost:8501
Or without Docker:   streamlit run dashboard/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import query  # noqa: E402

st.set_page_config(page_title="Regulatory Error Monitor", layout="wide")

MIN_QUALITY = 97  # keep in step with min_quality_score in dbt_project/dbt_project.yml
LEVEL_ORDER = ["Critical", "Error", "Warning"]
AGE_LABELS = ["0 to 1 days", "2 to 3 days", "4 to 7 days", "8 to 14 days", "15 days or more"]
AGE_BINS = [-1, 1, 3, 7, 14, 10**6]


# --------------------------------------------------------------------------
# Loading data (cached for 5 minutes so the page stays quick)
# --------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner="Loading data...")
def load_facts() -> pd.DataFrame:
    df = query("""
        select f.validation_error_key, f.created_at::date as created_date,
               f.error_version_key, f.entity_code, e.entity_name,
               r.rule_code, r.rule_name, r.rule_category,
               d.error_code, d.error_description, d.error_level, d.error_type,
               f.is_open, f.days_to_clear, f.batch_date
        from marts.fact_validation_error f
        join marts.dim_error d on d.error_version_key = f.error_version_key
        join marts.dim_rule r on r.rule_key = f.rule_key
        join marts.dim_reporting_entity e on e.entity_code = f.entity_code
    """)
    df["created_date"] = pd.to_datetime(df["created_date"])
    df["batch_date"] = pd.to_datetime(df["batch_date"])
    df["days_to_clear"] = pd.to_numeric(df["days_to_clear"], errors="coerce")
    df["is_open"] = df["is_open"].astype(bool)
    return df


@st.cache_data(ttl=300)
def load_error_versions() -> pd.DataFrame:
    return query("""
        select error_version_key, error_code, error_description, error_level, error_type,
               response, valid_from, valid_to
        from marts.dim_error order by error_code, valid_from
    """)


@st.cache_data(ttl=300)
def load_quality() -> pd.DataFrame:
    df = query("select batch_date, rows_read, rows_loaded, rows_rejected, quality_score_pct "
               "from marts.dq_daily_score order by batch_date")
    df["batch_date"] = pd.to_datetime(df["batch_date"])
    return df


@st.cache_data(ttl=300)
def load_rejections() -> pd.DataFrame:
    df = query("select batch_date, reason, rows_rejected from marts.dq_rejections_by_reason")
    df["batch_date"] = pd.to_datetime(df["batch_date"])
    return df


@st.cache_data(ttl=300)
def load_test_history():
    """Saved dbt results. Empty if the pipeline has not recorded any yet."""
    try:
        runs = query("select recorded_at, command, tests_total, tests_passed, tests_warned, tests_failed "
                     "from audit.dbt_runs order by recorded_at desc limit 15")
        problems = query("""
            select test_name, model_name, severity, status, failing_rows
            from audit.test_results
            where run_id = (select run_id from audit.dbt_runs order by recorded_at desc limit 1)
              and status <> 'pass'
            order by status, test_name
        """)
        return runs, problems
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def bars(df, value, label, title, height=320):
    chart = (alt.Chart(df).mark_bar()
             .encode(x=alt.X(f"{value}:Q", title=title),
                     y=alt.Y(f"{label}:N", sort="-x", title=None),
                     tooltip=list(df.columns))
             .properties(height=height))
    st.altair_chart(chart, width="stretch")


def pct(part, whole):
    return 0.0 if whole == 0 else 100.0 * part / whole


# --------------------------------------------------------------------------
# Page header and filters
# --------------------------------------------------------------------------
facts = load_facts()
if facts.empty:
    st.title("Regulatory Error Monitor")
    st.warning("No data yet. Run the pipeline first (see the README), then refresh this page.")
    st.stop()

as_of = facts["batch_date"].max()
st.title("Regulatory Error Monitor")
st.caption(f"Data as of {as_of:%d %B %Y}. All data in this project is generated: it has the shape "
           "of a regulatory reporting system, but nothing in it is real.")

st.sidebar.header("Filters")
first_day, last_day = facts["created_date"].min().date(), facts["created_date"].max().date()
picked = st.sidebar.date_input("Errors created between", value=(first_day, last_day),
                               min_value=first_day, max_value=last_day)
start, end = (picked[0], picked[1]) if isinstance(picked, (tuple, list)) and len(picked) == 2 \
    else (first_day, last_day)
all_entities = sorted(facts["entity_code"].unique())
entities = st.sidebar.multiselect("Reporting entity", all_entities, default=all_entities)
levels = st.sidebar.multiselect("Severity", LEVEL_ORDER, default=LEVEL_ORDER)
st.sidebar.caption("Filters apply to every tab except Definition history and Data quality.")

by_entity_level = facts[facts["entity_code"].isin(entities) & facts["error_level"].isin(levels)]
f = by_entity_level[(by_entity_level["created_date"] >= pd.Timestamp(start))
                    & (by_entity_level["created_date"] <= pd.Timestamp(end))]

tab_names = ["Overview", "Top failing rules", "Reporting entities", "Trends",
             "Error ageing", "Definition history", "Data quality"]
t_over, t_rules, t_ent, t_trend, t_age, t_hist, t_dq = st.tabs(tab_names)

# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------
with t_over:
    if f.empty:
        st.info("No errors match these filters.")
    else:
        last7 = by_entity_level[by_entity_level["created_date"] > as_of - pd.Timedelta(days=7)]
        prev7 = by_entity_level[(by_entity_level["created_date"] <= as_of - pd.Timedelta(days=7))
                                & (by_entity_level["created_date"] > as_of - pd.Timedelta(days=14))]
        open_now = int(f["is_open"].sum())
        cleared = f[~f["is_open"]]
        quality = load_quality()

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Errors in period", f"{len(f):,}")
        c2.metric("Last 7 days", f"{len(last7):,}",
                  delta=f"{len(last7) - len(prev7):+,} vs the 7 days before", delta_color="inverse")
        c3.metric("Still open", f"{open_now:,}", help=f"{pct(open_now, len(f)):.1f}% of errors in the period")
        c4.metric("Median days to clear",
                  "n/a" if cleared.empty else f"{cleared['days_to_clear'].median():.0f}")
        c5.metric("Latest quality score",
                  "n/a" if quality.empty else f"{quality['quality_score_pct'].iloc[-1]:.1f}%")

        st.subheader("What stands out")
        top_rule = f.groupby(["rule_code", "rule_name"]).size().sort_values(ascending=False)
        top_entity = f.groupby(["entity_code", "entity_name"]).size().sort_values(ascending=False)
        critical = pct((f["error_level"] == "Critical").sum(), len(f))
        (rc, rn), rule_n = top_rule.index[0], top_rule.iloc[0]
        (ec, en), ent_n = top_entity.index[0], top_entity.iloc[0]
        st.markdown(
            f"- **{rc} ({rn})** is the rule that fails most: {rule_n:,} errors, {pct(rule_n, len(f)):.1f}% of the total.\n"
            f"- **{en}** raises the most errors: {ent_n:,}, which is {pct(ent_n, len(f)):.1f}% of the total "
            f"(an even share across {f['entity_code'].nunique()} entities would be {100 / f['entity_code'].nunique():.1f}%).\n"
            f"- **{critical:.1f}%** of errors are Critical.")

# --------------------------------------------------------------------------
# Top failing rules
# --------------------------------------------------------------------------
with t_rules:
    if f.empty:
        st.info("No errors match these filters.")
    else:
        ordered = f.sort_values("created_date")
        rules = (ordered.groupby(["rule_code", "rule_category"])
                 .agg(rule_name=("rule_name", "last"), errors=("validation_error_key", "count"))
                 .reset_index().sort_values("errors", ascending=False))
        rules["share_pct"] = (100 * rules["errors"] / rules["errors"].sum()).round(1)
        rules["label"] = rules["rule_code"] + "  " + rules["rule_name"]

        st.subheader("Which rules fail the most?")
        bars(rules.head(10)[["label", "errors"]], "errors", "label", "Errors")
        st.dataframe(rules[["rule_code", "rule_name", "rule_category", "errors", "share_pct"]],
                     hide_index=True, width="stretch")

        st.subheader("Which error codes come up most?")
        codes = (ordered.groupby("error_code")
                 .agg(description=("error_description", "last"), level=("error_level", "last"),
                      errors=("validation_error_key", "count"))
                 .reset_index().sort_values("errors", ascending=False))
        st.dataframe(codes.head(15), hide_index=True, width="stretch")

# --------------------------------------------------------------------------
# Reporting entities
# --------------------------------------------------------------------------
with t_ent:
    if f.empty:
        st.info("No errors match these filters.")
    else:
        ents = (f.groupby(["entity_code", "entity_name"])
                .agg(errors=("validation_error_key", "count"), still_open=("is_open", "sum"),
                     median_days_to_clear=("days_to_clear", "median"),
                     critical=("error_level", lambda s: (s == "Critical").sum()))
                .reset_index().sort_values("errors", ascending=False))
        ents["critical_pct"] = (100 * ents["critical"] / ents["errors"]).round(1)
        ents["share_pct"] = (100 * ents["errors"] / ents["errors"].sum()).round(1)
        ents["median_days_to_clear"] = ents["median_days_to_clear"].round(1)

        st.subheader("Who produces the most errors?")
        bars(ents[["entity_name", "errors"]], "errors", "entity_name", "Errors")
        st.dataframe(ents[["entity_code", "entity_name", "errors", "share_pct", "still_open",
                           "median_days_to_clear", "critical_pct"]], hide_index=True, width="stretch")
        st.caption("Slow clearing shows up in 'still open' and 'median days to clear'.")

# --------------------------------------------------------------------------
# Trends
# --------------------------------------------------------------------------
with t_trend:
    if f.empty:
        st.info("No errors match these filters.")
    else:
        split = st.radio("Split by", ["Nothing", "Severity", "Entity (top 5)"], horizontal=True)
        data, colour = f, None
        if split == "Severity":
            colour = "error_level"
        elif split == "Entity (top 5)":
            top5 = f["entity_code"].value_counts().head(5).index
            data, colour = f[f["entity_code"].isin(top5)], "entity_name"
        keys = ["created_date"] + ([colour] if colour else [])
        daily = data.groupby(keys).size().reset_index(name="errors")
        enc = dict(x=alt.X("created_date:T", title="Day created"), y=alt.Y("errors:Q", title="Errors"),
                   tooltip=keys + ["errors"])
        if colour:
            enc["color"] = alt.Color(f"{colour}:N", title=None)
        st.subheader("Errors per day")
        st.altair_chart(alt.Chart(daily).mark_line(point=True).encode(**enc).properties(height=360),
                        width="stretch")
        st.caption("Weekends are quieter because fewer payments are reported.")

# --------------------------------------------------------------------------
# Error ageing
# --------------------------------------------------------------------------
with t_age:
    if f.empty:
        st.info("No errors match these filters.")
    else:
        open_df = f[f["is_open"]].copy()
        st.subheader(f"How old are the open errors? (counted up to {as_of:%d %B %Y})")
        if open_df.empty:
            st.success("Nothing is open.")
        else:
            open_df["age_days"] = (as_of - open_df["created_date"]).dt.days
            open_df["age"] = pd.cut(open_df["age_days"], bins=AGE_BINS, labels=AGE_LABELS)
            buckets = open_df["age"].value_counts(sort=False).reset_index()
            buckets.columns = ["age", "open_errors"]
            chart = (alt.Chart(buckets).mark_bar()
                     .encode(x=alt.X("age:N", sort=AGE_LABELS, title=None),
                             y=alt.Y("open_errors:Q", title="Open errors"), tooltip=["age", "open_errors"])
                     .properties(height=300))
            st.altair_chart(chart, width="stretch")
            st.markdown("**The 20 oldest open errors**")
            oldest = open_df.sort_values("age_days", ascending=False).head(20)
            st.dataframe(oldest[["created_date", "age_days", "entity_name", "rule_code", "error_code",
                                 "error_description", "error_level"]], hide_index=True, width="stretch")

        st.subheader("How long do errors take to clear?")
        done = f[~f["is_open"]]
        if done.empty:
            st.info("No cleared errors in this selection.")
        else:
            days = done["days_to_clear"].clip(upper=14).astype(int).value_counts().sort_index().reset_index()
            days.columns = ["days_to_clear", "errors"]
            days["days_to_clear"] = days["days_to_clear"].map(lambda d: "14 or more" if d >= 14 else str(d))
            chart = (alt.Chart(days).mark_bar()
                     .encode(x=alt.X("days_to_clear:N", title="Days from created to cleared",
                                     sort=list(days["days_to_clear"])),
                             y=alt.Y("errors:Q", title="Errors"), tooltip=["days_to_clear", "errors"])
                     .properties(height=300))
            st.altair_chart(chart, width="stretch")
            st.caption(f"Median {done['days_to_clear'].median():.0f} days, "
                       f"average {done['days_to_clear'].mean():.1f} days.")

# --------------------------------------------------------------------------
# Definition history
# --------------------------------------------------------------------------
with t_hist:
    st.subheader("What did an error code say on a given day?")
    st.write("Error codes can be reworded over time. Every error is linked to the version that was "
             "valid on the day it was created, so old reports never change.")
    versions = load_error_versions()
    counts = facts.groupby("error_version_key").size().rename("errors_raised").reset_index()
    versions = versions.merge(counts, on="error_version_key", how="left").fillna({"errors_raised": 0})
    versions["errors_raised"] = versions["errors_raised"].astype(int)
    versions["valid_from"] = versions["valid_from"].map(lambda d: d.isoformat())
    versions["valid_to"] = versions["valid_to"].map(lambda d: "still current" if d.year == 9999 else d.isoformat())

    per_code = versions.groupby("error_code").size()
    changed = sorted(per_code[per_code > 1].index)
    st.markdown(f"**{len(changed)} of {len(per_code)} error codes have been changed.**")
    if changed:
        code = st.selectbox("Pick a changed error code", changed)
        shown = versions[versions["error_code"] == code]
        st.dataframe(shown[["valid_from", "valid_to", "error_level", "error_description",
                            "response", "errors_raised"]], hide_index=True, width="stretch")
    with st.expander("See every version of every code"):
        st.dataframe(versions.drop(columns=["error_version_key"]), hide_index=True, width="stretch")

# --------------------------------------------------------------------------
# Data quality
# --------------------------------------------------------------------------
with t_dq:
    quality = load_quality()
    st.subheader("Can we trust today's numbers?")
    if quality.empty:
        st.info("No quality data yet.")
    else:
        latest = quality.iloc[-1]
        below = int((quality["quality_score_pct"] < MIN_QUALITY).sum())
        q1, q2, q3 = st.columns(3)
        q1.metric("Latest quality score", f"{latest['quality_score_pct']:.1f}%")
        q2.metric("Rows rejected on the latest day", f"{int(latest['rows_rejected']):,}")
        q3.metric(f"Days below {MIN_QUALITY}%", f"{below}")

        line = alt.Chart(quality).mark_line(point=True).encode(
            x=alt.X("batch_date:T", title="Day"),
            y=alt.Y("quality_score_pct:Q", title="Quality score (%)", scale=alt.Scale(zero=False)),
            tooltip=["batch_date", "rows_read", "rows_rejected", "quality_score_pct"])
        rule = alt.Chart(pd.DataFrame({"y": [MIN_QUALITY]})).mark_rule(strokeDash=[6, 4], color="red").encode(y="y:Q")
        st.altair_chart((line + rule).properties(height=320), width="stretch")
        st.caption(f"The dashed line is the warning threshold ({MIN_QUALITY}%). "
                   "Score = rows that passed every check, divided by rows read.")

        reasons = load_rejections()
        if not reasons.empty:
            st.markdown("**Why rows were rejected**")
            chart = (alt.Chart(reasons).mark_bar()
                     .encode(x=alt.X("batch_date:T", title="Day"),
                             y=alt.Y("rows_rejected:Q", title="Rows rejected"),
                             color=alt.Color("reason:N", title=None, legend=alt.Legend(orient="bottom", columns=1)),
                             tooltip=["batch_date", "reason", "rows_rejected"])
                     .properties(height=340))
            st.altair_chart(chart, width="stretch")

    runs, problems = load_test_history()
    st.subheader("Automated tests")
    if runs.empty:
        st.info("No test results saved yet. Run the pipeline with run_build.sh or Airflow.")
    else:
        last = runs.iloc[0]
        t1, t2, t3 = st.columns(3)
        t1.metric("Passed in the latest run", f"{int(last['tests_passed'])} of {int(last['tests_total'])}")
        t2.metric("Warnings", f"{int(last['tests_warned'])}")
        t3.metric("Failures", f"{int(last['tests_failed'])}")
        if problems.empty:
            st.success("Every test passed in the latest run.")
        else:
            st.markdown("**Tests that did not pass in the latest run**")
            st.dataframe(problems, hide_index=True, width="stretch")
        with st.expander("Recent runs"):
            st.dataframe(runs, hide_index=True, width="stretch")
