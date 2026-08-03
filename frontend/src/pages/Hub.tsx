import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ConsistencyCard, FocusCard, GymCard, RecallCard, RoadmapCard, TodayCard } from "../components/DashboardCards";
import HeroMedia from "../components/HeroMedia";
import ToolsBento from "../components/ToolsBento";
import { useWakeWord } from "../lib/useWakeWord";
import { useAuth } from "../store/auth";

const WAVE_DELAYS = [0, 0.08, 0.16, 0.24, 0.32, 0.4, 0.48, 0.56, 0.64, 0.72, 0.8, 0.88];

export default function Hub() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [wakeReady, setWakeReady] = useState(false);
  const [wakeHint, setWakeHint] = useState("");

  useWakeWord(
    () => navigate("/chat"),
    (r) => setWakeReady(r)
  );

  useEffect(() => {
    if (localStorage.getItem("athena_wakeword") !== "1") return;
    const SR = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
    if (!SR) {
      setWakeHint("Wake word needs Chrome or Edge");
      return;
    }
    const t = setTimeout(() => {
      setWakeReady((ready) => {
        if (!ready) setWakeHint("Allow the microphone, then reload to enable “Hey Athena”");
        return ready;
      });
    }, 3500);
    return () => clearTimeout(t);
  }, []);

  // Chrome's "Progress" / "Tools grid" nav links land here as /#progress, /#grid —
  // React Router doesn't auto-scroll to a hash the way a full page load would.
  useEffect(() => {
    if (!location.hash) return;
    const el = document.getElementById(location.hash.slice(1));
    el?.scrollIntoView({ behavior: "smooth" });
  }, [location.hash]);

  // Fade-up reveal for every .rise element, once, the first time it scrolls into view.
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const els = Array.from(document.querySelectorAll<HTMLElement>(".rise"));
    if (reduce) {
      els.forEach((el) => el.classList.add("in"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.1 }
    );
    els.forEach((el, i) => {
      el.style.transitionDelay = `${Math.min(i, 9) * 55}ms`;
      io.observe(el);
    });
    return () => io.disconnect();
  }, []);

  return (
    <>
      <header className="hero" id="top">
        <HeroMedia />
        <div className="shell hero-inner">
          <div>
            <p className="eyebrow rise">Local-first &middot; Voice-native</p>
            <h1 className="rise">
              Learn out <em>loud.</em>
            </h1>
            <p className="sub rise">
              A tutor that runs on your machine, listens while you think aloud, plans the path through a subject,
              drills you on it, and quietly remembers everything you're about to forget.
            </p>
            <div className="hero-actions rise">
              <Link className="cta" to="/chat">
                Start a session
              </Link>
              <a className="cta-ghost" href="#grid">
                See the tools
              </a>
            </div>
            {wakeReady ? (
              <p className="wake-status rise" style={{ color: "var(--jade)" }}>
                &#9679; LISTENING FOR &ldquo;HEY ATHENA&rdquo;
              </p>
            ) : wakeHint ? (
              <p className="wake-status rise" style={{ color: "var(--danger)" }}>
                {wakeHint}
              </p>
            ) : null}
            <dl className="hero-stats rise">
              <div>
                <dt>Runs on</dt>
                <dd>Your machine</dd>
              </div>
              <div>
                <dt>Voice</dt>
                <dd>Whisper &amp; Edge&#8209;TTS</dd>
              </div>
              <div>
                <dt>Recall</dt>
                <dd>Spaced repetition</dd>
              </div>
            </dl>
          </div>
          <Link className="console rise" to="/chat" title="Talk to Athena">
            <div className="console-bar">
              <i className="dot" /> Live session &middot; Communication Gym
            </div>
            <div className="console-body">
              <div className="turn you">
                <span className="who">You</span>
                <p>Explain backpropagation like I've never seen calculus.</p>
              </div>
              <div className="turn her">
                <span className="who">Athena</span>
                <p>
                  Picture a kitchen that got the soup wrong. Backprop is walking the recipe backwards, asking each
                  step how much of the salt was its fault&hellip;
                </p>
              </div>
              <div className="turn">
                <span className="who">Audio</span>
                <div className="wave">
                  {WAVE_DELAYS.map((d, i) => (
                    <span key={i} style={{ animationDelay: `${d}s` }} />
                  ))}
                </div>
              </div>
            </div>
            <div className="console-foot">
              <span>3 cards queued from this session</span>
              <span>Groq &middot; Llama 3.3 70B</span>
            </div>
          </Link>
        </div>
        <div className="scroll-cue">Scroll</div>
      </header>

      <main className="shell">
        <section className="band" id="progress">
          <div className="sec-head rise">
            <div>
              <span className="sec-tag">Signed in as {user?.name?.split(" ")[0] ?? "you"}</span>
              <h2>Where you are</h2>
              <p>Six readings, updated after every session. Each one points at a next action.</p>
            </div>
            <Link className="cta-ghost" to="/roadmap">
              Resume Roadmap &rarr;
            </Link>
          </div>
          <div className="dash">
            <RoadmapCard />
            <GymCard />
            <TodayCard />
            <ConsistencyCard />
            <RecallCard />
            <FocusCard />
          </div>
        </section>

        <ToolsBento />

        <footer className="site-footer">
          <span>ATHENA OS &middot; Learning platform</span>
          <span>Runs local &middot; No data leaves the machine</span>
        </footer>
      </main>
    </>
  );
}
