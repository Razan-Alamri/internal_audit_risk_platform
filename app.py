from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for, jsonify

APP_NAME = "النموذج الذكي لإدارة المراجعة والرقابة وقياس المخاطر"
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "app.db")

# -----------------------------
# App factory
# -----------------------------
app = Flask(__name__)

# Jinja helpers
from helpers import now
app.jinja_env.globals["now"] = now

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")


# -----------------------------
# Database helpers
# -----------------------------
def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql: str, params: Tuple = (), one: bool = False):
    cur = get_db().execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql: str, params: Tuple = ()) -> int:
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    last = cur.lastrowid
    cur.close()
    return last


# -----------------------------
# Constants
# -----------------------------
TRACKS = {
    "TOUR": "جولة رقابية",
    "ACTIVITY": "نشاط رقابي",
    "INTERNAL_AUDIT": "مراجعة داخلية",
    "COMPLAINT": "فحص شكوى",
    "COMPLIANCE": "فحص التزام",
}

PRIORITIES = {"LOW": "منخفض", "MED": "متوسط", "HIGH": "مرتفع", "CRITICAL": "حرج"}

STATUS_MAP = {
    "DRAFT": "تجهيز العملية",
    "APPROVED": "الموافقة",
    "ASSIGNED": "الإسناد",
    "IN_PROGRESS": "التنفيذ",
    "PRELIM_REPORT": "التقرير المبدئي",
    "FINAL_APPROVAL": "الاعتماد النهائي",
    "ACTIONS": "المعالجة",
    "CLOSED": "الإغلاق",
}

SEVERITIES = {"LOW": "منخفض", "MED": "متوسط", "HIGH": "مرتفع", "CRITICAL": "حرج"}
FINDING_TYPES = {"OPER": "تشغيلية", "ADMIN": "إدارية", "FIN": "مالية", "SEC": "أمنية"}

RATING_LABELS = {
    5: "ممتاز",
    4: "جيد جدًا",
    3: "مقبول",
    2: "سيئ",
    1: "سيئ جدًا",
}

WORKFLOW_STAGES = [
    ("DRAFT", "تجهيز العملية"),
    ("APPROVED", "الموافقة"),
    ("ASSIGNED", "الإسناد"),
    ("IN_PROGRESS", "التنفيذ"),
    ("PRELIM_REPORT", "التقرير المبدئي"),
    ("FINAL_APPROVAL", "الاعتماد النهائي"),
    ("ACTIONS", "المعالجة"),
    ("CLOSED", "الإغلاق"),
]


# -----------------------------
# Helpers
# -----------------------------
def generate_ref(track_type: str) -> str:
    prefix = {
        "TOUR": "JR",
        "ACTIVITY": "NR",
        "INTERNAL_AUDIT": "MI",
        "COMPLAINT": "SH",
        "COMPLIANCE": "EL",
    }.get(track_type, "PR")
    ts = datetime.now().strftime("%y%m%d")
    rnd = str(int(datetime.now().timestamp()))[-5:]
    return f"{prefix}-{ts}-{rnd}"


def standard_rating_options() -> List[Dict[str, Any]]:
    return [
        {"label": "ممتاز", "value": 5},
        {"label": "جيد جدًا", "value": 4},
        {"label": "مقبول", "value": 3},
        {"label": "سيئ", "value": 2},
        {"label": "سيئ جدًا", "value": 1},
    ]


