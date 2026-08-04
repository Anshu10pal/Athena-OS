import { Link } from "react-router-dom";

/**
 * Dashboard cards, ported from docs/athena-homepage-wireframe.html with its
 * exact placeholder values. RoadmapCard, TodayCard, and ConsistencyCard are
 * wired to real data; GymCard, RecallCard, and FocusCard still show the
 * original placeholder values — no data wiring yet for those.
 */

export function RoadmapCard({
  title,
  percent,
  topicCount,
  completedCount,
}: {
  title: string | null;
  percent: number;
  topicCount: number;
  completedCount: number;
}) {
  return (
    <div className="card w2 rise">
      <h3>Roadmap {title && <em>{title}</em>}</h3>
      {title ? (
        <>
          <p className="big">
            {percent}
            <small>
              % complete &middot; {completedCount} of {topicCount} topics
            </small>
          </p>
          <Link className="focus-cta" to="/roadmap">
            Resume this roadmap &rarr;
          </Link>
        </>
      ) : (
        <>
          <p className="note">You haven't searched a roadmap yet.</p>
          <Link className="focus-cta" to="/roadmap">
            Start a roadmap &rarr;
          </Link>
        </>
      )}
    </div>
  );
}

export function GymCard() {
  return (
    <div className="card rise">
      <h3>Communication Gym</h3>
      <svg className="radar" viewBox="0 0 200 172" role="img" aria-label="Four-axis chart: writing 74, reading 61, listening 83, speaking 47">
        <g fill="none" stroke="rgba(255,255,255,.085)" strokeWidth="1">
          <polygon points="100,69 113,82 100,95 87,82" />
          <polygon points="100,56 126,82 100,108 74,82" />
          <polygon points="100,43 139,82 100,121 61,82" />
          <polygon points="100,30 152,82 100,134 48,82" />
        </g>
        <g stroke="rgba(255,255,255,.065)" strokeWidth="1">
          <line x1="100" y1="82" x2="100" y2="30" />
          <line x1="100" y1="82" x2="152" y2="82" />
          <line x1="100" y1="82" x2="100" y2="134" />
          <line x1="100" y1="82" x2="48" y2="82" />
        </g>
        <polygon points="100,43.5 131.7,82 100,125.2 75.6,82" fill="rgba(61,220,151,.20)" stroke="#3DDC97" strokeWidth="1.5" strokeLinejoin="round" />
        <g fill="#3DDC97">
          <circle cx="100" cy="43.5" r="2.6" />
          <circle cx="131.7" cy="82" r="2.6" />
          <circle cx="100" cy="125.2" r="2.6" />
        </g>
        <circle cx="75.6" cy="82" r="3.2" fill="#E0B450" />
        <g fill="rgba(233,241,238,.40)" fontFamily="JetBrains Mono, monospace" fontSize="8.5" letterSpacing="1.2">
          <text x="100" y="16" textAnchor="middle">WRITING</text>
          <text x="196" y="85" textAnchor="end">READING</text>
          <text x="100" y="152" textAnchor="middle">LISTENING</text>
          <text x="4" y="85">SPEAKING</text>
        </g>
      </svg>
      <div className="quad-key">
        <span>Writing <b>74</b></span>
        <span>Reading <b>61</b></span>
        <span>Listening <b>83</b></span>
        <span className="low">Speaking <b>47</b></span>
      </div>
    </div>
  );
}

interface MissionT {
  id: number;
  objective: string;
  status: string;
}

interface ForecastDay {
  date: string;
  count: number;
}

