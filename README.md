QueueIQ

QueueIQ is a virtual waiting room API. When too many people hit your server at the same time like during a sneaker drop, concert ticket release, or course registration opening, instead of letting your server crash, you put users into a queue.

This API acts as an infrastructure layer. Your app talks to our API to issue tickets, check positions in line, and admit users when your system is ready. There is no frontend on our side. We just handle the queue logic cleanly and predictably.
What this actually solves

A lot of systems break when traffic spikes. Instead of handling overload poorly, QueueIQ makes traffic controlled and fair. Everyone gets a ticket, everyone has a position, and no one can cut the line.
This is infrastructure. It is meant to plug into other apps.

Tech Stack
* FastAPI for async performance and automatic API docs at `/docs`
* Pydantic v2 for strict input validation
* collections.deque for O(1) queue operations
* In memory state for hackathon simplicity
* Mailjet for real-time email notifs when users are admitted

How it works
1. An admin creates an event. Example: `jordan-drop-2026`
2. Users join the queue for that event
3. They receive a ticket_id and their position
4. Users poll the status endpoint to see updates
5. The admin admits users in batches when capacity is available
6. Users marked as admitted are allowed through
Everything is explicit and predictable.
Design choices we care about

Idempotent joins
If a user retries the join request, they do not get two tickets. They get the same ticket back. This prevents duplicate spots and race conditions.
Proper queue data structure
We use deque instead of a list. Using list.pop(0) is O(n) and inefficient for queues. deque.popleft() is O(1). For something called a queue, that matters.

Clear error handling
We return correct HTTP status codes:
* 200 for success
* 201 for created
* 400 for bad input
* 401 for unauthorized admin actions
* 404 for missing tickets or events
* 409 if an event already exists
* 410 if an event is closed
* 503 if the queue is full
Errors always include a detail field explaining what went wrong.

Admin secret in headers
We use an X-Admin-Secret header instead of putting secrets in the body. This is cleaner and aligns with how authentication is normally handled.
Events as first class resources
Queues are tied to events. This allows multiple independent queues to exist at the same time. Admins explicitly control when an event opens and closes.

Why this is a strong hackathon API
* It solves a real infrastructure problem
* It handles state correctly
* It is idempotent where it needs to be
* It returns proper HTTP codes
* It has clear resource modeling
* It is testable entirely with curl or Postman
* FastAPI automatically provides interactive docs
There is no UI because the goal is developer experience and correctness.

What we would build next
If this were production ready, we would:
* Replace in memory storage with Redis for durability and scalability
* Add WebSocket support to push position updates instead of polling
* Add rate limiting on join to prevent bot abuse
* Add webhooks so apps can be notified when users are admitted
* Add signed ticket IDs using HMAC so authenticity can be verified without a database lookup