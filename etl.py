import pandas as pd
import re
from datetime import datetime
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
CSV_PATH = "outreach_calls_sample_2.csv"  # update this path if needed

engine = create_engine(DATABASE_URL)

# ─────────────────────────────────────────────
# DISPOSITION MAP
# ─────────────────────────────────────────────

disposition_map = {
    # No Answer
    "no answer": "No Answer",
    "no-answer": "No Answer",
    # Other
    "na": "Other",
    # Reached
    "spoke w/ patient": "Reached",
    "answered": "Reached",
    "connected": "Reached",
    "reached - scheduled": "Reached",
    # Spoke with Family
    "spoke w/ family": "Spoke with Family",
    # Not Reached
    "disconnected": "Not Reached",
    "busy": "Not Reached",
    "busy signal": "Not Reached",
    # Callback Requested
    "callback requested": "Callback Requested",
    # Wrong Number
    "wrong #": "Wrong Number",
    "wrong number": "Wrong Number",
    # Voicemail
    "voicemail": "Voicemail",
    "vm": "Voicemail",
    "left vm": "Voicemail",
}

# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def parse_call_time(value):
    """Parse mixed date formats including 2-digit years, returning UTC timestamp."""
    if pd.isna(value) or str(value).strip() == "":
        return None
    value = str(value).strip()

    if value.endswith("Z"):
        try:
            dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            return pd.Timestamp(dt, tz="UTC")
        except:
            pass

    formats = [
        "%Y-%m-%d %H:%M:%S",     # 2026-05-13 09:11:00
        "%d-%b-%Y %H:%M",         # 26-May-2026 15:58
        "%m/%d/%Y %I:%M %p",      # 06/04/2026 09:21 PM
        "%m/%d/%Y %H:%M",         # 06/04/2026 21:21
        "%m/%d/%y %H:%M",         # 05/29/26 01:42 (2-digit year)
        "%m/%d/%y %I:%M %p",      # 05/29/26 01:42 PM (2-digit year with AM/PM)
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            return pd.Timestamp(dt).tz_localize("UTC")
        except:
            continue
    return None

def convert_duration(value):
    """Convert duration to integer seconds. Handles mm:ss, plain numbers, and empty values."""
    if pd.isna(value) or str(value).strip() == "":
        return None
    value = str(value).strip()
    if ":" in value:
        parts = value.split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except:
            return None
    try:
        return int(float(value))
    except:
        return None

def normalize_phone(value):
    """Strip all non-digit characters, then normalize to 10 digits by removing leading 1."""
    if pd.isna(value) or str(value).strip() == "":
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return digits
    return None

def normalize_disposition(value):
    """Lowercase and map disposition to standard label."""
    if pd.isna(value) or str(value).strip() == "":
        return None
    return disposition_map.get(str(value).strip().lower(), str(value).strip())

# ─────────────────────────────────────────────
# STEP 1 — EXTRACT
# ─────────────────────────────────────────────

print("Reading CSV...")
df_raw = pd.read_csv(CSV_PATH, dtype=str)
print(f"  {len(df_raw)} rows loaded")

# ─────────────────────────────────────────────
# STEP 2 — LOAD RAW DATA (accumulative, no truncate)
# ─────────────────────────────────────────────

print("Loading raw data...")

raw_inserted = 0
raw_skipped = 0

with engine.begin() as conn:
    for _, row in df_raw.iterrows():
        # Check if exact same raw row already exists
        result = conn.execute(text("""
            SELECT 1 FROM raw_calls
            WHERE call_id IS NOT DISTINCT FROM :call_id
            AND coordinator IS NOT DISTINCT FROM :coordinator
            AND patient_id IS NOT DISTINCT FROM :patient_id
            AND phone IS NOT DISTINCT FROM :phone
            AND call_time IS NOT DISTINCT FROM :call_time
            AND duration_sec IS NOT DISTINCT FROM :duration_sec
            AND disposition IS NOT DISTINCT FROM :disposition
            AND notes IS NOT DISTINCT FROM :notes
        """), {
            "call_id": row["call_id"] if pd.notna(row["call_id"]) else None,
            "coordinator": row["coordinator"] if pd.notna(row["coordinator"]) else None,
            "patient_id": row["patient_id"] if pd.notna(row["patient_id"]) else None,
            "phone": row["phone"] if pd.notna(row["phone"]) else None,
            "call_time": row["call_time"] if pd.notna(row["call_time"]) else None,
            "duration_sec": row["duration_sec"] if pd.notna(row["duration_sec"]) else None,
            "disposition": row["disposition"] if pd.notna(row["disposition"]) else None,
            "notes": row["notes"] if pd.notna(row["notes"]) else None,
        })
        if result.fetchone():
            raw_skipped += 1
            continue

        conn.execute(text("""
            INSERT INTO raw_calls (call_id, coordinator, patient_id, phone, call_time, duration_sec, disposition, notes)
            VALUES (:call_id, :coordinator, :patient_id, :phone, :call_time, :duration_sec, :disposition, :notes)
        """), {
            "call_id": row["call_id"] if pd.notna(row["call_id"]) else None,
            "coordinator": row["coordinator"] if pd.notna(row["coordinator"]) else None,
            "patient_id": row["patient_id"] if pd.notna(row["patient_id"]) else None,
            "phone": row["phone"] if pd.notna(row["phone"]) else None,
            "call_time": row["call_time"] if pd.notna(row["call_time"]) else None,
            "duration_sec": row["duration_sec"] if pd.notna(row["duration_sec"]) else None,
            "disposition": row["disposition"] if pd.notna(row["disposition"]) else None,
            "notes": row["notes"] if pd.notna(row["notes"]) else None,
        })
        raw_inserted += 1

print(f"  Raw rows inserted: {raw_inserted}")
print(f"  Raw rows skipped (already exist): {raw_skipped}")

# ─────────────────────────────────────────────
# STEP 3 — TRANSFORM
# ─────────────────────────────────────────────

print("Transforming data...")

df = df_raw.copy()
df["duration_sec"] = df["duration_sec"].apply(convert_duration)
df["phone"] = df["phone"].apply(normalize_phone)
df["call_time"] = df["call_time"].apply(parse_call_time)
df["disposition"] = df["disposition"].apply(normalize_disposition)

for col in ["call_id", "coordinator", "patient_id", "notes"]:
    df[col] = df[col].str.strip()

df["call_time_str"] = df["call_time"].astype(str)

# ─────────────────────────────────────────────
# STEP 4 — SEPARATE TRUE DUPLICATES FIRST
# ─────────────────────────────────────────────

print("Detecting true duplicates...")

all_cols = ["call_id", "coordinator", "patient_id", "phone", "call_time_str", "duration_sec", "disposition", "notes"]

duplicate_mask = df.duplicated(subset=all_cols, keep="first")
true_duplicates_df = df[duplicate_mask].copy()
true_duplicates_df["flag"] = "True duplicate"

df_deduped = df[~duplicate_mask].copy()

print(f"  True duplicates removed from working set: {duplicate_mask.sum()}")
print(f"  Rows remaining after dedup: {len(df_deduped)}")

# ─────────────────────────────────────────────
# STEP 5 — FLAG ISSUES ON DEDUPLICATED SET
# ─────────────────────────────────────────────

print("Flagging issues...")

df_deduped["flag"] = None

# --- Flag: empty required fields ---
empty_mask = (
    df_deduped["call_id"].isna() |
    df_deduped["coordinator"].isna() |
    df_deduped["patient_id"].isna() |
    df_deduped["phone"].isna() |
    df_deduped["call_time"].isna() |
    df_deduped["duration_sec"].isna()
)
df_deduped.loc[empty_mask & df_deduped["flag"].isna(), "flag"] = "Empty required field"

# --- Flag: negative duration ---
negative_mask = df_deduped["duration_sec"].notna() & (df_deduped["duration_sec"] < 0)
df_deduped.loc[negative_mask & df_deduped["flag"].isna(), "flag"] = "Negative duration"

# --- Flag: duration exceeds maximum threshold (3600 seconds = 1 hour) ---
max_duration_mask = df_deduped["duration_sec"].notna() & (df_deduped["duration_sec"] > 3600)
df_deduped.loc[max_duration_mask & df_deduped["flag"].isna(), "flag"] = "Duration exceeds maximum threshold"

# --- Flag: duplicate call_id with conflicting values (last, only flags otherwise clean rows) ---
conflict_mask = df_deduped[df_deduped["flag"].isna()].duplicated(subset=["call_id"], keep=False)
conflict_index = df_deduped[df_deduped["flag"].isna()][conflict_mask].index
df_deduped.loc[conflict_index, "flag"] = "Duplicate call_id with conflicting values"

# ─────────────────────────────────────────────
# STEP 6 — SPLIT INTO CLEAN AND FLAGGED
# ─────────────────────────────────────────────

clean_df = df_deduped[df_deduped["flag"].isna()].copy()
flagged_df = pd.concat([
    df_deduped[df_deduped["flag"].notna()],
    true_duplicates_df
], ignore_index=True)

print(f"  Clean rows:        {len(clean_df)}")
print(f"  Flagged rows:      {len(flagged_df)}")
print(f"  True duplicates:   {len(true_duplicates_df)}")

# ─────────────────────────────────────────────
# STEP 7 — LOAD CLEAN AND FLAGGED DATA (accumulative, no truncate)
# ─────────────────────────────────────────────

print("Loading into database...")

with engine.begin() as conn:

    # --- Upsert coordinators ---
    coordinators = clean_df[["coordinator"]].dropna().drop_duplicates()
    for _, row in coordinators.iterrows():
        conn.execute(text("""
            INSERT INTO coordinators (name)
            VALUES (:name)
            ON CONFLICT (name) DO NOTHING
        """), {"name": row["coordinator"]})
    print(f"  Coordinators upserted: {len(coordinators)}")

    # --- Upsert patients ---
    patients = (
        clean_df[["patient_id", "phone"]]
        .dropna(subset=["patient_id"])
        .sort_values("phone")
        .drop_duplicates(subset=["patient_id"], keep="last")
    )
    for _, row in patients.iterrows():
        conn.execute(text("""
            INSERT INTO patients (patient_id, phone)
            VALUES (:patient_id, :phone)
            ON CONFLICT (patient_id) DO UPDATE SET phone = EXCLUDED.phone
        """), {"patient_id": row["patient_id"], "phone": row["phone"]})
    print(f"  Patients upserted: {len(patients)}")

    # --- Insert clean calls ---
    calls_inserted = 0
    calls_skipped = 0
    for _, row in clean_df.iterrows():
        result = conn.execute(text("""
            SELECT id FROM coordinators WHERE name = :name
        """), {"name": row["coordinator"]})
        coord_row = result.fetchone()
        coordinator_id = coord_row[0] if coord_row else None

        result = conn.execute(text("""
            INSERT INTO calls (call_id, coordinator_id, patient_id, call_time, duration_sec, disposition, notes)
            VALUES (:call_id, :coordinator_id, :patient_id, :call_time, :duration_sec, :disposition, :notes)
            ON CONFLICT (call_id) DO NOTHING
            RETURNING call_id
        """), {
            "call_id": row["call_id"],
            "coordinator_id": coordinator_id,
            "patient_id": row["patient_id"] if pd.notna(row["patient_id"]) else None,
            "call_time": row["call_time"],
            "duration_sec": int(row["duration_sec"]) if pd.notna(row["duration_sec"]) else None,
            "disposition": row["disposition"] if pd.notna(row["disposition"]) else None,
            "notes": row["notes"] if pd.notna(row["notes"]) else None,
        })
        if result.fetchone():
            calls_inserted += 1
        else:
            calls_skipped += 1
    print(f"  Calls inserted: {calls_inserted}")
    print(f"  Calls skipped (already exist): {calls_skipped}")

    # --- Insert flagged rows (skip if same call_id and flag_reason already exist) ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS call_logs_flagged (
            id SERIAL PRIMARY KEY,
            call_id VARCHAR(50),
            coordinator VARCHAR(100),
            patient_id VARCHAR(50),
            phone VARCHAR(20),
            call_time TIMESTAMP WITH TIME ZONE,
            duration_sec INT,
            disposition VARCHAR(100),
            notes TEXT,
            flag_reason TEXT
        )
    """))
    flagged_inserted = 0
    flagged_skipped = 0
    for _, row in flagged_df.iterrows():
        # Check if same call_id and flag_reason already exists
        existing = conn.execute(text("""
            SELECT 1 FROM call_logs_flagged
            WHERE call_id IS NOT DISTINCT FROM :call_id
            AND flag_reason IS NOT DISTINCT FROM :flag_reason
        """), {
            "call_id": row["call_id"] if pd.notna(row["call_id"]) else None,
            "flag_reason": row["flag"],
        })
        if existing.fetchone():
            flagged_skipped += 1
            continue

        conn.execute(text("""
            INSERT INTO call_logs_flagged
            (call_id, coordinator, patient_id, phone, call_time, duration_sec, disposition, notes, flag_reason)
            VALUES
            (:call_id, :coordinator, :patient_id, :phone, :call_time, :duration_sec, :disposition, :notes, :flag_reason)
        """), {
            "call_id": row["call_id"] if pd.notna(row["call_id"]) else None,
            "coordinator": row["coordinator"] if pd.notna(row["coordinator"]) else None,
            "patient_id": row["patient_id"] if pd.notna(row["patient_id"]) else None,
            "phone": row["phone"] if pd.notna(row["phone"]) else None,
            "call_time": row["call_time"] if pd.notna(row["call_time"]) else None,
            "duration_sec": int(row["duration_sec"]) if pd.notna(row["duration_sec"]) else None,
            "disposition": row["disposition"] if pd.notna(row["disposition"]) else None,
            "notes": row["notes"] if pd.notna(row["notes"]) else None,
            "flag_reason": row["flag"],
        })
        flagged_inserted += 1
    print(f"  Flagged rows inserted: {flagged_inserted}")
    print(f"  Flagged rows skipped (already exist): {flagged_skipped}")

print("ETL complete.")