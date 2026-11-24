"""Same-origin local application. Run one worker with Qdrant Local."""

import json
import re
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.activity_clocks import activity_answer
from app.config import ROOT, Settings, settings_from_env
from app.distance import (
    DISTANCE,
    DistanceGuideCache,
    distance_followup,
    distance_question,
    route_distance,
    selected_trailhead,
)
from app.document_review import material_answer
from app.live import (
    ForecastDay,
    WalkingWindow,
    daily_forecast,
    forecast,
    live_intent,
    notices,
)
from app.live_chat import ChatContext, chat_lookup, read_slots
from app.live_snapshots import LiveSnapshots
from app.packing import rain_packing
from app.preparation import add_packing_clause, cumulative_training
from app.service import Assistant
from app.source_watch import report_dir
from app.stage_metrics import stage_measurement
from app.trail_updates import Section, add_local_sources, municipal_notices
from app.turn_context import TrailFocus, TrailSubjects
from app.variant_plans import (
    ROUTE_TERMS,
    PlanContext,
    comparison_followup,
    matching_routes,
    plan_places,
    requested_stage,
    route_followup,
    selected_schedule,
    variant_answer,
)

STATIC = Path(__file__).parent / "static"


class PriorTurn(BaseModel):
    question: str = Field(min_length=1, max_length=1200)
    answer: str = Field(min_length=1, max_length=1800)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_history: list[PriorTurn] = Field(default_factory=list, max_length=3)
    chat_context: ChatContext | None = None
    trail_focus: TrailFocus | None = None
    prior_planning_question: str | None = Field(default=None, max_length=1200)
    question: str = Field(min_length=1, max_length=1200)
    mode: Literal["rag", "baseline"] = "rag"
    offer_live_checks: bool = False
    variant_context: PlanContext | None = None
    distance_followup: bool = False
    planning_followup: bool = False
    reference_id: str | None = None
    top_k: int = Field(default=3, ge=1, le=6)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or settings_from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.assistant = Assistant(config)
        app.state.live_snapshots = LiveSnapshots()
        app.state.distance_guide = DistanceGuideCache()
        app.state.subjects = TrailSubjects(app.state.assistant.release)
        monitor = None
        if config.monitor_sources:
            monitor = subprocess.Popen([sys.executable, "-m", "app.source_watch", "--watch", "--release",
                                        str(config.release_dir), "--runtime", str(ROOT/"runtime")], cwd=ROOT)
        try:
            with httpx.Client(timeout=7, headers={"User-Agent": "Trailwise-ABC-Research/1.0"}) as public_sources:
                app.state.public_sources = public_sources
                yield
        finally:
            if monitor:
                monitor.terminate()
                monitor.wait(timeout=15)
            app.state.assistant.close()

    app = FastAPI(title="Trailwise · Nepal", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def local_headers(request: Request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and origin not in {f"http://{request.headers.get('host')}", f"https://{request.headers.get('host')}"}:
                return JSONResponse({"detail": "Cross-origin writes are disabled."}, status_code=403)
            try:
                content_length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "Invalid request length."}, status_code=400)
            if content_length < 0:
                return JSONResponse({"detail": "Invalid request length."}, status_code=400)
            if content_length > 16384:
                return JSONResponse({"detail": "Request too large."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.get("/api/health")
    def health():
        return {"ok": True, "release_id": app.state.assistant.release.manifest["release_id"]}

    @app.get("/api/status")
    def status():
        return app.state.assistant.status()

    @app.post("/api/ask")
    def ask(body: AskRequest):
        if body.reference_id and body.reference_id not in app.state.assistant.release.scope["allowed_reference_ids"]:
            raise HTTPException(422, "Reference is not part of the reviewed release.")
        if not body.question.strip():
            raise HTTPException(422, "Enter a question or reply.")
        if body.mode == "baseline":
            # The control sees only visible conversation and the selected menu label.
            # Resolving a numbered day through TrailSubjects would disclose project facts.
            history = []
            for turn in body.baseline_history:
                history.extend([{"role": "user", "content": turn.question},
                                {"role": "assistant", "content": turn.answer}])
            selected = {"ABC-KT-06": "Annapurna Base Camp · six-day round trip from Siwai",
                        "ABC-WV-CORRIDOR": "Annapurna Sanctuary trail · Wikivoyage route guide"}.get(body.reference_id)
            question = body.question.strip()
            ctx = body.chat_context
            if body.offer_live_checks:
                now = datetime.now(UTC)
                if ctx is None and body.baseline_history:
                    # Only user-visible place names, never the guide's resolved stage or evidence.
                    ctx = ChatContext()
                    for turn in body.baseline_history:
                        prior = read_slots(turn.question, ChatContext(), now)
                        if prior.point or prior.section != "ABC corridor":
                            ctx = ChatContext(point=prior.point, section=prior.section)
                public = chat_lookup(question, ctx, now, public_forecast, public_notices)
                if public:
                    return {**public, "mode": "baseline", "retrieval": {"mode": "none"}}
            if selected:
                question = f"Selected route: {selected}\n{question}"
            result = app.state.assistant.ask(question, "baseline", None, body.top_k, history=history)
            if body.offer_live_checks:
                location = read_slots(body.question, ChatContext(), now)
                if location.point or location.section != "ABC corridor":
                    result["chat_context"] = ChatContext(point=location.point, section=location.section).model_dump(mode="json")
            return result
        release = app.state.assistant.release
        subjects = app.state.subjects
        question = body.question.strip()
        selecting_distance = (
            body.mode == "rag" and body.distance_followup
            and body.trail_focus is not None and body.trail_focus.route is not None
        )
        if selecting_distance:
            question = selected_trailhead(question)
        selected_option = selecting_distance and distance_followup(question)
        if (body.mode == "rag" and body.offer_live_checks and body.trail_focus and body.trail_focus.route
                and not body.trail_focus.outside_route and live_intent(question) in {"forecast", "both"}
                and "Machhapuchhare Base Camp" not in body.trail_focus.places):
            question = re.sub(r"\b(at|in|for) (?:the )?base camp\b", r"\1 Annapurna Base Camp", question, flags=re.I)
        focus, resolved = subjects.resolve(question, body.trail_focus, body.reference_id)
        if body.variant_context and (parent_key := body.variant_context.active_key()) and parent_key != "siwai":
            # TrailSubjects' numbered-day index describes KeiTreks only.
            day = requested_stage(question.casefold(), body.variant_context)
            if day and not subjects.pattern.search(question):
                contextual = body.variant_context.model_copy(update={"stage":day})
                focus.places = plan_places(contextual)
                resolved = question + (" (Trail section: " + " to ".join(focus.places) + ".)" if focus.places else "")
        reference = body.reference_id or focus.reference
        if focus.outside_route:
            return {"mode": body.mode, "answer_kind": "scope_limit", "evidence": [], "warnings": [],
                    "answer": app.state.assistant.scope_limit(question) or
                              f"This guide covers Annapurna Base Camp. {focus.outside_route.upper()} is outside its reviewed routes.",
                    "trail_focus": focus.model_dump()}
        context_fields = {"variant_context": body.variant_context.model_dump()} if body.variant_context else {}
        if body.mode == "rag":
            personal = activity_answer(question, body.trail_focus)
            if personal:
                focus.personal_clock = personal.pop("personal_clock", None)
                return {**personal, **context_fields, "release_id": release.manifest["release_id"], "trail_focus": focus.model_dump()}
            comparison = comparison_followup(question, body.variant_context)
            if comparison:
                context = PlanContext.model_validate(comparison["variant_context"])
                focus.places = plan_places(context)
                focus.reference = "ABC-KT-06" if context.active_key() == "siwai" else None
                return {**comparison, "release_id": release.manifest["release_id"], "trail_focus": focus.model_dump()}
            material = material_answer(question, release, focus, body.chat_context)
            if material:
                flagged = {c["fact_id"] for c in material["evidence"]}.intersection(source_audit().get("review_fact_ids", []))
                if flagged:
                    material["warnings"].append("Source change awaiting review for " + ", ".join(sorted(flagged)) + ".")
                return {**material, **context_fields, "release_id": release.manifest["release_id"], "trail_focus": focus.model_dump()}
        if body.offer_live_checks and body.mode == "rag":
            # Weather replies such as "07:00" already have point and time slots.
            active_live = body.chat_context and body.chat_context.tool
            live = chat_lookup(question if active_live else resolved, body.chat_context,
                               datetime.now(UTC), point_forecast, trail_notices)
            if live:
                add_packing_clause(live, question, release, reference)
                return {**live, **context_fields, "trail_focus": focus.model_dump()}
        if body.mode == "rag" and release.manifest["release_id"] in {"ABC-KT06-LOCAL-TEST-20261122-R1", "ABC-KT06-PUBLIC-20261125-R1"}:
            rain = rain_packing(question)
            if rain:
                return {**rain, **context_fields, "mode": "rag", "release_id": release.manifest["release_id"],
                        "trail_focus": focus.model_dump()}
            load = cumulative_training(question.casefold(), release, reference)
            if load and not selected_option:
                return {**load, **context_fields, "mode":"rag", "warnings":[], "release_id":release.manifest["release_id"], "trail_focus":focus.model_dump()}
            measurement = stage_measurement(question, release, focus, body.trail_focus, body.variant_context, reference)
            if measurement:
                if measurement.pop("single_observation", False):
                    measurement = app.state.assistant.generate_observation(question, measurement)
                flagged = {c["fact_id"] for c in measurement["evidence"]}.intersection(source_audit().get("review_fact_ids", []))
                if flagged:
                    measurement["warnings"].append("Source change awaiting review for " + ", ".join(sorted(flagged)) + ".")
                return {**context_fields, **measurement, "release_id": release.manifest["release_id"]}
            plan = None
            if not selected_option:
                plan = route_followup(question, body.variant_context, release) or variant_answer(
                    question, body.variant_context, focus, body.distance_followup, body.reference_id)
            if plan:
                context = PlanContext.model_validate(plan["variant_context"])
                focus.route = "Annapurna Base Camp"
                focus.places = plan_places(context)
                focus.reference = "ABC-KT-06" if context.active_key() == "siwai" else None
                return {**plan, "trail_focus": focus.model_dump(), "release_id": release.manifest["release_id"]}
        distance_query = resolved
        if body.distance_followup and body.trail_focus and body.trail_focus.route:
            if distance_followup(question):
                distance_query = f"How far is the ABC trek {question.rstrip('?.!')}?"
            elif not re.search(r"\b(?:ABC|Annapurna Base Camp)\b", question, re.I):
                places = " and ".join(focus.places)
                distance_query = f"{question} ABC {places}"
        stated_routes = matching_routes(question)
        if (focus.route and DISTANCE.search(question)
                and not re.search(r"\b(?:abc|annapurna base camp)\b", question, re.I)
                and (stated_routes or len(focus.places) <= 1 or body.variant_context)):
            route = ""
            if not stated_routes:
                if body.variant_context and (key := body.variant_context.active_key()):
                    route = ROUTE_TERMS[key]
                else:
                    route = " ".join(focus.places)
            distance_query = f"{question} ABC {route}"
        if (body.mode == "rag" and release.manifest["release_id"] in {"ABC-KT06-LOCAL-TEST-20261122-R1", "ABC-KT06-PUBLIC-20261125-R1"}
                and distance_question(distance_query, reference)):
            answer = route_distance(distance_query, release,
                                    app.state.public_sources if body.offer_live_checks else None, reference, app.state.distance_guide)
            if stated_routes and (body.variant_context or selected_option):
                distance_plan = (body.variant_context or PlanContext()).model_copy(update={"keys": stated_routes, "stage": None, "suggested": None})
                context_fields["variant_context"] = distance_plan.model_dump()
                if selected_option and len(stated_routes) == 1:
                    summary, source = selected_schedule(stated_routes[0])
                    answer["answer"] += "\n\n" + summary
                    answer["itinerary_sources"] = [source]
            return {**answer, **context_fields, "trail_focus": focus.model_dump()}
        if body.planning_followup and re.search(r"\b(?:days?|transfers?|travel)\b", question, re.I):
            # Preserve the walking-budget parser's short reply format.
            resolved = question
        if body.prior_planning_question and re.search(
            r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|morning|afternoon|"
            r"days?|transfer|arrive|depart|finish|start|confirm)\b|\d+:\d+", question, re.I
        ) and not re.search(r"\b(?:weather|equipment|gear|poles|rain|snow|distance)\b", question, re.I):
            resolved = body.prior_planning_question + "\n" + question
        # Published alternatives have their own timelines. Similar place names never
        # make a KeiTreks stage measurement evidence for another operator's day.
        active = body.variant_context.active_key() if body.variant_context else None
        if stated_routes and len(stated_routes) == 1 and (not active or re.search(r"switch|instead|version|itinerary|route from", question, re.I)):
            active = stated_routes[0]
        alternative = body.mode == "rag" and active is not None and active != "siwai"
        answer = app.state.assistant.ask(resolved, body.mode, None if alternative else reference, body.top_k,
                                         alternative_route=alternative,
                                         planning_followup=body.planning_followup)
        answer.update(context_fields)
        answer["trail_focus"] = (focus if body.variant_context else subjects.from_answer(focus, answer)).model_dump()
        if answer["answer_kind"] == "clarification":
            answer["planning_question"] = resolved[-1200:]
        if body.offer_live_checks and body.mode == "rag":
            context = read_slots(resolved, ChatContext(), datetime.now(UTC))
            if context.point or context.section != "ABC corridor":
                answer["chat_context"] = context.model_dump(mode="json")
            audit = source_audit()
            evidence = {e["fact_id"] for e in answer.get("evidence", [])}
            flagged = sorted(evidence.intersection(audit.get("review_fact_ids", [])))
            if flagged:
                answer.setdefault("warnings", []).append("Source change awaiting review for " + ", ".join(flagged)
                    + ". These records describe the frozen reference version.")
        return answer

    def public_forecast(window):
        lookup = forecast if isinstance(window, WalkingWindow) else daily_forecast
        return app.state.live_snapshots.get(("weather", window.model_dump_json()),
            lambda: lookup(window, app.state.public_sources, datetime.now(UTC)))

    def notice_snapshot(section, folder):
        client = app.state.public_sources
        now = datetime.now(UTC)
        national = app.state.live_snapshots.get("national", lambda: notices(client, now))
        municipal = app.state.live_snapshots.get("municipal", lambda: municipal_notices(client, now))
        return add_local_sources(national, client, now, folder, section, municipal)

    def public_notices(section):
        return notice_snapshot(section, None)

    @app.post("/api/live/forecast")
    def point_forecast(window: WalkingWindow | ForecastDay):
        result = public_forecast(window)
        if not isinstance(window, WalkingWindow):
            return result
        if result["status"] == "forecast" and window.point in {"Deurali", "ABC"}:
            result["planning_evidence"] = [c for c in app.state.assistant.release.chunks
                                           if c["fact_id"] == "G07" and c["reference_id"] == "ABC-KT-06"]
            if result["planning_evidence"] and "G07" in source_audit().get("review_fact_ids", []):
                result["source_review_warning"] = "The source behind G07 has changed. This gear note is from the frozen reference version and is awaiting review."
        return result

    @app.post("/api/live/notices")
    def trail_notices(section: Section = "ABC corridor"):
        return notice_snapshot(section, ROOT/"runtime/field-reports")

    @app.get("/api/source-audit")
    def source_audit():
        path = report_dir(config.release_dir, ROOT/"runtime")/"latest.json"
        empty = {"checked_at": None, "targets": [], "review_fact_ids": [], "unavailable_fact_ids": []}
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return empty
        except (OSError, ValueError):
            return {**empty, "error": "The source audit could not be read."}

    @app.get("/")
    def home():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
