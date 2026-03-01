QueueIQ

A virtual waiting room API. When too many people hit your server at once — sneaker drop, concert tickets, course registration — instead of crashing, you put them in a queue.
Your app calls our API to issue tickets, check positions, and admit users when you're ready. No frontend. Just the queue logic.

Stack

FastAPI — async, auto-generates interactive docs at /docs
Pydantic v2 — strict input validation
collections.deque — O(1) queue operations. list.pop(0) is O(n), which is the wrong data structure for a queue
Mailjet — emails users when they get admitted
In-memory state — fine for a hackathon, Redis in prod


Quickstart
bashpip install fastapi uvicorn pydantic mailjet-rest
uvicorn main:app --reload
Then go to http://127.0.0.1:8000/docs — FastAPI generates a full interactive UI where you can test every endpoint.
Environment variables (all have defaults, none are required to get started):
bashexport QUEUE_ADMIN_SECRET="your_secret"
export SECONDS_PER_POSITION="120"
export MAX_QUEUE_CAPACITY="10000"
export ADMISSION_WINDOW_SECONDS="120"   # how long admitted users have to act
export MJ_API_KEY="..."
export MJ_SECRET_KEY="..."
export SENDER_EMAIL="..."

How it works

Admin creates an event — e.g. jordan-drop-2026
Users join and get a ticket_id and their position
Users poll /queue/status to see where they're at
Admin calls /queue/admit when the server has room
Admitted users get an email with a deadline — they have 2 minutes to act
If they don't, /queue/expire-stale releases their spot to the next person
Admin can pause and resume the event without losing the queue


Endpoints
Admin endpoints need X-Admin-Secret: <your_secret> in the header.

Meta
GET / — service info
GET /health — live stats across all events

Events
POST /events 🔒 — create an event
bashcurl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: stripe_hackathon_2026" \
  -d '{
    "event_name": "jordan-drop-2026",
    "description": "AJ1 Retro drop",
    "capacity_hint": 500,
    "admission_window_seconds": 120
  }' | jq
admission_window_seconds is per-event. A flash sale might give 2 minutes, a class registration might give an hour.
GET /events 🔒 — list all events. Filter with ?status=open, ?status=paused, or ?status=closed
GET /events/{event_name} — public stats, no auth needed
GET /events/{event_name}/stats 🔒 — average wait time, longest wait, ticket breakdown, how many spots were lost to inaction
POST /events/{event_name}/pause 🔒 — pause admissions without killing the queue. Users can still join and hold their spot.
POST /events/{event_name}/resume 🔒 — unpause
DELETE /events/{event_name} 🔒 — close permanently. Everyone still waiting gets expired.

Tickets
GET /tickets/{ticket_id} 🔒 — full ticket info: user, email, metadata, all timestamps, live position if still waiting, countdown if admitted

Queue
POST /queue/join — join the queue
bashcurl -s -X POST http://localhost:8000/queue/join \
  -H "Content-Type: application/json" \
  -d '{
    "user_identifier": "alice",
    "event_name": "jordan-drop-2026",
    "email": "alice@example.com",
    "metadata": {"source": "mobile", "locale": "en-US"}
  }' | jq
Idempotent: if the same user calls join twice, they get their existing ticket back (HTTP 200, not 201). If the event is paused they can still join, a note field tells them admissions are on hold.
GET /queue/status/{ticket_id}:  check where a ticket stands
StatusMeaningwaitingStill in line. Returns live position, wait estimate, and a note if paused.admittedLet them through. Returns admission_expires_at and seconds remaining.expiredIncludes expire_reason — event_closed, admission_window_elapsed, or left_voluntarily.
POST /queue/leave: leave voluntarily. Safe to call multiple times.

Admin
POST /queue/admit 🔒 — admit the next N users
bashcurl -s -X POST http://localhost:8000/queue/admit \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: stripe_hackathon_2026" \
  -d '{"event_name": "jordan-drop-2026", "number_to_admit": 5}' | jq
