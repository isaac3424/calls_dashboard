from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
app = FastAPI()

# Allow Lovable frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────

def query(sql, params=None):
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        rows = result.fetchall()
        keys = result.keys()
        return [dict(zip(keys, row)) for row in rows]

# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/stats")
def get_stats():
    total_calls = query("SELECT COUNT(*) AS total FROM calls")[0]["total"]
    unique_patients = query("SELECT COUNT(DISTINCT patient_id) AS total FROM calls")[0]["total"]
    reach_rate = query("""
        SELECT ROUND(
            COUNT(*) FILTER (WHERE disposition = 'Reached') * 100.0 / NULLIF(COUNT(*), 0), 1
        ) AS rate FROM calls
    """)[0]["rate"]
    flagged_count = query("SELECT COUNT(*) AS total FROM call_logs_flagged")[0]["total"]

    return {
        "total_calls": total_calls,
        "unique_patients": unique_patients,
        "reach_rate": reach_rate,
        "flagged_count": flagged_count,
    }

@app.get("/dispositions")
def get_dispositions():
    return query("""
        SELECT disposition, COUNT(*) AS total
        FROM calls
        WHERE disposition IS NOT NULL
        GROUP BY disposition
        ORDER BY total DESC
    """)

@app.get("/calls-per-coordinator")
def get_calls_per_coordinator():
    return query("""
        SELECT co.name AS coordinator, COUNT(*) AS total_calls
        FROM calls ca
        JOIN coordinators co ON ca.coordinator_id = co.id
        GROUP BY co.name
        ORDER BY total_calls DESC
    """)

@app.get("/reach-rate-per-coordinator")
def get_reach_rate_per_coordinator():
    return query("""
        SELECT
            co.name AS coordinator,
            COUNT(*) AS total_calls,
            COUNT(*) FILTER (WHERE ca.disposition = 'Reached') AS reached,
            ROUND(
                COUNT(*) FILTER (WHERE ca.disposition = 'Reached') * 100.0 / NULLIF(COUNT(*), 0), 1
            ) AS reach_rate
        FROM calls ca
        JOIN coordinators co ON ca.coordinator_id = co.id
        GROUP BY co.name
        ORDER BY reach_rate DESC
    """)

@app.get("/calls-over-time")
def get_calls_over_time(period: str = "daily"):
    if period == "weekly":
        trunc = "week"
    elif period == "monthly":
        trunc = "month"
    else:
        trunc = "day"

    return query(f"""
        SELECT
            DATE_TRUNC('{trunc}', call_time) AS period,
            COUNT(*) AS total_calls
        FROM calls
        GROUP BY period
        ORDER BY period ASC
    """)

@app.get("/flagged-summary")
def get_flagged_summary():
    return query("""
        SELECT flag_reason, COUNT(*) AS total
        FROM call_logs_flagged
        GROUP BY flag_reason
        ORDER BY total DESC
    """)