def build_default_criteria(track_type: str) -> Dict[str, Any]:
    """
    نفس الأقسام الأصلية تمامًا.
    التغيير فقط في مقياس التقييم إلى 1-5.
    """
    opts = standard_rating_options()

    if track_type == "TOUR":
        axes = [
            {
                "name": "الرعاية الصحية",
                "weight": 0.30,
                "criteria": [
                    {"name": "آلية تسليم الأدوية النفسية", "weight": 0.25, "options": opts},
                    {"name": "تجهيزات المركز الصحي", "weight": 0.25, "options": opts},
                    {"name": "إجراءات العزل", "weight": 0.25, "options": opts},
                    {"name": "كفاية الكادر الطبي", "weight": 0.25, "options": opts},
                ],
            },
            {
                "name": "الأمن والسلامة",
                "weight": 0.35,
                "criteria": [
                    {"name": "تغطية المواقع بكاميرات مراقبة", "weight": 0.40, "options": opts},
                    {"name": "الضبط والتفتيش", "weight": 0.30, "options": opts},
                    {"name": "سجلات الحوادث الأمنية", "weight": 0.30, "options": opts},
                ],
            },
            {
                "name": "التشغيل والخدمات",
                "weight": 0.20,
                "criteria": [
                    {"name": "جاهزية المرافق", "weight": 0.50, "options": opts},
                    {"name": "الالتزام بخطة الجولة", "weight": 0.50, "options": opts},
                ],
            },
            {
                "name": "الالتزام الإداري",
                "weight": 0.15,
                "criteria": [
                    {"name": "رفع التقارير في الوقت المحدد", "weight": 0.60, "options": opts},
                    {"name": "تكرار الملاحظة في نفس الموقع", "weight": 0.40, "options": opts},
                ],
            },
        ]
    else:
        axes = [
            {
                "name": "الحوكمة والامتثال",
                "weight": 0.40,
                "criteria": [
                    {"name": "توثيق الإجراءات", "weight": 0.25, "options": opts},
                    {"name": "الالتزام باللوائح", "weight": 0.25, "options": opts},
                    {"name": "صلاحيات واعتمادات", "weight": 0.25, "options": opts},
                    {"name": "الأرشفة", "weight": 0.25, "options": opts},
                ],
            },
            {
                "name": "المخاطر التشغيلية",
                "weight": 0.30,
                "criteria": [
                    {"name": "تأخر التنفيذ", "weight": 0.50, "options": opts},
                    {"name": "تراكم الملاحظات", "weight": 0.50, "options": opts},
                ],
            },
            {
                "name": "المخاطر المالية",
                "weight": 0.30,
                "criteria": [
                    {"name": "انحرافات الصرف", "weight": 0.50, "options": opts},
                    {"name": "تكرار ملاحظات عالية الأثر", "weight": 0.50, "options": opts},
                ],
            },
        ]

    return {"axes": axes}


def build_default_workflow(track_type: str) -> Dict[str, Any]:
    return {
        "stages": [{"code": s, "label": label} for s, label in WORKFLOW_STAGES],
        "routing": {
            "by_region": True,
            "coord_role": "REGION_COORD",
            "auditor_role": "AUDITOR",
            "director_role": "DIRECTOR",
        },
        "governance": {
            "requires_director_approval_for_critical": True,
            "auto_assign_on_approved": True,
            "sla_days_by_severity": {"LOW": 30, "MED": 20, "HIGH": 10, "CRITICAL": 5},
        },
    }


def build_process_payload(
    track_type: str,
    title: str,
    region: str,
    prison_code: str,
    planned_date: Optional[str],
    created_by: str,
    priority: str,
    status: str = "DRAFT",
) -> Dict[str, Any]:
    return {
        "track_type": track_type,
        "title": title,
        "region": region,
        "prison_code": prison_code,
        "planned_date": planned_date,
        "created_by": created_by,
        "priority": priority,
        "status": status,
        "workflow": build_default_workflow(track_type),
        "criteria": build_default_criteria(track_type),
    }


def compute_risk_score(criteria_payload: Dict[str, Any], answers: Dict[str, Any]) -> Dict[str, Any]:
    """
    التقييم المعتمد:
    5 = ممتاز
    4 = جيد جدًا
    3 = مقبول
    2 = سيئ
    1 = سيئ جدًا

    يتم تحويله داخليًا إلى مخاطرة:
    5 -> 0
    4 -> 25
    3 -> 50
    2 -> 75
    1 -> 100
    """
    axes = criteria_payload.get("axes", [])
    axis_results = []
    total = 0.0

    def rating_to_risk(value: float) -> float:
        try:
            v = float(value)
        except Exception:
            v = 5.0
        v = max(1.0, min(5.0, v))
        return ((5.0 - v) / 4.0) * 100.0

    for ai, ax in enumerate(axes):
        aw = float(ax.get("weight", 0))
        csum = 0.0
        cw_total = 0.0
        crits = ax.get("criteria", [])

        for ci, cr in enumerate(crits):
            cw = float(cr.get("weight", 0))
            key = f"{ai}:{ci}"
            selected_rating = float(answers.get(key, 5))
            risk_value = rating_to_risk(selected_rating)
            csum += risk_value * cw
            cw_total += cw

        axis_score = (csum / cw_total) if cw_total else 0.0
        axis_results.append({
            "axis": ax.get("name", ""),
            "score": round(axis_score, 1),
            "weight": aw,
        })
        total += axis_score * aw

    total_score = round(total, 1)

    level = "LOW"
    if total_score >= 75:
        level = "CRITICAL"
    elif total_score >= 55:
        level = "HIGH"
    elif total_score >= 30:
        level = "MED"

    return {"total": total_score, "level": level, "axes": axis_results}