export function TodayCard({
  completed,
  total,
  missions,
  forecast,
}: {
  completed: number;
  total: number;
  missions: MissionT[];
  forecast: ForecastDay[];
}) {
  const circumference = 2 * Math.PI * 28;
  const filled = total > 0 ? (circumference * completed) / total : 0;
  const totalDue = forecast.reduce((sum, f) => sum + f.count, 0);
  const maxCount = Math.max(1, ...forecast.map((f) => f.count));

  return (
    <div className="card rise">
      <h3>Today</h3>
      <div className="ringwrap">
        <svg
          className="ring"
          width="68"
          height="68"
          viewBox="0 0 68 68"
          role="img"
          aria-label={`${completed} of ${total} daily missions complete`}
        >
          <circle className="bg" cx="34" cy="34" r="28" />
          <circle className="fg" cx="34" cy="34" r="28" strokeDasharray={`${filled.toFixed(1)} ${circumference.toFixed(1)}`} />
          <text x="34" y="34" textAnchor="middle" dominantBaseline="central" fill="#E9F1EE" fontFamily="Instrument Sans, sans-serif" fontSize="17" fontWeight="600">
            {completed}/{total}
          </text>
        </svg>
        <div className="tasklist">
          {missions.length > 0 ? (
            missions.map((m) => (
              <span key={m.id} className={m.status === "completed" ? "ok" : ""}>
                <i />
                {m.objective}
              </span>
            ))
          ) : (
            <span>No missions generated yet today</span>
          )}
        </div>
      </div>
      <div className="forecast">
        <h4>
          Due next 7 days &middot; {totalDue} card{totalDue === 1 ? "" : "s"}
        </h4>
        <div className="bars">
          {forecast.map((f, i) => (
            <span key={f.date} className={i === 0 && f.count > 0 ? "hot" : ""}>
              <u style={{ height: `${Math.round((f.count / maxCount) * 100)}%` }} />
              <em>{new Date(f.date + "T00:00:00").toLocaleDateString(undefined, { weekday: "short" }).charAt(0)}</em>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ConsistencyCard({
  cells,
  rangeStart,
  rangeEnd,
  streak,
  activeDays,
  activeThisWeek,
  activeLastWeek,
}: {
  cells: { date: string; level: number }[];
  rangeStart: string;
  rangeEnd: string;
  streak: number;
  activeDays: number;
  activeThisWeek: number;
  activeLastWeek: number;
}) {
  const fmt = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" });
  const startWeekday = cells.length ? new Date(rangeStart + "T00:00:00").getDay() : 0;
  const delta = activeThisWeek - activeLastWeek;
  const deltaLabel = delta === 0 ? "same as last week" : `${delta > 0 ? "+" : ""}${delta} vs last week`;

  return (
    <div className="card rise">
      <h3>Consistency</h3>
      <p className="range">
        {fmt(rangeStart)} &rarr; {fmt(rangeEnd)}
      </p>
      <div className="heat">
        {Array.from({ length: startWeekday }).map((_, i) => (
          <i key={`pad-${i}`} className="pad" />
        ))}
        {cells.map((c) => (
          <i key={c.date} className={c.level ? `l${c.level}` : ""} title={c.date} />
        ))}
      </div>
      <div className="hours">
        <b>{activeDays} active days</b>
        <em>{deltaLabel}</em>
      </div>
      <div className="foot">
        <span>{streak} day streak</span>
        <span>{activeThisWeek} active this week</span>
      </div>
    </div>
  );
}

export function RecallCard() {
  return (
    <div className="card rise">
      <h3>Recall accuracy</h3>
      <p className="big">
        71<small>% &middot; last 30 cards</small>
      </p>
      <svg className="spark" viewBox="0 0 200 46" preserveAspectRatio="none" role="img" aria-label="Recall accuracy trending upward">
        <polyline points="0,36 28,32 56,38 84,27 112,23 140,28 168,17 200,13 200,46 0,46" fill="rgba(61,220,151,.10)" stroke="none" />
        <polyline points="0,36 28,32 56,38 84,27 112,23 140,28 168,17 200,13" fill="none" stroke="#3DDC97" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <p className="note">Up 9 points this fortnight.</p>
      <div className="foot">
        <span>Target 85%</span>
        <span>Trending up</span>
      </div>
    </div>
  );
}

export function FocusCard() {
  return (
    <div className="card w2 rise">
      <h3>Focus next</h3>
      <p className="focus-name">Speaking</p>
      <p className="note">
        Your lagging quadrant by 27 points, and the one Interview Arena leans on hardest. Three drills would close most
        of the gap. These are the topics you fumbled most recently:
      </p>
      <div className="topics">
        <Link to="/communication">TCP handshakes</Link>
        <Link to="/communication">Cache eviction</Link>
        <Link to="/communication">CAP theorem</Link>
      </div>
      <Link className="focus-cta" to="/communication">
        Open a speaking drill &rarr;
      </Link>
    </div>
  );
}
