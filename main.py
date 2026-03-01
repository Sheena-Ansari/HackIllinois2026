from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uuid
import os


app = FastAPI(
    title="QueueIQ API",
    description="B2B Infrastructure for managing high-traffic virtual waiting rooms.",
    version="1.0.0"
)


# --- In-Memory Database ---
waiting_room_queue = []
ticket_database = {}


# --- Data Models ---
class JoinRequest(BaseModel):
    user_identifier: str
    event_name: str


class AdmitRequest(BaseModel):
    number_to_admit: int
    admin_secret: str


# --- ENDPOINTS ---


@app.get("/")
def home():
    return {"message": "QueueIQ API is live. Visit /docs for documentation."}


@app.post("/queue/join", status_code=201)
def join_waiting_room(request: JoinRequest):
    ticket_id = f"tkt_{uuid.uuid4().hex[:8]}"
    ticket_database[ticket_id] = {
        "user_identifier": request.user_identifier,
        "event_name": request.event_name,
        "status": "waiting"
    }
    waiting_room_queue.append(ticket_id)
    position = len(waiting_room_queue)
    return {
        "message": "Successfully joined the waiting room.",
        "ticket_id": ticket_id,
        "position_in_line": position,
        "estimated_wait_minutes": position * 2
    }


@app.get("/queue/status/{ticket_id}")
def check_queue_status(ticket_id: str):
    if ticket_id not in ticket_database:
        raise HTTPException(status_code=404, detail="Invalid ticket ID. Please join the queue first.")
    ticket_info = ticket_database[ticket_id]
    if ticket_info["status"] == "admitted":
        return {
            "ticket_id": ticket_id,
            "status": "admitted",
            "action": "You may now access the checkout page!"
        }
    try:
        position_index = waiting_room_queue.index(ticket_id)
        actual_position = position_index + 1
        return {
            "ticket_id": ticket_id,
            "status": "waiting",
            "people_ahead_of_you": position_index,
            "position_in_line": actual_position
        }
    except ValueError:
        raise HTTPException(status_code=500, detail="Queue error. Ticket not found in active line.")


@app.post("/queue/admit", status_code=200)
def admit_users(request: AdmitRequest):
    if request.admin_secret != os.getenv("ADMIN_SECRET", "queueiq_admin_2026"):
        raise HTTPException(status_code=401, detail="Unauthorized. Invalid admin secret.")
    if request.number_to_admit <= 0:
        raise HTTPException(status_code=400, detail="Must admit at least 1 person.")
    admitted_users = []
    for _ in range(request.number_to_admit):
        if len(waiting_room_queue) > 0:
            lucky_ticket = waiting_room_queue.pop(0)
            ticket_database[lucky_ticket]["status"] = "admitted"
            admitted_users.append(lucky_ticket)
        else:
            break
    return {
        "message": f"Successfully admitted {len(admitted_users)} users.",
        "queue_remaining": len(waiting_room_queue),
        "admitted_tickets": admitted_users
    }


@app.get("/queue/stats")
def get_queue_stats():
    total_waiting = len(waiting_room_queue)
    total_admitted = sum(1 for t in ticket_database.values() if t["status"] == "admitted")
    return {
        "total_waiting": total_waiting,
        "total_admitted": total_admitted,
        "estimated_clear_time_minutes": total_waiting * 2
    }


@app.delete("/queue/leave/{ticket_id}")
def leave_queue(ticket_id: str):
    if ticket_id not in ticket_database:
        raise HTTPException(status_code=404, detail="Invalid ticket ID.")
    if ticket_database[ticket_id]["status"] == "admitted":
        raise HTTPException(status_code=400, detail="You are already admitted, no need to leave.")
    waiting_room_queue.remove(ticket_id)
    del ticket_database[ticket_id]
    return {
        "message": "Successfully left the queue.",
        "ticket_id": ticket_id
    }



