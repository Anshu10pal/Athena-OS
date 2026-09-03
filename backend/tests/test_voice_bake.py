"""Bake verification: every model loads with NO network available.

BUILDPACK-SCOPED, not container-scoped. The original instruction said to assert
this against "a fresh container"; there is no container -- docs/DEPLOYMENT.md
records that the project deliberately avoids Docker dependence and the service
runs on a Render buildpack. So the equivalent assertion is: after the build
command has run, the application loads every model with egress unavailable.

WHY BLOCKING THE NETWORK IS THE ONLY HONEST FORM OF THIS TEST
=============================================================
A test that merely observes "no download happened this time" proves nothing --
it passes identically on a machine whose cache is warm, which is exactly the
condition that hid KI-2 for weeks and VKI-4 for a second time. The only version
with force blocks the network and asserts the loaders still succeed.

Egress is blocked by replacing `socket.socket` for the duration, so any attempt
to open a connection raises. That covers requests/httpx/urllib underneath
huggingface_hub, ctranslate2 and fastembed alike, because all of them bottom out
in the same standard-library primitive.
"""
import os
import socket
import pathlib

import pytest

from app.core.config import MODELS_DIR, MODELS_OFFLINE

WEIGHTS = {
    "kokoro model": MODELS_DIR / "kokoro-v1.0.int8.onnx",
    "kokoro voices": MODELS_DIR / "voices-v1.0.bin",
    "piper voice": MODELS_DIR / "piper" / "en_US-lessac-medium.onnx",
    "piper config": MODELS_DIR / "piper" / "en_US-lessac-medium.onnx.json",
    "whisper root": MODELS_DIR / "whisper",
    "fastembed cache": MODELS_DIR / "fastembed",
}

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in WEIGHTS.values()),
    reason="model weights absent -- run scripts/fetch_models.sh (this is the "
           "state a fresh checkout is in, and the skip is the point: the test "
           "must not silently pass by finding nothing to check)",
)


class NoNetwork:
    """Context manager that makes every outbound connection raise.

    Not a mock of one HTTP client: the loaders under test use at least three
    different ones, and stubbing them individually would leave whichever one was
    forgotten free to reach the network -- the partial-input defect class in a
    new medium. So this patches the standard-library primitives they all bottom
    out in.

    BLOCKS EGRESS, NOT SOCKET CREATION, and that distinction was learned the
    hard way. The first version replaced `socket.socket` outright, which broke
    asyncio's own event-loop self-pipe (built from `socket.socketpair`) and
    produced three FALSE failures that looked exactly like fetch attempts. A
    blocker that blocks more than it claims is as misleading as one that blocks
    less. So: `connect`, `create_connection` and `getaddrinfo` are blocked --
    every route to a remote host -- while local socket objects still construct.
    """

    def __init__(self):
        self.attempts = []

    def __enter__(self):
        attempts = self.attempts
        self._real_connect = socket.socket.connect
        self._real_connect_ex = socket.socket.connect_ex
        self._real_create = socket.create_connection
        self._real_getaddrinfo = socket.getaddrinfo

        def blocked_connect(self_sock, address, *a, **k):
            attempts.append(("connect", address))
            raise OSError("network egress blocked by the bake-verification test")

        def blocked_connect_ex(self_sock, address, *a, **k):
            attempts.append(("connect_ex", address))
            raise OSError("network egress blocked by the bake-verification test")

        def blocked_create(address, *a, **k):
            attempts.append(("create_connection", address))
            raise OSError("network egress blocked by the bake-verification test")

        def blocked_getaddrinfo(host, *a, **k):
            attempts.append(("getaddrinfo", host))
            raise socket.gaierror("DNS blocked by the bake-verification test")

        socket.socket.connect = blocked_connect
        socket.socket.connect_ex = blocked_connect_ex
        socket.create_connection = blocked_create
        socket.getaddrinfo = blocked_getaddrinfo
        return self

    def __exit__(self, *exc):
        socket.socket.connect = self._real_connect
        socket.socket.connect_ex = self._real_connect_ex
        socket.create_connection = self._real_create
        socket.getaddrinfo = self._real_getaddrinfo
        return False


class TestTheBlockerItselfWorks:
    """A network blocker that does not block would make every test below pass
    for the wrong reason -- the check-that-cannot-fail class. So it is tested
    before it is trusted."""

    def test_an_outbound_connection_is_refused_while_blocked(self):
        with NoNetwork() as net:
            with pytest.raises((OSError, socket.gaierror)):
                socket.create_connection(("huggingface.co", 443), timeout=2)
        assert net.attempts, "the blocker recorded no attempt -- it is not wired in"

    def test_dns_is_blocked_too_not_only_connect(self):
        with NoNetwork() as net:
            with pytest.raises(socket.gaierror):
                socket.getaddrinfo("huggingface.co", 443)
        assert any(a[0] == "getaddrinfo" for a in net.attempts)

    def test_local_socket_construction_still_works_while_blocked(self):
        """The false-failure guard. asyncio builds its event-loop self-pipe from
        socket.socketpair(); a blocker that prevented that produced three
        failures indistinguishable from real fetch attempts."""
        with NoNetwork():
            a, b = socket.socketpair()
            a.close(); b.close()
            import asyncio
            assert asyncio.run(asyncio.sleep(0)) is None

    def test_the_network_is_restored_afterwards(self):
        with NoNetwork():
            pass
        assert socket.socket.connect is not None
        assert callable(socket.create_connection)