Blocked with a 409 if the event is paused. Returns admission_expires_at so you know when spots get released if nobody acts. Each admitted user gets an email.
POST /queue/expire-stale 🔒 — release spots from admitted users who didn't act in time
bashcurl -s -X POST \
  "http://localhost:8000/queue/expire-stale?event_name=jordan-drop-2026" \
  -H "X-Admin-Secret: stripe_hackathon_2026" | jq
In production this would run on a cron every minute. Here it's a manual endpoint so you can trigger and watch it happen.
GET /queue/peek/{event_name} 🔒 — see who's at the front of the line without admitting anyone

Error codes
* CodeWhen200OK, or idempotent join201Created400Bad input401Wrong or missing admin secret404Ticket or event not found409Event already exists, already paused, or admitting from a paused/closed event410Event is closed, no new joins503Queue is full
* Every error has a detail field telling you what went wrong.

Demo walkthrough
bashBASE=http://localhost:8000
SECRET="stripe_hackathon_2026"

# create an event
curl -s -X POST $BASE/events \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: $SECRET" \
  -d '{"event_name":"demo-drop","admission_window_seconds":120}' | jq

# join as 3 users
curl -s -X POST $BASE/queue/join \
  -H "Content-Type: application/json" \
  -d '{"user_identifier":"alice","event_name":"demo-drop","email":"alice@example.com"}' | jq

curl -s -X POST $BASE/queue/join \
  -H "Content-Type: application/json" \
  -d '{"user_identifier":"bob","event_name":"demo-drop","email":"bob@example.com"}' | jq

curl -s -X POST $BASE/queue/join \
  -H "Content-Type: application/json" \
  -d '{"user_identifier":"carol","event_name":"demo-drop","email":"carol@example.com"}' | jq

# pause the event then try to admit — should get a 409
curl -s -X POST $BASE/events/demo-drop/pause \
  -H "X-Admin-Secret: $SECRET" | jq

curl -s -X POST $BASE/queue/admit \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: $SECRET" \
  -d '{"event_name":"demo-drop","number_to_admit":1}' | jq

# resume and admit 2
curl -s -X POST $BASE/events/demo-drop/resume \
  -H "X-Admin-Secret: $SECRET" | jq

curl -s -X POST $BASE/queue/admit \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: $SECRET" \
  -d '{"event_name":"demo-drop","number_to_admit":2}' | jq

# check alice — admitted with a countdown
curl -s $BASE/queue/status/ALICES_TICKET_ID | jq

# wait 2 minutes, then expire stale spots
curl -s -X POST "$BASE/queue/expire-stale?event_name=demo-drop" \
  -H "X-Admin-Secret: $SECRET" | jq

# alice is now expired — reason: admission_window_elapsed
curl -s $BASE/queue/status/ALICES_TICKET_ID | jq

# pull stats
curl -s "$BASE/events/demo-drop/stats" \
  -H "X-Admin-Secret: $SECRET" | jq

# close the event — carol expires
curl -s -X DELETE $BASE/events/demo-drop \
  -H "X-Admin-Secret: $SECRET" | jq

Why we built it this way
* Admission window: when someone gets admitted, admission_expires_at is set and the status endpoint shows a live countdown. /queue/expire-stale handles cleanup. The API enforces what the email says — if we tell you that you have 2 minutes, we actually take your spot back after 2 minutes.
deque not list: deque.popleft() is O(1). list.pop(0) shifts every element. It's one line but it's the difference between doing it right and doing it wrong.
* Idempotent join: if a browser crashes and retries, the user doesn't get two spots. Same identifier, same ticket.
* Pause vs close: pause is temporary, queue stays intact. Close is permanent, everyone waiting gets expired. We kept these as separate operations because they mean different things.
* expire_reason: without it, every expired ticket looks the same. With it you can tell who left voluntarily, who ran out of time, and who got caught by an event closing.
* Auth in headers: body fields get logged. Headers don't. X-Admin-Secret stays out of your access logs.
Per-event admission windows — hardcoding 2 minutes globally doesn't work for every use case. You set it when you create the event.

What we'd build next

* Rate limiting on /queue/join so bots can't flood the line
* Auto-admit when a stale spot gets released, pull the next person in automatically