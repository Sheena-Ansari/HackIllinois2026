# QueuePass — Virtual Waiting Room API

QueuePass stops your server from crashing during high-traffic events like sneaker drops, ticket sales, or product launches. Instead of everyone hitting your server at once, users are placed in a fair virtual queue and admitted in controlled batches.

---

## Tech Stack

| Tool | Why we used it |
|---|---|
| **FastAPI** | Fast, async Python framework — automatically generates interactive API docs at `/docs` |
| **Pydantic v2** | Validates all request and response data automatically |
| **collections.deque** | Built-in Python queue — O(1) performance for adding/removing users |
| **In-memory storage** | Simple, no database setup needed (note: data clears on restart) |
| **Mailjet** | Sends an email to users the moment they're admitted |

---

## Setup & Running the API

**1. Install dependencies**

```bash
pip install fastapi uvicorn pydantic mailjet_rest
```

**2. Set environment variables**

```bash
export QUEUE_ADMIN_SECRET="stripe_hackathon_2026"   # default if not set
export SECONDS_PER_POSITION=120                      # used to estimate wait time
export MAX_QUEUE_CAPACITY=10000                      # max users per queue

export MJ_API_KEY="your_mailjet_key"                 # required for email notifications
export MJ_SECRET_KEY="your_mailjet_secret"
export SENDER_EMAIL="you@yourdomain.com"
```

**3. Start the server**

```bash
uvicorn main:app --reload
```

**4. Open the interactive docs**

```
http://127.0.0.1:8000/docs
```

The docs let you read every endpoint, see exactly what to send, and test live requests in your browser — no extra tools needed.

---

## How to Use the API

There are two roles: **Admin** and **User**. Here's the typical flow:

### Step 1 — Admin creates an event

```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: stripe_hackathon_2026" \
  -d '{"event_name": "jordan-drop-2026", "description": "Limited release", "capacity_hint": 500}'
```

### Step 2 — User joins the queue

```bash
curl -X POST http://127.0.0.1:8000/queue/join \
  -H "Content-Type: application/json" \
  -d '{"user_identifier": "sheena123", "event_name": "jordan-drop-2026", "email": "user@example.com"}'
```

The response tells them their position and estimated wait:

```json
{
  "ticket_id": "tkt_ab12cd34ef56",
  "position_in_line": 42,
  "people_ahead_of_you": 41,
  "estimated_wait_seconds": 4920,
  "status": "waiting"
}
```

> Save the `ticket_id` — you'll need it to check status. If a user calls this endpoint again, they'll get their existing ticket back instead of a duplicate spot.

### Step 3 — User checks their status

```bash
curl http://127.0.0.1:8000/queue/status/tkt_ab12cd34ef56
```

### Step 4 — Admin admits users

```bash
curl -X POST http://127.0.0.1:8000/queue/admit \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: stripe_hackathon_2026" \
  -d '{"event_name": "jordan-drop-2026", "number_to_admit": 10}'
```

This removes users from the front of the queue, marks them as admitted, and automatically sends each one an email with their ticket ID and a 10-minute window to complete their action.

---

## Email Notifications

When a user is admitted, Mailjet sends them an email:

- **Subject:** `You're in! Access granted for {event_name}`
- **Includes:** Their ticket ID, the event name, and a reminder that they have **10 minutes** to complete their purchase before their spot expires.

Email requires `MJ_API_KEY`, `MJ_SECRET_KEY`, and `SENDER_EMAIL` to be set. If they're missing, admission still works — the email will just silently fail and log an error.

---

## When Something Goes Wrong

Every error returns the same simple format:

```json
{ "detail": "Explanation of what went wrong" }
```

| Code | What it means |
|---|---|
| `400` | You sent bad or missing data |
| `401` | Wrong or missing `X-Admin-Secret` header |
| `404` | Ticket or event not found |
| `409` | An event with that name already exists |
| `410` | Event is closed — no new entries accepted |
| `503` | Queue is at max capacity, try again later |

The `detail` message will always tell you specifically what to fix — not just the code.

---

## All Endpoints

| Method | Path | Who |
|---|---|---|
| `GET` | `/` | Anyone |
| `GET` | `/health` | Anyone |
| `POST` | `/events` | Admin |
| `GET` | `/events` | Admin |
| `GET` | `/events/{event_name}` | Anyone |
| `DELETE` | `/events/{event_name}` | Admin |
| `POST` | `/queue/join` | User |
| `GET` | `/queue/status/{ticket_id}` | User |
| `POST` | `/queue/leave` | User |
| `POST` | `/queue/admit` | Admin |
| `GET` | `/queue/peek/{event_name}` | Admin |

---

## Notes

- **In-memory only** — restarting the server clears all events and tickets. This is intentional for the hackathon.
- **Admin routes** all require the `X-Admin-Secret` header.
- **`event_name` is auto-slugified** — spaces and special characters are replaced with `-`.
- **Optional `metadata` field** on `/queue/join` accepts any key-value pairs (e.g. locale, referral source).