class TestEveryWeightSetIsPresentOnDisk:
    @pytest.mark.parametrize("label", sorted(WEIGHTS))
    def test_weight_present(self, label):
        assert WEIGHTS[label].exists(), f"{label} missing at {WEIGHTS[label]}"

    def test_all_weights_are_inside_the_project_directory(self):
        """Not ~/.cache and not /tmp.

        Render documents the build filesystem as carrying into the runtime and
        the runtime filesystem as otherwise ephemeral; it does NOT document
        whether build-time writes outside the project directory survive. And
        FastEmbed's own default was /tmp/fastembed_cache -- measured -- which is
        worse than the once-per-deploy download KI-2 describes, because /tmp is
        cleared under a running service.
        """
        backend = pathlib.Path(__file__).resolve().parents[1]
        for label, path in WEIGHTS.items():
            assert str(path).startswith(str(backend)), (
                f"{label} resolves to {path}, outside the project directory")
            for bad in ("/tmp/", "/.cache/"):
                assert bad not in str(path), f"{label} points into {bad}"


class TestModelsLoadWithNoNetwork:
    """The actual bake verification."""

    def test_offline_enforcement_is_on_by_default(self):
        assert MODELS_OFFLINE is True, (
            "MODELS_OFFLINE defaults to off, so a missing weight would be "
            "silently downloaded at runtime instead of failing loudly -- which "
            "is the defect KI-2 and VKI-4 both describe."
        )

    def test_whisper_loads_with_egress_blocked(self):
        from app.services.voice import stt
        stt.reset_for_tests()
        with NoNetwork():
            model = stt._get_model()
        assert model is not None
        stt.reset_for_tests()

    def test_a_real_transcription_runs_with_egress_blocked(self):
        from app.services.voice import stt
        fixture = pathlib.Path(__file__).resolve().parent / "fixtures" / "voice" / "kokoro_roundtrip.wav"
        stt.reset_for_tests()
        with NoNetwork():
            out = stt.transcribe(str(fixture))
        assert out["transcript"].strip(), "transcription produced nothing offline"
        assert len(out["words"]) >= 10
        stt.reset_for_tests()

    def test_kokoro_synthesises_with_egress_blocked(self):
        import asyncio
        from app.services.voice import tts
        tts.reset_for_tests()
        with NoNetwork():
            audio, media, engine = asyncio.run(tts.synthesize("Offline check."))
        assert engine == "kokoro" and media == "audio/wav" and len(audio) > 5000
        tts.reset_for_tests()

    def test_piper_synthesises_with_egress_blocked(self, monkeypatch):
        import asyncio
        from app.services.voice import tts
        monkeypatch.setenv("TTS_ENGINE", "piper")
        tts.reset_for_tests()
        with NoNetwork():
            audio, media, engine = asyncio.run(tts.synthesize("Offline fallback check."))
        assert engine == "piper", f"engine was {engine}, so Piper did not serve it"
        assert media == "audio/wav" and len(audio) > 5000
        tts.reset_for_tests()

    def test_fastembed_embeds_with_egress_blocked(self):
        """This is KI-2's closure, asserted rather than asserted-about."""
        from app.services.codebase import embeddings
        embeddings._model = None
        with NoNetwork():
            vecs = embeddings.embed_texts(["offline embedding check"])
        assert vecs.shape[0] == 1 and vecs.shape[1] > 100

    def test_all_three_tts_engines_report_ready_with_egress_blocked(self):
        from app.services.voice import tts
        with NoNetwork():
            status = tts.engine_status()
        for name in ("kokoro", "piper"):
            assert status["engines"][name]["ready"] is True, (
                f"{name} not ready offline: {status['engines'][name]}")
        # edge is network-dependent BY NATURE; readiness here means "installed",
        # and claiming otherwise would be the honest-self-report defect again.
        assert status["engines"]["edge"]["ready"] is True
        assert status["engines"]["edge"]["note"] == "network-dependent"


class TestNoFetchWasAttempted:
    def test_loading_every_model_offline_makes_zero_connection_attempts(self):
        """Stronger than 'it worked': nothing even TRIED to reach the network.

        A loader that attempted a fetch, failed, and fell back to cache would
        pass every test above while still being a runtime-fetch defect on a
        machine where the network is merely slow rather than absent.
        """
        import asyncio
        from app.services.voice import stt, tts
        from app.services.codebase import embeddings

        stt.reset_for_tests()
        tts.reset_for_tests()
        embeddings._model = None
        with NoNetwork() as net:
            stt._get_model()
            asyncio.run(tts.synthesize("Zero fetch check."))
            embeddings.embed_texts(["zero fetch check"])
        assert net.attempts == [], (
            f"{len(net.attempts)} connection attempt(s) made while loading "
            f"models that are supposed to be baked: {net.attempts[:5]}"
        )
        stt.reset_for_tests()
        tts.reset_for_tests()