def kpi_snapshot() -> Dict[str, Any]:
    rows = query("SELECT status, COUNT(*) AS c FROM processes GROUP BY status")
    by_status = {r["status"]: r["c"] for r in rows}
    findings = query("SELECT status, COUNT(*) AS c FROM findings GROUP BY status")
    findings_status = {r["status"]: r["c"] for r in findings}
    open_findings = findings_status.get("OPEN", 0) + findings_status.get("IN_REVIEW", 0)
    done_findings = findings_status.get("DONE", 0)
    return {
        "total_processes": sum(by_status.values()),
        "in_progress": by_status.get("IN_PROGRESS", 0),
        "pending_approval": by_status.get("APPROVED", 0) + by_status.get("DRAFT", 0),
        "open_findings": open_findings,
        "closure_rate": round((done_findings / max(done_findings + open_findings, 1)) * 100, 1),
    }


def kri_by_prison() -> List[Dict[str, Any]]:
    prisons = query("SELECT code, name, region FROM prisons WHERE is_active=1 ORDER BY region, name")
    out = []
    for p in prisons:
        procs = query(
            "SELECT id, criteria_json, workflow_json, status FROM processes WHERE prison_code=? ORDER BY id DESC LIMIT 10",
            (p["code"],),
        )
        scores = []
        backlog = query(
            """SELECT COUNT(*) AS c
               FROM findings f
               JOIN processes pr ON pr.id=f.process_id
               WHERE pr.prison_code=? AND f.status!='DONE'""",
            (p["code"],),
            one=True,
        )["c"]

        for pr in procs:
            wf = json.loads(pr["workflow_json"])
            answers = wf.get("answers", {})
            crit = json.loads(pr["criteria_json"])
            s = compute_risk_score(crit, answers)["total"]
            scores.append(s)

        base = (sum(scores) / len(scores)) if scores else 0.0
        kri = min(100.0, round(base + min(20, backlog * 1.5), 1))

        level = "LOW"
        if kri >= 75:
            level = "CRITICAL"
        elif kri >= 55:
            level = "HIGH"
        elif kri >= 30:
            level = "MED"

        out.append({
            "code": p["code"],
            "name": p["name"],
            "region": p["region"],
            "kri": kri,
            "level": level,
            "backlog": backlog,
        })

    out.sort(key=lambda x: x["kri"], reverse=True)
    return out


def log_action(process_id: int, actor: str, action: str, details: str = ""):
    execute(
        "INSERT INTO actions_log(process_id, action_at, actor, action, details) VALUES (?,?,?,?,?)",
        (process_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), actor, action, details),
    )


