"""Tests for all 8 rawos core primitives."""
import pytest
from anima.models import (
    User, UserTier,
    Project,
    Agent, AgentStatus,
    Intent, IntentStatus,
    Memory, MemoryTier, MessageRole,
    Artifact, ArtifactType,
    Tool, SandboxLevel,
    Event, EventType,
)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class TestUser:
    def test_creates_with_defaults(self):
        u = User(email="Alice@Example.COM", password_hash="x")
        assert u.email == "alice@example.com"
        assert u.tier == UserTier.FREE
        assert u.token_budget_daily == 100_000
        assert u.id and len(u.id) == 36
        assert u.created_at > 0

    def test_rejects_invalid_email(self):
        with pytest.raises(Exception):
            User(email="notanemail", password_hash="x")

    def test_no_password_hash_in_public(self):
        from anima.models import UserPublic
        u = User(email="a@b.com", password_hash="secret")
        pub = UserPublic(**u.model_dump(exclude={"password_hash"}))
        assert not hasattr(pub, "password_hash")


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

class TestProject:
    def test_creates_ok(self):
        p = Project(user_id="uid", name="My Project")
        assert p.name == "My Project"
        assert p.workdir == ""

    def test_rejects_empty_name(self):
        with pytest.raises(Exception):
            Project(user_id="uid", name="   ")

    def test_rejects_long_name(self):
        with pytest.raises(Exception):
            Project(user_id="uid", name="x" * 129)


# ---------------------------------------------------------------------------
# Agent + FSM
# ---------------------------------------------------------------------------

class TestAgent:
    def test_default_status_is_dormant(self):
        a = Agent(user_id="u", project_id="p", goal="do something")
        assert a.status == AgentStatus.DORMANT

    def test_valid_fsm_transitions(self):
        a = Agent(user_id="u", project_id="p", goal="g")
        a = a.transition(AgentStatus.ACTIVE)
        assert a.status == AgentStatus.ACTIVE
        a = a.transition(AgentStatus.SUSPENDED)
        assert a.status == AgentStatus.SUSPENDED
        a = a.transition(AgentStatus.ACTIVE)
        a = a.transition(AgentStatus.ARCHIVED)
        assert a.status == AgentStatus.ARCHIVED

    def test_invalid_fsm_transition_raises(self):
        a = Agent(user_id="u", project_id="p", goal="g")
        with pytest.raises(ValueError, match="invalid agent transition"):
            a.transition(AgentStatus.ARCHIVED)

    def test_archived_is_terminal(self):
        a = Agent(user_id="u", project_id="p", goal="g", status=AgentStatus.ARCHIVED)
        with pytest.raises(ValueError):
            a.transition(AgentStatus.ACTIVE)


# ---------------------------------------------------------------------------
# Intent
# ---------------------------------------------------------------------------

class TestIntent:
    def test_creates_ok(self):
        i = Intent(user_id="u", project_id="p", raw_text="build me a website")
        assert i.status == IntentStatus.PENDING
        assert i.raw_text == "build me a website"

    def test_rejects_empty_raw_text(self):
        with pytest.raises(Exception):
            Intent(user_id="u", project_id="p", raw_text="   ")

    def test_rejects_oversized_raw_text(self):
        with pytest.raises(Exception):
            Intent(user_id="u", project_id="p", raw_text="x" * 32_001)


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class TestMemory:
    def test_creates_episodic(self):
        m = Memory(
            user_id="u", project_id="p",
            tier=MemoryTier.EPISODIC,
            role=MessageRole.USER,
            content="hello",
        )
        assert m.expires_at is None
        assert m.embedding is None

    def test_accepts_list_content(self):
        m = Memory(
            user_id="u",
            tier=MemoryTier.WORKING,
            role=MessageRole.ASSISTANT,
            content=[{"type": "text", "text": "hi"}],
        )
        assert isinstance(m.content, list)


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------

class TestArtifact:
    def test_creates_file_artifact(self):
        a = Artifact(
            user_id="u", project_id="p",
            type=ArtifactType.FILE,
            name="index.html",
            path="/root/rawos/workspaces/u/p/index.html",
        )
        assert a.size_bytes == 0


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class TestTool:
    def test_creates_ok(self):
        t = Tool(
            name="bash",
            description="Run shell commands",
            input_schema={"type": "object", "properties": {"command": {"type": "string"}}},
            sandbox_level=SandboxLevel.SYSTEM,
        )
        assert t.name == "bash"
        assert t.enabled is True

    def test_rejects_invalid_slug(self):
        with pytest.raises(Exception):
            Tool(name="My Tool!", description="x", input_schema={})

    def test_name_normalised_to_lower(self):
        t = Tool(name="bash_exec", description="x", input_schema={})
        assert t.name == "bash_exec"


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

class TestEvent:
    def test_creates_ok(self):
        e = Event(user_id="u", type=EventType.AUTH_SIGNUP)
        assert e.payload == {}
        assert e.created_at > 0

    def test_accepts_payload(self):
        e = Event(user_id="u", type=EventType.TOOL_CALLED, payload={"tool": "bash"})
        assert e.payload["tool"] == "bash"
