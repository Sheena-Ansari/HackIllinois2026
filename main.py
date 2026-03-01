"""
QueueIQ — Virtual Waiting Room API
"""

import uuid
import os
import re
from collections import deque
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from mailjet_rest import Client

app = FastAPI(
    title="QueueIQ API",
    description=(
        "Virtual waiting room infrastructure. Drop this in front of any high-traffic event "
        "— drops, registrations, ticket sales — and your server stops getting crushed."
    ),
    version="1.1.0",
    contact={"name": "QueueIQ Team", "email": "team@queueiq.dev"},
    license_info={"name": "MIT"},
)

# keyed by event_name
events: dict[str, dict] = {}

# keyed by ticket_id
tickets: dict[str, dict] = {}

ADMIN_SECRET = os.getenv("QUEUE_ADMIN_SECRET", "stripe_hackathon_2026")
SECONDS_PER_POSITION = int(os.getenv("SECONDS_PER_POSITION", "120"))
MAX_QUEUE_CAPACITY = int(os.getenv("MAX_QUEUE_CAPACITY", "10000"))

# mailjet config
MJ_API_KEY = os.getenv("MJ_API_KEY", "")
MJ_SECRET_KEY = os.getenv("MJ_SECRET_KEY", "")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")


# email helper
def send_admission_email(to_email: str, user_name: str, event_name: str, ticket_id: str):
    try:
        mailjet = Client(auth=(MJ_API_KEY, MJ_SECRET_KEY), version='v3.1')
        data = {
            'Messages': [
                {
                    "From": {
                        "Email": SENDER_EMAIL,
                        "Name": "QueueIQ"
                    },
                    "To": [
                        {
                            "Email": to_email,
                            "Name": user_name
                        }
                    ],
                    "Subject": f"You're in! Access granted for {event_name}",
                    "TextPart": f"Hey {user_name}, your ticket {ticket_id} has been admitted. Complete your purchase in the next 10 minutes before your spot expires!",
                    "HTMLPart": f"""
                    <h2>You're in, {user_name}! 🎉</h2>
                    <p>Your ticket <strong>{ticket_id}</strong> has been admitted to <strong>{event_name}</strong>.</p>
                    <p>Complete your purchase in the next <strong>10 minutes</strong> before your spot expires.</p>
                    <br>
                    <p>— QueueIQ</p>
                    """
                }
            ]
        }
        mailjet.send.create(data=data)
    except Exception as e:
        print(f"Email failed to send: {e}")


class CreateEventRequest(BaseModel):
    event_name: str = Field(..., min_length=1, max_length=100, description="Unique slug for the event")
    description: Optional[str] = Field(None, max_length=500)
    capacity_hint: Optional[int] = Field(
        None, ge=1,
        description="Informational only — does not cap the queue size."
    )

    @field_validator("event_name")
    @classmethod
    def slugify(cls, v: str) -> str:
        slug = re.sub(r"[^\w-]", "-", v.strip().lower())
        if not slug:
            raise ValueError("event_name must contain at least one alphanumeric character")
        return slug


class JoinRequest(BaseModel):
    user_identifier: str = Field(..., min_length=1, max_length=255, description="Opaque user ID or email")
    event_name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., description="Email address to notify when admitted")
    metadata: Optional[dict] = Field(None, description="Arbitrary key-value pairs, e.g. locale or referral source")


class AdmitRequest(BaseModel):
    event_name: str
    number_to_admit: int = Field(..., ge=1, le=10_000)


class LeaveRequest(BaseModel):
    ticket_id: str


def require_admin(x_admin_secret: Optional[str]):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized. Pass your admin secret in the X-Admin-Secret header."
        )


def get_event_or_404(event_name: str) -> dict:
    if event_name not in events:
        raise HTTPException(
            status_code=404,
            detail=f"Event '{event_name}' not found. Create it first via POST /events."
        )
    return events[event_name]


def compute_position(event_name: str, ticket_id: str) -> tuple[int, int]:
    lst = list(events[event_name]["queue"])
    try:
        idx = lst.index(ticket_id)
        return idx + 1, idx
    except ValueError:
        return -1, -1


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_summary(name: str) -> dict:
    e = events[name]
    return {
        "event_name": name,
        "description": e["description"],
        "status": e["status"],
        "queue_length": len(e["queue"]),
        "total_admitted": e["total_admitted"],
        "capacity_hint": e["capacity_hint"],
        "created_at": e["created_at"],
    }


