import { Link } from "react-router-dom";

/**
 * Six dashboard cards, ported from docs/athena-homepage-wireframe.html with its
 * exact placeholder values. No data wiring yet — see Phase 3.
 */

export function RoadmapCard() {
  return (
    <div className="card w2 rise">
      <h3>
        Roadmap <em>Systems design</em>
      </h3>
      <p className="big">
        38<small>% complete &middot; 13 of 34 nodes</small>
      </p>
      <div className="legs">
        <span className="stage done"><b>Foundations</b><u /></span>
        <span className="stage done"><b>Storage</b><u /></span>
        <span className="stage now"><b>Caching</b><u /></span>
        <span className="stage"><b>Queues</b><u /></span>
        <span className="stage"><b>Scale</b><u /></span>
      </div>
      <p className="note">
        You stalled on <b>Caching</b> 4 days ago &mdash; two nodes left before Queues unlocks.
      </p>
      <div className="foot">
        <span>Started 14 Jun</span>
        <span>~9 sessions to finish</span>
      </div>
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

export function TodayCard() {
  const forecast = [
    { day: "T", pct: 38, hot: true },
    { day: "W", pct: 13, hot: false },
    { day: "T", pct: 63, hot: false },
    { day: "F", pct: 25, hot: false },
    { day: "S", pct: 100, hot: false },
    { day: "S", pct: 50, hot: false },
    { day: "M", pct: 75, hot: false },
  ];
  return (
    <div className="card rise">
      <h3>Today</h3>
      <div className="ringwrap">
        <svg className="ring" width="68" height="68" viewBox="0 0 68 68" role="img" aria-label="Two of three daily missions complete">
          <circle className="bg" cx="34" cy="34" r="28" />
          <circle className="fg" cx="34" cy="34" r="28" strokeDasharray="117.3 175.9" />
          <text x="34" y="34" textAnchor="middle" dominantBaseline="central" fill="#E9F1EE" fontFamily="Instrument Sans, sans-serif" fontSize="17" fontWeight="600">
            2/3
          </text>
        </svg>
        <div className="tasklist">
          <span className="ok"><i />Clear the review queue</span>
          <span className="ok"><i />One speaking drill</span>
          <span><i />Advance the roadmap</span>
        </div>
      </div>
      <div className="forecast">
        <h4>Due next 7 days &middot; 29 cards</h4>
        <div className="bars">
          {forecast.map((f, i) => (
            <span key={i} className={f.hot ? "hot" : ""}>
              <u style={{ height: `${f.pct}%` }} />
              <em>{f.day}</em>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ConsistencyCard() {
  const padCells = 5;
  const days = [0, 2, 1, 0, 3, 1, 0, 0, 2, 4, 1, 0, 2, 3, 1, 0, 0, 1, 4, 2, 0, 3, 0, 1, 2, 0, 4, 1, 3, 0, 2];
  return (
    <div className="card rise">
      <h3>Consistency</h3>
      <p className="range">12 Jul &rarr; 12 Aug</p>
      <div className="heat">
        {Array.from({ length: padCells }).map((_, i) => (
          <i key={`pad-${i}`} className="pad" />
        ))}
        {days.map((v, i) => (
          <i key={i} className={v ? `l${v}` : ""} />
        ))}
      </div>
      <div className="hours">
        <b>4h 20m</b>
        <em>+38m vs last week</em>
      </div>
      <div className="foot">
        <span>1 day streak</span>
        <span>Best 11</span>
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
