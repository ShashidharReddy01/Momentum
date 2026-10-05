"""Phase 7 load test (E7.1): ~150 people using Momentum at once, on the `seed --scale` workspace.

Each simulated person signs in with dev login as one of the scale people and spends the day the
way people do: Home and My Tasks, a project's list, task details and activity, the inbox, search,
and now and then edits a task, comments, or adds a task; dashboards and workload less often.
Think time is 2-8 s between actions, so 150 people make roughly 25-30 requests a second.

Run (server from tools/load/serve.sh on :8150):
    uvx --from "locust==2.42.6" locust -f tools/load/locustfile.py --host http://localhost:8150 \
        --users 150 --spawn-rate 10 --run-time 10m --headless --csv docs/progress/load/run
Budgets (phase-7.md E7.1): p95 < 150 ms for reads, < 300 ms for writes, no errors.
"""

from __future__ import annotations

import itertools
import random
import threading

from locust import HttpUser, between, task

H = {"X-Requested-With": "momentum"}
_people: list[dict[str, str]] = []
_next = itertools.count()
_lock = threading.Lock()


def _person(client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    with _lock:
        if not _people:
            users = client.get("/api/v1/dev/users", name="setup: dev users").json()
            _people.extend(u for u in users if u["email"].startswith("scale-"))
        return _people[next(_next) % len(_people)]


class Person(HttpUser):
    wait_time = between(2, 8)

    def on_start(self) -> None:
        me = _person(self.client)
        self.me = me["id"]
        self.client.post("/api/v1/dev/login", json={"user_id": me["id"]}, headers=H, name="login")
        projects = self.client.get("/api/v1/projects", name="GET /projects").json()["data"]
        self.projects = [p["id"] for p in projects] or [None]
        self.task_ids: list[str] = []  # not `tasks`: that name is locust's own list of actions

    def _project(self) -> str | None:
        return random.choice(self.projects)

    @task(5)
    def home(self) -> None:
        self.client.get("/api/v1/home", name="GET /home")

    @task(4)
    def my_tasks(self) -> None:
        r = self.client.get("/api/v1/me/tasks", name="GET /me/tasks")
        if r.ok:
            data = r.json().get("data") or []
            ids = [t["id"] for t in data if isinstance(t, dict) and "id" in t]
            if ids:
                self.task_ids = ids[:50]

    @task(6)
    def project_list(self) -> None:
        pid = self._project()
        if pid is None:
            return
        r = self.client.get(f"/api/v1/projects/{pid}/tasks", name="GET /projects/:id/tasks")
        if r.ok:
            ids = [t["id"] for t in r.json()["data"]]
            if ids:
                self.task_ids = random.sample(ids, min(50, len(ids)))
        self.client.get(f"/api/v1/projects/{pid}/sections", name="GET /projects/:id/sections")

    @task(5)
    def task_detail(self) -> None:
        if not self.task_ids:
            return
        tid = random.choice(self.task_ids)
        self.client.get(f"/api/v1/tasks/{tid}", name="GET /tasks/:id")
        self.client.get(f"/api/v1/tasks/{tid}/feed", name="GET /tasks/:id/feed")

    @task(3)
    def inbox(self) -> None:
        self.client.get("/api/v1/notifications", name="GET /notifications")

    @task(1)
    def search(self) -> None:
        q = random.choice(["pricing", "review", "budget", "roadmap", "docs", "contract"])
        self.client.get("/api/v1/search", params={"q": q}, name="GET /search")

    @task(2)
    def edit_task(self) -> None:
        if not self.task_ids:
            return
        tid = random.choice(self.task_ids)
        body = random.choice(
            [{"priority": random.choice(["low", "medium", "high"])}, {"estimate_minutes": 120}]
        )
        self.client.patch(f"/api/v1/tasks/{tid}", json=body, headers=H, name="PATCH /tasks/:id")

    @task(1)
    def comment(self) -> None:
        if not self.task_ids:
            return
        tid = random.choice(self.task_ids)
        text = "Load test comment"
        body = {
            "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]},
        }
        self.client.post(f"/api/v1/tasks/{tid}/comments", json=body, headers=H, name="POST /tasks/:id/comments")

    @task(1)
    def add_task(self) -> None:
        pid = self._project()
        if pid is None:
            return
        self.client.post(
            f"/api/v1/projects/{pid}/tasks", json={"title": "Load test task"}, headers=H,
            name="POST /projects/:id/tasks",
        )

    @task(1)
    def dashboard(self) -> None:
        pid = self._project()
        if pid is None:
            return
        self.client.get(f"/api/v1/dashboards/project/{pid}", name="GET /dashboards/project/:id")

    @task(1)
    def workload(self) -> None:
        # like the page: the grid alone, then one person's tasks when a cell is opened
        self.client.get("/api/v1/workload", params={"tasks_for": "none"}, name="GET /workload")
        if self.me and random.random() < 0.5:
            self.client.get(
                "/api/v1/workload", params={"tasks_for": self.me}, name="GET /workload (a row)"
            )