@app.get("/", tags=["Meta"])
def root():
    return {
        "service": "QueueIQ API",
        "version": "1.1.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["Meta"])
def health():
    total_waiting = sum(len(e["queue"]) for e in events.values())
    return {
        "status": "ok",
        "events_active": len(events),
        "tickets_issued": len(tickets),
        "total_waiting": total_waiting,
        "timestamp": now_iso(),
    }


@app.post("/events", status_code=201, tags=["Events"])
def create_event(
    body: CreateEventRequest,
    x_admin_secret: Optional[str] = Header(default=None),
):
    require_admin(x_admin_secret)

    if body.event_name in events:
        raise HTTPException(
            status_code=409,
            detail=f"Event '{body.event_name}' already exists."
        )

    events[body.event_name] = {
        "event_name": body.event_name,
        "description": body.description,
        "capacity_hint": body.capacity_hint,
        "queue": deque(),
        "total_admitted": 0,
        "created_at": now_iso(),
        "status": "open",
    }

    return {
        "message": f"Event '{body.event_name}' created.",
        "event": _event_summary(body.event_name),
    }


@app.get("/events", tags=["Events"])
def list_events(
    status: Optional[str] = Query(None, description="Filter by status: open | closed"),
    x_admin_secret: Optional[str] = Header(default=None),
):
    require_admin(x_admin_secret)

    result = []
    for name in events:
        e = _event_summary(name)
        if status and e["status"] != status:
            continue
        result.append(e)

    return {"events": result, "total": len(result)}


@app.get("/events/{event_name}", tags=["Events"])
def get_event(event_name: str):
    get_event_or_404(event_name)
    return _event_summary(event_name)


@app.delete("/events/{event_name}", status_code=200, tags=["Events"])
def close_event(
    event_name: str,
    x_admin_secret: Optional[str] = Header(default=None),
):
    require_admin(x_admin_secret)
    get_event_or_404(event_name)

    event = events[event_name]
    expired_count = 0
    while event["queue"]:
        tid = event["queue"].popleft()
        if tid in tickets:
            tickets[tid]["status"] = "expired"
            tickets[tid]["expired_at"] = now_iso()
            expired_count += 1

    event["status"] = "closed"

    return {
        "message": f"Event '{event_name}' closed.",
        "tickets_expired": expired_count,
    }


@app.post("/queue/join", status_code=201, tags=["Queue"])
def join_queue(body: JoinRequest):
    event = get_event_or_404(body.event_name)

    if event["status"] == "closed":
        raise HTTPException(
            status_code=410,
            detail=f"Event '{body.event_name}' is closed. No new entries accepted."
        )

    if len(event["queue"]) >= MAX_QUEUE_CAPACITY:
        raise HTTPException(status_code=503, detail="Queue is at maximum capacity. Try again later.")

    for tid in event["queue"]:
        if tickets[tid]["user_identifier"] == body.user_identifier:
            position_in_line, people_ahead = compute_position(body.event_name, tid)
            return JSONResponse(
                status_code=200,
                content={
                    "message": "You're already in line — here's your existing ticket.",
                    "ticket_id": tid,
                    "position_in_line": position_in_line,
                    "people_ahead_of_you": people_ahead,
                    "estimated_wait_seconds": people_ahead * SECONDS_PER_POSITION,
                    "status": "waiting",
                }
            )

    ticket_id = f"tkt_{uuid.uuid4().hex[:12]}"

    tickets[ticket_id] = {
        "ticket_id": ticket_id,
        "user_identifier": body.user_identifier,
        "event_name": body.event_name,
        "email": body.email,
        "status": "waiting",
        "metadata": body.metadata or {},
        "joined_at": now_iso(),
        "admitted_at": None,
        "expired_at": None,
    }

    event["queue"].append(ticket_id)

    position_in_line = len(event["queue"])
    people_ahead = position_in_line - 1

    return {
        "message": "You're in. Hold onto that ticket_id.",
        "ticket_id": ticket_id,
        "event_name": body.event_name,
        "position_in_line": position_in_line,
        "people_ahead_of_you": people_ahead,
        "estimated_wait_seconds": people_ahead * SECONDS_PER_POSITION,
        "status": "waiting",
        "joined_at": tickets[ticket_id]["joined_at"],
    }


@app.get("/queue/status/{ticket_id}", tags=["Queue"])
def get_status(ticket_id: str):
    if ticket_id not in tickets:
        raise HTTPException(
            status_code=404,
            detail="Ticket not found. Join the queue first via POST /queue/join."
        )

    ticket = tickets[ticket_id]
    event_name = ticket["event_name"]
    status = ticket["status"]

    if status == "admitted":
        return {
            "ticket_id": ticket_id,
            "status": "admitted",
            "event_name": event_name,
            "admitted_at": ticket["admitted_at"],
            "action": "Access granted. Proceed to the protected resource.",
        }

    if status == "expired":
        return {
            "ticket_id": ticket_id,
            "status": "expired",
            "event_name": event_name,
            "expired_at": ticket["expired_at"],
            "message": "This event closed before your position was reached.",
        }

    if event_name not in events:
        raise HTTPException(status_code=500, detail="Event data missing. Contact support.")

    position_in_line, people_ahead = compute_position(event_name, ticket_id)

    if position_in_line == -1:
        raise HTTPException(
            status_code=500,
            detail="Queue state inconsistency — ticket exists but isn't in the queue. Contact support."
        )

    return {
        "ticket_id": ticket_id,
        "status": "waiting",
        "event_name": event_name,
        "position_in_line": position_in_line,
        "people_ahead_of_you": people_ahead,
        "estimated_wait_seconds": people_ahead * SECONDS_PER_POSITION,
        "joined_at": ticket["joined_at"],
    }


@app.post("/queue/leave", status_code=200, tags=["Queue"])
def leave_queue(body: LeaveRequest):
    if body.ticket_id not in tickets:
        raise HTTPException(status_code=404, detail="Ticket not found.")

    ticket = tickets[body.ticket_id]

    if ticket["status"] != "waiting":
        return {
            "message": f"Ticket is already '{ticket['status']}', nothing to do.",
            "ticket_id": body.ticket_id,
        }

    event_name = ticket["event_name"]
    if event_name in events:
        try:
            events[event_name]["queue"].remove(body.ticket_id)
        except ValueError:
            pass

    ticket["status"] = "expired"
    ticket["expired_at"] = now_iso()

    return {
        "message": "You've left the queue.",
        "ticket_id": body.ticket_id,
    }


@app.post("/queue/admit", status_code=200, tags=["Admin"])
def admit_users(
    body: AdmitRequest,
    x_admin_secret: Optional[str] = Header(default=None),
):
    require_admin(x_admin_secret)
    event = get_event_or_404(body.event_name)

    admitted = []
    ts = now_iso()

    for _ in range(body.number_to_admit):
        if not event["queue"]:
            break
        tid = event["queue"].popleft()
        tickets[tid]["status"] = "admitted"
        tickets[tid]["admitted_at"] = ts
        admitted.append(tid)

        # Send admission email
        send_admission_email(
            to_email=tickets[tid]["email"],
            user_name=tickets[tid]["user_identifier"],
            event_name=body.event_name,
            ticket_id=tid
        )

    event["total_admitted"] += len(admitted)

    return {
        "message": f"Admitted {len(admitted)} user(s).",
        "event_name": body.event_name,
        "admitted_count": len(admitted),
        "admitted_tickets": admitted,
        "queue_remaining": len(event["queue"]),
        "total_admitted_all_time": event["total_admitted"],
    }


@app.get("/queue/peek/{event_name}", tags=["Admin"])
def peek_queue(
    event_name: str,
    limit: int = Query(10, ge=1, le=100, description="How many tickets to preview from the front"),
    x_admin_secret: Optional[str] = Header(default=None),
):
    require_admin(x_admin_secret)
    event = get_event_or_404(event_name)

    preview = list(event["queue"])[:limit]
    result = []
    for tid in preview:
        t = tickets.get(tid, {})
        result.append({
            "ticket_id": tid,
            "user_identifier": t.get("user_identifier"),
            "joined_at": t.get("joined_at"),
        })

    return {
        "event_name": event_name,
        "queue_length": len(event["queue"]),
        "preview": result,
    }