# -----------------------------
# Database init + seed
# -----------------------------
def ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    db.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS prisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region TEXT NOT NULL,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            capacity INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL,
            region TEXT,
            username TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_no TEXT NOT NULL UNIQUE,
            track_type TEXT NOT NULL,
            title TEXT NOT NULL,
            region TEXT NOT NULL,
            prison_code TEXT NOT NULL,
            planned_date TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            workflow_json TEXT NOT NULL,
            criteria_json TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY(prison_code) REFERENCES prisons(code)
        );

        CREATE TABLE IF NOT EXISTS findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_id INTEGER NOT NULL,
            axis TEXT NOT NULL,
            criterion TEXT NOT NULL,
            severity TEXT NOT NULL,
            finding_type TEXT NOT NULL,
            owner_unit TEXT NOT NULL,
            due_date TEXT,
            status TEXT NOT NULL,
            description TEXT,
            attachments_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS actions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_id INTEGER NOT NULL,
            action_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()

    # Seed prisons
    row = db.execute("SELECT COUNT(*) AS c FROM prisons").fetchone()
    if row["c"] == 0:
        prisons = [
            ("منطقة الرياض", "سجن الرياض", "RYD-01", 3500),
            ("منطقة الرياض", "سجن الحائر", "RYD-02", 4200),
            ("منطقة مكة المكرمة", "سجن جدة", "MKK-01", 3800),
            ("منطقة عسير", "سجن أبها", "ASR-01", 2400),
            ("منطقة الشرقية", "سجن الدمام", "EST-01", 3200),
        ]
        db.executemany("INSERT INTO prisons(region, name, code, capacity) VALUES(?,?,?,?)", prisons)

    # Seed users
    row = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    if row["c"] == 0:
        users = [
            ("مدير عام المراجعة الداخلية", "DIRECTOR", None, "director"),
            ("مشرف المنصة", "ADMIN", None, "admin"),
            ("منسق منطقة الرياض", "REGION_COORD", "منطقة الرياض", "r_coord"),
            ("مدقق داخلي - الرياض", "AUDITOR", "منطقة الرياض", "r_auditor"),
            ("منسق منطقة مكة", "REGION_COORD", "منطقة مكة المكرمة", "m_coord"),
            ("مدقق داخلي - جدة", "AUDITOR", "منطقة مكة المكرمة", "m_auditor"),
        ]
        db.executemany("INSERT INTO users(display_name, role, region, username) VALUES(?,?,?,?)", users)

    # تنظيف بيانات العمليات القديمة وإعادة تعبئة بيانات أقرب للواقع
    row = db.execute("SELECT COUNT(*) AS c FROM processes").fetchone()
    if row["c"] == 0:
        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        payload1 = build_process_payload(
            track_type="TOUR",
            title="جولة رقابية مجدولة على الرعاية الصحية والخدمات المساندة",
            region="منطقة الرياض",
            prison_code="RYD-01",
            planned_date=date.today().strftime("%Y-%m-%d"),
            created_by="r_coord",
            priority="HIGH",
            status="IN_PROGRESS",
        )
        payload1["workflow"]["answers"] = {
            "0:0": 3, "0:1": 2, "0:2": 3, "0:3": 2,
            "1:0": 3, "1:1": 2, "1:2": 4,
            "2:0": 3, "2:1": 4,
            "3:0": 2, "3:1": 3,
        }

        ref1 = "JR-260223-10001"
        db.execute(
            """INSERT INTO processes
            (ref_no, track_type, title, region, prison_code, planned_date, created_at, created_by,
                status, priority, workflow_json, criteria_json, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ref1,
                payload1["track_type"],
                payload1["title"],
                payload1["region"],
                payload1["prison_code"],
                payload1["planned_date"],
                now_ts,
                payload1["created_by"],
                "IN_PROGRESS",
                payload1["priority"],
                json.dumps(payload1["workflow"], ensure_ascii=False),
                json.dumps(payload1["criteria"], ensure_ascii=False),
                "تم تنفيذ الجولة وفق الخطة المعتمدة، مع تسجيل عدد من الملاحظات التشغيلية والصحية.",
            ),
        )
        pid1 = db.execute("SELECT id FROM processes WHERE ref_no=?", (ref1,)).fetchone()["id"]

        payload2 = build_process_payload(
            track_type="TOUR",
            title="جولة رقابية مفاجئة على الأمن والسلامة",
            region="منطقة الرياض",
            prison_code="RYD-02",
            planned_date=date.today().strftime("%Y-%m-%d"),
            created_by="r_auditor",
            priority="CRITICAL",
            status="PRELIM_REPORT",
        )
        payload2["workflow"]["answers"] = {
            "0:0": 4, "0:1": 4, "0:2": 3, "0:3": 3,
            "1:0": 2, "1:1": 1, "1:2": 2,
            "2:0": 3, "2:1": 3,
            "3:0": 3, "3:1": 2,
        }

        ref2 = "JR-260223-10002"
        db.execute(
            """INSERT INTO processes
            (ref_no, track_type, title, region, prison_code, planned_date, created_at, created_by,
                status, priority, workflow_json, criteria_json, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ref2,
                payload2["track_type"],
                payload2["title"],
                payload2["region"],
                payload2["prison_code"],
                payload2["planned_date"],
                now_ts,
                payload2["created_by"],
                "PRELIM_REPORT",
                payload2["priority"],
                json.dumps(payload2["workflow"], ensure_ascii=False),
                json.dumps(payload2["criteria"], ensure_ascii=False),
                "الجولة مرتبطة برصد فجوات في تغطية بعض المواقع وضبط السجلات الأمنية.",
            ),
        )
        pid2 = db.execute("SELECT id FROM processes WHERE ref_no=?", (ref2,)).fetchone()["id"]

        payload3 = build_process_payload(
            track_type="TOUR",
            title="جولة رقابية مجدولة على الالتزام الإداري ورفع التقارير",
            region="منطقة مكة المكرمة",
            prison_code="MKK-01",
            planned_date=date.today().strftime("%Y-%m-%d"),
            created_by="m_coord",
            priority="MED",
            status="FINAL_APPROVAL",
        )
        payload3["workflow"]["answers"] = {
            "0:0": 4, "0:1": 4, "0:2": 4, "0:3": 4,
            "1:0": 4, "1:1": 4, "1:2": 4,
            "2:0": 3, "2:1": 4,
            "3:0": 2, "3:1": 2,
        }

        ref3 = "JR-260223-10003"
        db.execute(
            """INSERT INTO processes
            (ref_no, track_type, title, region, prison_code, planned_date, created_at, created_by,
                status, priority, workflow_json, criteria_json, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ref3,
                payload3["track_type"],
                payload3["title"],
                payload3["region"],
                payload3["prison_code"],
                payload3["planned_date"],
                now_ts,
                payload3["created_by"],
                "FINAL_APPROVAL",
                payload3["priority"],
                json.dumps(payload3["workflow"], ensure_ascii=False),
                json.dumps(payload3["criteria"], ensure_ascii=False),
                "الجولة ركزت على انتظام دورة العمل ورفع التقارير في الوقت المحدد.",
            ),
        )
        pid3 = db.execute("SELECT id FROM processes WHERE ref_no=?", (ref3,)).fetchone()["id"]

        findings = [
            (
                pid1,
                "الرعاية الصحية",
                "آلية تسليم الأدوية النفسية",
                "HIGH",
                "OPER",
                "إدارة الرعاية الصحية",
                "2026-03-05",
                "OPEN",
                "عدم اكتمال توثيق تسليم الأدوية لعدد من الحالات خلال فترة المناوبة المسائية.",
                "[]",
                now_ts,
            ),
            (
                pid1,
                "التشغيل والخدمات",
                "جاهزية المرافق",
                "MED",
                "OPER",
                "إدارة التشغيل والصيانة",
                "2026-03-10",
                "IN_REVIEW",
                "وجود ملاحظات على جاهزية بعض المرافق الصحية وتأخر تنفيذ أعمال الصيانة الوقائية.",
                "[]",
                now_ts,
            ),
            (
                pid2,
                "الأمن والسلامة",
                "تغطية المواقع بكاميرات مراقبة",
                "CRITICAL",
                "SEC",
                "إدارة الأمن والسلامة",
                "2026-02-28",
                "OPEN",
                "وجود فجوات مؤثرة في تغطية بعض المواقع الحساسة بكاميرات المراقبة.",
                "[]",
                now_ts,
            ),
            (
                pid2,
                "الأمن والسلامة",
                "سجلات الحوادث الأمنية",
                "HIGH",
                "SEC",
                "إدارة الأمن والسلامة",
                "2026-03-03",
                "OPEN",
                "رصد تكرار في الحوادث الأمنية خلال الفترة الأخيرة مع حاجة لمتابعة عاجلة.",
                "[]",
                now_ts,
            ),
            (
                pid3,
                "الالتزام الإداري",
                "رفع التقارير في الوقت المحدد",
                "MED",
                "ADMIN",
                "إدارة المتابعة الإدارية",
                "2026-03-07",
                "DONE",
                "تأخر محدود في رفع بعض التقارير الدورية وتمت المعالجة وإعادة الضبط.",
                "[]",
                now_ts,
            ),
        ]

        db.executemany(
            """INSERT INTO findings(process_id, axis, criterion, severity, finding_type, owner_unit, due_date, status, description, attachments_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            findings,
        )

        actions = [
            (pid1, now_ts, "r_coord", "إنشاء العملية", "تم إنشاء العملية ضمن الخطة السنوية."),
            (pid1, now_ts, "r_coord", "الإحالة للتنفيذ", "تم إسناد الجولة للفريق المختص بالمنطقة."),
            (pid1, now_ts, "r_auditor", "تسجيل ملاحظة", "تم تسجيل ملاحظات على آلية تسليم الأدوية وجاهزية المرافق."),
            (pid2, now_ts, "r_auditor", "إنشاء العملية", "تم فتح جولة رقابية مفاجئة بناءً على مؤشرات تشغيلية."),
            (pid2, now_ts, "r_auditor", "رفع تقرير مبدئي", "تم رفع تقرير مبدئي يتضمن ملاحظات أمنية عالية الخطورة."),
            (pid3, now_ts, "m_coord", "إنشاء العملية", "تم تسجيل الجولة ضمن أعمال المنطقة."),
            (pid3, now_ts, "m_auditor", "إغلاق ملاحظة", "تمت معالجة ملاحظة تأخر التقارير وإقفالها."),
        ]

        db.executemany(
            "INSERT INTO actions_log(process_id, action_at, actor, action, details) VALUES (?,?,?,?,?)",
            actions,
        )

        db.commit()

    db.commit()
    db.close()


# -----------------------------
# Auth
# -----------------------------
def current_user():
    return session.get("user")


@app.route("/login", methods=["GET", "POST"])
def login():
    ensure_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        u = query("SELECT display_name, role, region, username FROM users WHERE username=?", (username,), one=True)
        if not u:
            flash("بيانات الدخول غير صحيحة.", "danger")
            return redirect(url_for("login"))
        session["user"] = {
            "display_name": u["display_name"],
            "role": u["role"],
            "region": u["region"],
            "username": u["username"],
        }
        return redirect(url_for("dashboard"))
    users = query("SELECT display_name, role, region, username FROM users ORDER BY role, display_name")
    return render_template("login.html", users=users, app_name=APP_NAME)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.before_request
def _guard():
    allow = {"login", "static"}
    if request.endpoint and request.endpoint.split(".")[0] in allow:
        return
    if request.endpoint in allow:
        return
    if request.path.startswith("/static/"):
        return
    if request.path == "/health":
        return
    if not current_user():
        return redirect(url_for("login"))


# -----------------------------
# Pages
# -----------------------------
@app.route("/")
def dashboard():
    snap = kpi_snapshot()
    prisons = kri_by_prison()
    return render_template(
        "dashboard.html",
        app_name=APP_NAME,
        user=current_user(),
        snap=snap,
        prisons=prisons,
        pri_map=PRIORITIES,
        sev_map=SEVERITIES,
        status_map=STATUS_MAP,
    )


@app.route("/processes")
def processes():
    region = request.args.get("region") or ""
    track = request.args.get("track") or ""
    status = request.args.get("status") or ""

    q = """SELECT p.*, pr.name AS prison_name
           FROM processes p
           JOIN prisons pr ON pr.code=p.prison_code
           WHERE 1=1"""
    params: List[Any] = []

    if region:
        q += " AND p.region=?"
        params.append(region)
    if track:
        q += " AND p.track_type=?"
        params.append(track)
    if status:
        q += " AND p.status=?"
        params.append(status)

    q += " ORDER BY p.id DESC LIMIT 200"
    rows = query(q, tuple(params))
    regions = [r["region"] for r in query("SELECT DISTINCT region FROM prisons ORDER BY region")]

    return render_template(
        "processes.html",
        app_name=APP_NAME,
        user=current_user(),
        rows=rows,
        regions=regions,
        tracks=TRACKS,
        status_map=STATUS_MAP,
        pri_map=PRIORITIES,
    )


@app.route("/process/new", methods=["GET", "POST"])
def process_new():
    if request.method == "POST":
        track_type = request.form.get("track_type", "TOUR")
        title = request.form.get("title", "").strip()
        region = request.form.get("region", "").strip()
        prison_code = request.form.get("prison_code", "").strip()
        planned_date = request.form.get("planned_date", "").strip() or None
        priority = request.form.get("priority", "MED")

        if not (title and region and prison_code and track_type):
            flash("يرجى استكمال الحقول الأساسية.", "danger")
            return redirect(url_for("process_new"))

        ref_no = generate_ref(track_type)
        payload = build_process_payload(
            track_type=track_type,
            title=title,
            region=region,
            prison_code=prison_code,
            planned_date=planned_date,
            created_by=current_user()["username"],
            priority=priority,
            status="DRAFT",
        )

        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pid = execute(
            """INSERT INTO processes(ref_no, track_type, title, region, prison_code, planned_date, created_at, created_by,
                                     status, priority, workflow_json, criteria_json, notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ref_no,
                track_type,
                title,
                region,
                prison_code,
                planned_date,
                now_ts,
                current_user()["username"],
                "DRAFT",
                priority,
                json.dumps(payload["workflow"], ensure_ascii=False),
                json.dumps(payload["criteria"], ensure_ascii=False),
                "",
            ),
        )
        log_action(pid, current_user()["username"], "إنشاء العملية", f"رقم المرجع: {ref_no}")
        return redirect(url_for("process_view", process_id=pid))

    prisons = query("SELECT code, name, region FROM prisons WHERE is_active=1 ORDER BY region, name")
    regions = [r["region"] for r in query("SELECT DISTINCT region FROM prisons ORDER BY region")]
    return render_template(
        "process_new.html",
        app_name=APP_NAME,
        user=current_user(),
        prisons=prisons,
        regions=regions,
        tracks=TRACKS,
        pri_map=PRIORITIES,
    )


@app.route("/process/<int:process_id>")
def process_view(process_id: int):
    p = query(
        """SELECT p.*, pr.name AS prison_name, pr.capacity AS prison_capacity
           FROM processes p
           JOIN prisons pr ON pr.code=p.prison_code
           WHERE p.id=?""",
        (process_id,),
        one=True,
    )
    if not p:
        abort(404)

    wf = json.loads(p["workflow_json"])
    crit = json.loads(p["criteria_json"])
    answers = wf.get("answers", {})
    score = compute_risk_score(crit, answers)

    findings = query("SELECT * FROM findings WHERE process_id=? ORDER BY id DESC", (process_id,))
    log = query("SELECT * FROM actions_log WHERE process_id=? ORDER BY id DESC LIMIT 40", (process_id,))
    users = query("SELECT display_name, role, region, username FROM users ORDER BY role, display_name")

    return render_template(
        "process_view.html",
        app_name=APP_NAME,
        user=current_user(),
        p=p,
        wf=wf,
        crit=crit,
        answers=answers,
        score=score,
        tracks=TRACKS,
        pri_map=PRIORITIES,
        status_map=STATUS_MAP,
        sev_map=SEVERITIES,
        finding_types=FINDING_TYPES,
        findings=findings,
        log=log,
        users=users,
        rating_labels=RATING_LABELS,
    )


@app.post("/process/<int:process_id>/update_status")
def process_update_status(process_id: int):
    new_status = request.form.get("status", "").strip()
    if new_status not in STATUS_MAP:
        abort(400)

    p = query("SELECT id, status, priority FROM processes WHERE id=?", (process_id,), one=True)
    if not p:
        abort(404)

    execute("UPDATE processes SET status=? WHERE id=?", (new_status, process_id))
    log_action(process_id, current_user()["username"], "تحديث الحالة", f"{STATUS_MAP.get(p['status'])} → {STATUS_MAP.get(new_status)}")
    return redirect(url_for("process_view", process_id=process_id))


@app.post("/process/<int:process_id>/save_assessment")
def process_save_assessment(process_id: int):
    p = query("SELECT workflow_json, criteria_json FROM processes WHERE id=?", (process_id,), one=True)
    if not p:
        abort(404)

    wf = json.loads(p["workflow_json"])
    crit = json.loads(p["criteria_json"])

    answers = {}
    axes = crit.get("axes", [])
    for ai, ax in enumerate(axes):
        for ci, _cr in enumerate(ax.get("criteria", [])):
            key = f"{ai}:{ci}"
            v = request.form.get(key)
            if v is not None:
                try:
                    answers[key] = int(v)
                except Exception:
                    answers[key] = 5

    wf["answers"] = answers
    execute(
        "UPDATE processes SET workflow_json=? WHERE id=?",
        (json.dumps(wf, ensure_ascii=False), process_id),
    )
    log_action(process_id, current_user()["username"], "حفظ التقييم", "تم تحديث درجات المعايير وربطها بالمؤشر")
    return redirect(url_for("process_view", process_id=process_id))


@app.post("/process/<int:process_id>/add_finding")
def add_finding(process_id: int):
    axis = request.form.get("axis", "").strip()
    criterion = request.form.get("criterion", "").strip()
    severity = request.form.get("severity", "MED")
    finding_type = request.form.get("finding_type", "OPER")
    owner_unit = request.form.get("owner_unit", "").strip() or "الجهة المختصة"
    due_date = request.form.get("due_date", "").strip() or None
    description = request.form.get("description", "").strip()

    if not (axis and criterion):
        abort(400)

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fid = execute(
        """INSERT INTO findings(process_id, axis, criterion, severity, finding_type, owner_unit, due_date, status, description, attachments_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (process_id, axis, criterion, severity, finding_type, owner_unit, due_date, "OPEN", description, "[]", now_ts),
    )
    log_action(process_id, current_user()["username"], "إضافة ملاحظة", f"رقم الملاحظة: {fid}")
    return redirect(url_for("process_view", process_id=process_id))


@app.post("/finding/<int:finding_id>/update")
def update_finding(finding_id: int):
    status = request.form.get("status", "OPEN")
    if status not in {"OPEN", "IN_REVIEW", "DONE"}:
        abort(400)

    f = query("SELECT process_id FROM findings WHERE id=?", (finding_id,), one=True)
    if not f:
        abort(404)

    execute("UPDATE findings SET status=? WHERE id=?", (status, finding_id))
    log_action(int(f["process_id"]), current_user()["username"], "تحديث حالة الملاحظة", f"الملاحظة {finding_id}: {status}")
    return redirect(url_for("process_view", process_id=int(f["process_id"])))


@app.route("/prison/<code>")
def prison_view(code: str):
    pr = query("SELECT * FROM prisons WHERE code=?", (code,), one=True)
    if not pr:
        abort(404)

    procs = query(
        """SELECT p.*, pr.name AS prison_name
           FROM processes p
           JOIN prisons pr ON pr.code=p.prison_code
           WHERE p.prison_code=? ORDER BY p.id DESC LIMIT 50""",
        (code,),
    )

    trend = []
    for p in procs[:10]:
        wf = json.loads(p["workflow_json"])
        crit = json.loads(p["criteria_json"])
        s = compute_risk_score(crit, wf.get("answers", {}))
        trend.append({"ref_no": p["ref_no"], "score": s["total"], "level": s["level"]})
    trend.reverse()

    backlog = query(
        """SELECT f.*, p.ref_no, p.title
           FROM findings f
           JOIN processes p ON p.id=f.process_id
           WHERE p.prison_code=? AND f.status!='DONE'
           ORDER BY f.severity DESC, f.id DESC LIMIT 100""",
        (code,),
    )

    return render_template(
        "prison_view.html",
        app_name=APP_NAME,
        user=current_user(),
        pr=pr,
        procs=procs,
        trend=trend,
        backlog=backlog,
        tracks=TRACKS,
        pri_map=PRIORITIES,
        status_map=STATUS_MAP,
        sev_map=SEVERITIES,
        finding_types=FINDING_TYPES,
    )


@app.get("/api/kri")
def api_kri():
    return jsonify({"items": kri_by_prison(), "kpi": kpi_snapshot()})


@app.get("/health")
def health():
    return "ok"


if __name__ == "__main__":
    ensure_db()
    app.run(host="127.0.0.1", port=5000, debug=True)