import { useCallback, useEffect, useMemo, useState } from "react";

const api = async (path, options) => {
  const res = await fetch(`/api${path}`, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  }
  return res.json();
};
const post = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

const STATUS = {
  supported: { label: "Verified", text: "text-ok", bg: "bg-ok/10", ring: "ring-ok/30", bar: "bg-ok" },
  contradicted: { label: "Contradiction", text: "text-bad", bg: "bg-bad/10", ring: "ring-bad/30", bar: "bg-bad" },
  partial: { label: "Partly supported", text: "text-warn", bg: "bg-warn/10", ring: "ring-warn/30", bar: "bg-warn" },
  unverifiable: { label: "Unverifiable", text: "text-unk", bg: "bg-unk/10", ring: "ring-unk/30", bar: "bg-unk" },
};
const ORDER = ["supported", "contradicted", "partial", "unverifiable"];
const TABS = [
  ["verify", "Verify"],
  ["disagreements", "Disagreements"],
  ["library", "Spec library"],
  ["evaluation", "Evaluation"],
];
const pct = (x) => (x == null ? "n/a" : `${(x * 100).toFixed(1)}%`);

function Badge({ status, small }) {
  const s = STATUS[status];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full ring-1 ${s.ring} ${s.bg} ${s.text} ${small ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs"} font-semibold whitespace-nowrap`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.bar}`} />
      {s.label}
    </span>
  );
}

function Panel({ className = "", children }) {
  return <section className={`rounded-2xl border border-ink-700/70 bg-ink-900/80 ${className}`}>{children}</section>;
}

function Label({ children }) {
  return <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-400">{children}</div>;
}

function Gauge({ value }) {
  const r = 52;
  const arc = Math.PI * r;
  const v = value ?? 0;
  const color = value == null ? "var(--color-unk)" : v >= 0.85 ? "var(--color-ok)" : v >= 0.6 ? "var(--color-warn)" : "var(--color-bad)";
  return (
    <div className="relative w-40 shrink-0">
      <svg viewBox="0 0 128 74" className="w-full">
        <path d="M12 66 A52 52 0 0 1 116 66" fill="none" stroke="var(--color-ink-700)" strokeWidth="9" strokeLinecap="round" />
        <path d="M12 66 A52 52 0 0 1 116 66" fill="none" stroke={color} strokeWidth="9" strokeLinecap="round"
          strokeDasharray={`${arc * v} ${arc}`} style={{ transition: "stroke-dasharray .6s ease" }} />
      </svg>
      <div className="absolute inset-x-0 bottom-0 text-center">
        <div className="font-display text-2xl font-bold leading-none">{value == null ? "n/a" : `${Math.round(v * 100)}%`}</div>
        <div className="mt-1 whitespace-nowrap text-[10px] uppercase tracking-[0.1em] text-ink-400">factual accuracy</div>
      </div>
    </div>
  );
}

function Quote({ quote }) {
  return <p className="border-l-2 border-ink-600 pl-3 text-sm italic leading-relaxed text-ink-300">“{quote}”</p>;
}

function EvidenceRow({ e }) {
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-950/60 p-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-400">
        <span className="font-semibold text-ink-300">{e.doc_title}</span>
        <span>·</span>
        <span>{e.url ? "web page" : `page ${e.page}`}</span>
        <span>·</span>
        <span>{e.heading}</span>
        {e.trim && (<><span>·</span><span>{e.trim}</span></>)}
        {e.standard && <span className="rounded bg-ink-700 px-1.5 py-0.5 font-mono text-[10px] text-ink-100">{e.standard}</span>}
        <a className="ml-auto font-semibold text-amber-glow hover:underline" target="_blank" rel="noreferrer"
          href={e.url ?? `/api/specs/${encodeURIComponent(e.file)}#page=${e.page}`}>
          {e.url ? "Open source page ↗" : "Open PDF page ↗"}
        </a>
      </div>
      <div className="mt-2 font-mono text-[13px] text-ink-100">{e.text}</div>
    </div>
  );
}

function VerdictCard({ v }) {
  const [open, setOpen] = useState(v.status !== "supported");
  const s = STATUS[v.status];
  const c = v.claim;
  return (
    <article className="relative overflow-hidden rounded-2xl border border-ink-700/70 bg-ink-900/80">
      <div className={`absolute inset-y-0 left-0 w-1 ${s.bar}`} />
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 py-3.5 pl-5 pr-4 text-left hover:bg-ink-850">
        <div className="min-w-0 flex-1">
          <div className="font-display text-[15px] font-semibold">{c.text}</div>
          <div className="mt-0.5 text-xs text-ink-400">
            {[c.vehicle.year, c.vehicle.make, c.vehicle.model, c.vehicle.trim || "any trim", c.vehicle.market].filter(Boolean).join(" · ")}
          </div>
        </div>
        {v.official && v.status !== "supported" && (
          <div className="hidden text-right sm:block">
            <div className="text-[10px] uppercase tracking-[0.14em] text-ink-400">official</div>
            <div className="max-w-64 truncate font-mono text-xs text-ink-100">{v.official}</div>
          </div>
        )}
        <Badge status={v.status} />
        <span className={`text-ink-400 transition-transform ${open ? "rotate-180" : ""}`}>▾</span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-ink-700/70 py-4 pl-5 pr-4">
          <Quote quote={c.quote} />
          <p className="text-sm leading-relaxed text-ink-100">{v.reason}</p>
          {v.config_note && <p className="text-xs text-ink-400">{v.config_note}</p>}
          {v.configs.length > 1 && (
            <div className="flex flex-wrap gap-2">
              {v.configs.map((r) => (
                <div key={r.config} className="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-950/50 px-2.5 py-1.5 text-xs">
                  <span className="text-ink-300">{r.config}</span>
                  {r.official && <span className="font-mono text-ink-100">{r.official}</span>}
                  <Badge status={r.status} small />
                </div>
              ))}
            </div>
          )}
          {v.evidence.length > 0 && (
            <div className="space-y-2">
              <Label>Evidence from official documentation</Label>
              {v.evidence.map((e, i) => <EvidenceRow key={i} e={e} />)}
            </div>
          )}
          <div className="text-[11px] text-ink-400">
            Verified by: {{ numeric: "unit-aware numerical comparison", categorical: "category match", feature: "equipment availability", nli: "NLI model", none: "no applicable check" }[v.method]}
            {" · "}claim extracted by {c.extractor}
          </div>
        </div>
      )}
    </article>
  );
}

function Results({ a }) {
  const [filter, setFilter] = useState("all");
  const shown = useMemo(
    () => [...a.verdicts].filter((v) => filter === "all" || v.status === filter)
      .sort((x, y) => ["contradicted", "partial", "unverifiable", "supported"].indexOf(x.status) - ["contradicted", "partial", "unverifiable", "supported"].indexOf(y.status)),
    [a, filter]
  );
  const v = a.vehicle;
  return (
    <div className="space-y-5">
      <Panel className="p-5">
        <div className="flex flex-wrap items-start gap-5">
          <div className="min-w-0 flex-1">
            <Label>{a.source.type} review{a.source.author ? ` · ${a.source.author}` : ""}</Label>
            <h2 className="font-display text-xl font-bold leading-snug">{a.source.title}</h2>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              {[["Vehicle", [v.year, v.make, v.model].filter(Boolean).join(" ") || "not identified"], ["Trim", v.trim || "not stated"], ["Market", v.market || "not stated"]].map(([k, val]) => (
                <span key={k} className="rounded-lg border border-ink-700 bg-ink-950/50 px-2.5 py-1.5">
                  <span className="text-ink-400">{k} </span><span className="font-semibold">{val}</span>
                </span>
              ))}
            </div>
            <p className="mt-3 text-sm leading-relaxed text-ink-300">{a.summary}</p>
          </div>
          <Gauge value={a.accuracy} />
        </div>
        <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-5">
          {[...ORDER, "subjective"].map((k) => (
            <button key={k} type="button" disabled={k === "subjective"} onClick={() => setFilter(filter === k ? "all" : k)}
              className={`rounded-xl border px-3 py-2.5 text-left transition ${filter === k ? "border-amber-glow bg-ink-800" : "border-ink-700 bg-ink-950/50"} ${k === "subjective" ? "" : "hover:border-ink-600"}`}>
              <div className={`font-display text-2xl font-bold ${STATUS[k]?.text ?? "text-ink-100"}`}>{a.counts[k]}</div>
              <div className="text-[11px] text-ink-400">{STATUS[k]?.label ?? "Opinions set aside"}</div>
            </button>
          ))}
        </div>
        <div className="mt-3 text-[11px] text-ink-400">
          {a.latency_ms} ms · extractor: {a.extractor} · retrieval: {a.retrieval}
        </div>
      </Panel>

      <div className="space-y-2.5">
        {shown.map((x) => <VerdictCard key={x.claim.id} v={x} />)}
        {!shown.length && <Panel className="p-6 text-sm text-ink-400">No claims in this category.</Panel>}
      </div>

      {a.subjective.length > 0 && filter === "all" && (
        <Panel className="p-5">
          <Label>Subjective statements · not fact-checked</Label>
          <p className="mb-3 text-xs text-ink-400">Opinions and impressions are separated from measurable claims and are never given a verdict.</p>
          <ul className="space-y-2">
            {a.subjective.map((c) => <li key={c.id}><Quote quote={c.quote} /></li>)}
          </ul>
        </Panel>
      )}
    </div>
  );
}

function VerifyTab({ library, llm, onSaved, history, current, setCurrent }) {
  const [useLlm, setUseLlm] = useState(false);
  const [samples, setSamples] = useState([]);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState("text");
  const [override, setOverride] = useState({ doc: "", trim: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { api("/samples").then(setSamples).catch(() => {}); }, []);
  const doc = library.find((d) => d.id === override.doc);

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const vehicle = doc ? { make: doc.make, model: doc.model, year: doc.year, market: doc.market, trim: override.trim || null } : null;
      const body = { ...(mode === "url" ? { url } : { text, title: title || null, author: author || null }), vehicle, use_llm: useLlm };
      const result = await post("/analyze", body);
      setCurrent(result);
      onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const input = "w-full rounded-xl border border-ink-700 bg-ink-950/70 px-3 py-2 text-sm placeholder:text-ink-600";

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
      <div className="space-y-5">
        <Panel className="p-5">
          <div className="mb-4 flex gap-1 rounded-xl bg-ink-950/70 p-1 text-sm">
            {[["text", "Paste a review"], ["url", "From a URL"]].map(([k, l]) => (
              <button key={k} type="button" onClick={() => setMode(k)}
                className={`flex-1 rounded-lg px-3 py-1.5 font-medium ${mode === k ? "bg-ink-700 text-ink-100" : "text-ink-400 hover:text-ink-100"}`}>{l}</button>
            ))}
          </div>
          {mode === "text" ? (
            <>
              <Label>Sample reviews</Label>
              <div className="mb-4 flex flex-wrap gap-1.5">
                {samples.map((s) => (
                  <button key={s.id} type="button" title={s.title}
                    onClick={() => { setText(s.text); setTitle(s.title); setAuthor(s.author || ""); }}
                    className={`rounded-full border px-2.5 py-1 text-xs ${title === s.title ? "border-amber-glow text-amber-glow" : "border-ink-700 text-ink-300 hover:border-ink-600"}`}>
                    {s.author}
                  </button>
                ))}
              </div>
              <Label>Review text</Label>
              <textarea value={text} onChange={(e) => setText(e.target.value)} rows={11}
                placeholder="Paste a written review, a video transcript or a forum post…" className={`${input} resize-y leading-relaxed`} />
              <div className="mt-2 grid grid-cols-2 gap-2">
                <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title (optional)" className={input} />
                <input value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="Reviewer (optional)" className={input} />
              </div>
            </>
          ) : (
            <>
              <Label>Review URL</Label>
              <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.youtube.com/watch?v=…" className={input} />
              <p className="mt-2 text-xs leading-relaxed text-ink-400">YouTube videos (transcript), Reddit threads and article pages. The page is fetched by the backend.</p>
            </>
          )}
          <div className="mt-4">
            <Label>Vehicle configuration</Label>
            <div className="grid grid-cols-2 gap-2">
              <select value={override.doc} onChange={(e) => setOverride({ doc: e.target.value, trim: "" })} className={input}>
                <option value="">Auto-detect from text</option>
                {library.map((d) => <option key={d.id} value={d.id}>{d.year} {d.make} {d.model} · {d.market}</option>)}
              </select>
              <select value={override.trim} disabled={!doc} onChange={(e) => setOverride({ ...override, trim: e.target.value })} className={`${input} disabled:opacity-40`}>
                <option value="">Any trim</option>
                {(doc?.trims.length ? doc.trims : doc?.variants ?? []).map((t) => <option key={t}>{t}</option>)}
              </select>
            </div>
          </div>
          {llm && (
            <label className="mt-4 flex cursor-pointer items-start gap-2.5 text-sm">
              <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} className="mt-0.5 h-4 w-4 accent-amber-glow" />
              <span>
                Extract claims with {llm}
                <span className="block text-xs text-ink-400">Slower and uses API quota. Verdicts are still decided by the independent verification layer.</span>
              </span>
            </label>
          )}
          {error && <div role="alert" className="mt-3 rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{error}</div>}
          <button type="button" onClick={run} disabled={busy || (mode === "text" ? !text.trim() : !url.trim())}
            className="mt-4 w-full rounded-xl bg-amber-glow px-4 py-2.5 font-display font-semibold text-ink-950 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40">
            {busy ? "Verifying…" : "Verify claims"}
          </button>
        </Panel>

        {history.length > 0 && (
          <Panel className="p-5">
            <Label>Analysed reviews</Label>
            <ul className="space-y-1">
              {history.map((h) => (
                <li key={h.id}>
                  <button type="button" onClick={() => api(`/analyses/${h.id}`).then(setCurrent)}
                    className={`w-full rounded-lg px-2.5 py-2 text-left hover:bg-ink-800 ${current?.id === h.id ? "bg-ink-800" : ""}`}>
                    <div className="truncate text-sm font-medium">{h.title}</div>
                    <div className="mt-1 flex items-center gap-2 text-[11px] text-ink-400">
                      <span className="truncate">{h.vehicle}</span>
                      <span className="ml-auto flex shrink-0 gap-2 font-mono">
                        <span className="text-ok">{h.counts.supported}</span>
                        <span className="text-bad">{h.counts.contradicted}</span>
                        <span className="text-warn">{h.counts.partial}</span>
                        <span className="text-unk">{h.counts.unverifiable}</span>
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </div>

      <div className="min-w-0">
        {current ? <Results key={current.id} a={current} /> : (
          <Panel className="flex min-h-96 flex-col items-center justify-center p-10 text-center">
            <div className="font-display text-2xl font-bold">Check what a review claims against what the manufacturer published.</div>
            <p className="mt-3 max-w-lg text-sm leading-relaxed text-ink-400">
              Pick a sample review or paste your own. Every measurable claim is matched to the exact model year, market and trim,
              then compared with the official specification sheet and cited down to the PDF page.
            </p>
          </Panel>
        )}
      </div>
    </div>
  );
}

function DisagreementsTab({ items }) {
  if (!items.length)
    return <Panel className="p-8 text-sm text-ink-400">No disagreements yet. Analyse at least two reviews of the same vehicle and any factual points they dispute will appear here.</Panel>;
  return (
    <div className="space-y-4">
      {items.map((d, i) => (
        <Panel key={i} className="p-5">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h3 className="font-display text-lg font-bold">{d.attribute}</h3>
            <span className="text-sm text-ink-400">{d.vehicle}</span>
            {d.official && <span className="ml-auto font-mono text-xs text-ink-300">official: {d.official}</span>}
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {d.positions.map((p, j) => (
              <div key={j} className="rounded-xl border border-ink-700 bg-ink-950/50 p-3.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-xs font-semibold text-ink-300">{p.author || p.source}</div>
                    <div className="mt-1 font-display font-semibold">{p.claim}</div>
                  </div>
                  <Badge status={p.status} small />
                </div>
                <div className="mt-2.5"><Quote quote={p.quote} /></div>
              </div>
            ))}
          </div>
          <p className="mt-4 text-sm text-ink-100">{d.resolution}</p>
        </Panel>
      ))}
    </div>
  );
}

function LibraryTab({ library, reload }) {
  const [open, setOpen] = useState(null);
  const [facts, setFacts] = useState([]);
  const [msg, setMsg] = useState("");
  const show = async (id) => {
    if (open === id) return setOpen(null);
    setFacts(await api(`/library/${id}/facts`));
    setOpen(id);
  };
  const upload = async (e) => {
    e.preventDefault();
    setMsg("Parsing…");
    try {
      const r = await api("/library/upload", { method: "POST", body: new FormData(e.target) });
      setMsg(`Indexed ${r.facts} specification rows across ${r.trims.length || 1} trim(s).`);
      e.target.reset();
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  };
  const input = "rounded-xl border border-ink-700 bg-ink-950/70 px-3 py-2 text-sm placeholder:text-ink-600";
  return (
    <div className="space-y-4">
      {library.map((d) => (
        <Panel key={d.id} className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 p-5">
            <div className="min-w-0 flex-1">
              <h3 className="font-display text-lg font-bold">{d.year} {d.make} {d.model}</h3>
              <div className="mt-1 text-xs text-ink-400">{d.market} market · {d.pages} pages · {d.facts} specification rows · {d.chunks} retrieval chunks</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(d.trims.length ? d.trims : d.variants).map((t) => <span key={t} className="rounded-full border border-ink-700 px-2.5 py-0.5 text-xs text-ink-300">{t}</span>)}
              </div>
            </div>
            <a href={d.file.endsWith(".html") ? d.source_url : `/api/specs/${encodeURIComponent(d.file)}`} target="_blank" rel="noreferrer" className="text-sm font-semibold text-amber-glow hover:underline">{d.file.endsWith(".html") ? "Open source page ↗" : "Open PDF ↗"}</a>
            <button type="button" onClick={() => show(d.id)} className="rounded-lg border border-ink-700 px-3 py-1.5 text-sm hover:border-ink-600">
              {open === d.id ? "Hide rows" : "Show parsed rows"}
            </button>
          </div>
          {open === d.id && (
            <div className="max-h-96 overflow-auto border-t border-ink-700/70">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-ink-850 text-ink-400">
                  <tr>{["Trim", "Page", "Section", "Row", "Parsed as"].map((h) => <th key={h} className="px-4 py-2 font-semibold">{h}</th>)}</tr>
                </thead>
                <tbody>
                  {facts.map((f, i) => (
                    <tr key={i} className="border-t border-ink-800">
                      <td className="px-4 py-1.5 whitespace-nowrap text-ink-300">{f.trim}</td>
                      <td className="px-4 py-1.5 text-ink-400">{f.page}</td>
                      <td className="px-4 py-1.5 whitespace-nowrap text-ink-400">{f.heading}</td>
                      <td className="px-4 py-1.5 font-mono text-ink-100">{f.line}</td>
                      <td className="px-4 py-1.5 whitespace-nowrap text-ink-400">{f.attribute}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      ))}
      <Panel className="p-5">
        <Label>Add an official specification PDF</Label>
        <form onSubmit={upload} className="mt-2 grid gap-2 sm:grid-cols-[1.4fr_1fr_1fr_.7fr_.8fr_auto]">
          <input type="file" name="file" accept="application/pdf" required className={`${input} file:mr-3 file:rounded-md file:border-0 file:bg-ink-700 file:px-2 file:py-1 file:text-ink-100`} />
          <input name="make" placeholder="Make" required className={input} />
          <input name="model" placeholder="Model" required className={input} />
          <input name="year" type="number" placeholder="Year" className={input} />
          <input name="market" placeholder="Market" className={input} />
          <button className="rounded-xl bg-ink-700 px-4 py-2 text-sm font-semibold hover:bg-ink-600">Index</button>
        </form>
        <p className="mt-2 text-xs leading-relaxed text-ink-400">
          The parser reads “label: value” rows under section headings, and a heading such as “Trim: XLE” starts a new trim. {msg && <span className="text-ink-100">{msg}</span>}
        </p>
      </Panel>
    </div>
  );
}

function Metric({ label, value, hint }) {
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-950/50 p-4">
      <div className="font-display text-2xl font-bold">{value}</div>
      <div className="mt-1 text-xs font-semibold text-ink-300">{label}</div>
      {hint && <div className="mt-1 text-[11px] leading-snug text-ink-400">{hint}</div>}
    </div>
  );
}

function EvalBlock({ title, r }) {
  const ce = r.claim_extraction, cd = r.contradiction_detection;
  return (
    <Panel className="p-5">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h3 className="font-display text-lg font-bold">{title}</h3>
        <span className="text-xs text-ink-400">extractor: {r.extractor} · retrieval: {r.retrieval} · {r.gold_claims} gold claims in {r.reviews} reviews</span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <Metric label="Claim extraction F1" value={pct(ce.f1)} hint={`precision ${pct(ce.precision)} · recall ${pct(ce.recall)}`} />
        <Metric label="Verification accuracy" value={pct(r.verification_accuracy_end_to_end)} hint={`end to end · ${pct(r.verification_accuracy_on_extracted)} on extracted claims`} />
        <Metric label="Contradiction F1" value={pct(cd.f1)} hint={`precision ${pct(cd.precision)} · recall ${pct(cd.recall)}`} />
        <Metric label="Numeric matching" value={pct(r.numeric_matching_accuracy)} hint="unit-aware comparison" />
        <Metric label="Retrieval Recall@1" value={pct(r.retrieval_recall_at_k["@1"])} hint={`@2 ${pct(r.retrieval_recall_at_k["@2"])} · @3 ${pct(r.retrieval_recall_at_k["@3"])}`} />
        <Metric label="Citation correctness" value={pct(r.citation_correctness)} hint={`${pct(r.citation_verbatim_in_pdf)} verbatim on the cited page`} />
        <Metric label="Spurious claims" value={pct(r.hallucination_rate.spurious_claims)} hint={`fabricated citations ${pct(r.hallucination_rate.fabricated_citations)}`} />
        <Metric label="Latency per review" value={`${r.latency_ms.mean} ms`} hint={r.cost_per_review_usd === 0 ? "no API cost (offline extractor)" : "LLM cost not measured"} />
      </div>
      {r.errors.length > 0 && (
        <div className="mt-4">
          <Label>Errors ({r.errors.length})</Label>
          <ul className="space-y-1 text-xs text-ink-300">
            {r.errors.map((e, i) => (
              <li key={i} className="font-mono">
                <span className="text-warn">{e.type}</span> · {e.review} · {e.gold ?? e.claim}{e.sentence ? ` · “${e.sentence}”` : ""}{e.predicted ? ` · predicted ${e.predicted}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

function EvaluationTab() {
  const [data, setData] = useState(null);
  useEffect(() => { api("/eval").then(setData).catch(() => setData({})); }, []);
  if (!data) return null;
  if (!data.pipeline)
    return <Panel className="p-8 text-sm text-ink-400">No evaluation results yet. Run <span className="font-mono text-ink-100">python eval/run_eval.py --ablation</span> from the project root.</Panel>;
  return (
    <div className="space-y-4">
      <Panel className="border-warn/30 p-4 text-sm leading-relaxed text-ink-300">
        <span className="font-semibold text-warn">Read these numbers with care.</span> The benchmark is small, covers fictional vehicles whose PDFs share one layout,
        and was written by the same author as the extraction rules. It shows the pipeline works end to end; it does not predict accuracy on real brochures
        and real reviews. Generated {data.generated_at}.
      </Panel>
      <EvalBlock title="Full pipeline" r={data.pipeline} />
      {data.ablation_bm25_only && <EvalBlock title="Ablation: BM25-only retrieval" r={data.ablation_bm25_only} />}
      {data.pipeline_llm_extractor && <EvalBlock title="Pipeline with LLM claim extraction" r={data.pipeline_llm_extractor} />}
      {data.baseline_llm_judge ? (
        <Panel className="p-5">
          <h3 className="font-display text-lg font-bold">Baseline: retrieve, then let the LLM judge ({data.baseline_llm_judge.model})</h3>
          <p className="mt-1 text-xs leading-relaxed text-ink-400">
            Same retrieved evidence, but the model alone decides each verdict. It is handed the {data.baseline_llm_judge.claims} gold claims,
            so it is not penalised for extraction misses the way the pipeline is.
          </p>
          <div className="mt-4 grid grid-cols-2 gap-2.5 md:grid-cols-4">
            <Metric label="Verification accuracy" value={pct(data.baseline_llm_judge.verification_accuracy)} hint={`full pipeline: ${pct(data.pipeline.verification_accuracy_end_to_end)} end to end`} />
            <Metric label="Contradiction precision" value={pct(data.baseline_llm_judge.contradiction_detection.precision)} hint={`full pipeline: ${pct(data.pipeline.contradiction_detection.precision)}`} />
            <Metric label="Contradiction recall" value={pct(data.baseline_llm_judge.contradiction_detection.recall)} hint={`full pipeline: ${pct(data.pipeline.contradiction_detection.recall)}`} />
            <Metric label="Tokens used" value={data.baseline_llm_judge.total_tokens?.toLocaleString() ?? "n/a"} hint="all six reviews" />
          </div>
          {data.baseline_llm_judge.errors?.length > 0 && (
            <div className="mt-4">
              <Label>Baseline errors ({data.baseline_llm_judge.errors.length})</Label>
              <ul className="space-y-1 font-mono text-xs text-ink-300">
                {data.baseline_llm_judge.errors.map((e, i) => (
                  <li key={i}><span className="text-warn">{e.gold} → {e.predicted}</span> · {e.review} · {e.claim} · “{e.sentence}”</li>
                ))}
              </ul>
            </div>
          )}
        </Panel>
      ) : (
        <Panel className="p-5 text-sm text-ink-400">
          The LLM-as-judge baseline has not been run. Set <span className="font-mono text-ink-100">LLM_API_KEY</span> and run{" "}
          <span className="font-mono text-ink-100">python eval/run_eval.py --baseline</span> to compare it with the independent verification layer.
        </Panel>
      )}
    </div>
  );
}

export default function App() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const [tab, setTabState] = useState(TABS.some(([k]) => k === params.get("tab")) ? params.get("tab") : "verify");
  const setTab = (k) => { setTabState(k); window.history.replaceState(null, "", `#tab=${k}`); };
  const [health, setHealth] = useState(null);
  const [library, setLibrary] = useState([]);
  const [history, setHistory] = useState([]);
  const [conflicts, setConflicts] = useState([]);
  const [current, setCurrent] = useState(null);
  const [down, setDown] = useState(false);

  const refresh = useCallback(() => {
    api("/analyses").then(setHistory).catch(() => {});
    api("/disagreements").then(setConflicts).catch(() => {});
  }, []);
  const loadLibrary = useCallback(() => {
    api("/library").then(setLibrary).catch(() => {});
    api("/health").then(setHealth).catch(() => setDown(true));
  }, []);
  useEffect(() => { loadLibrary(); refresh(); }, [loadLibrary, refresh]);
  useEffect(() => {  // deep link: #tab=verify&analysis=<id>
    const id = new URLSearchParams(window.location.hash.slice(1)).get("analysis");
    if (id) api(`/analyses/${id}`).then(setCurrent).catch(() => {});
  }, []);

  return (
    <div className="mx-auto max-w-7xl px-4 pb-16 sm:px-6">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-3 py-6">
        <div className="flex items-center gap-3">
          <svg viewBox="0 0 32 32" className="h-9 w-9" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="var(--color-ink-800)" />
            <path d="M8 24l8-16 8 16M11.5 18.5h9" fill="none" stroke="var(--color-amber-glow)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <h1 className="font-display text-xl font-bold tracking-wide">AutoTruth <span className="text-amber-glow">AI</span></h1>
            <div className="text-[11px] tracking-wide text-ink-400">An AI-powered automotive review intelligence and fact-verification engine</div>
          </div>
        </div>
        {health && (
          <div className="ml-auto flex flex-wrap gap-1.5 text-[11px] text-ink-300">
            {[`${health.documents} spec documents · ${health.facts} rows`, `Retrieval: ${health.retrieval.split(" (")[0]}`,
              `NLI: ${health.nli ? "DeBERTa (" + health.nli + ")" : "off"}`, `LLM extractor: ${health.llm ? health.llm + " (opt-in)" : "not configured"}`].map((t) => (
              <span key={t} className="rounded-full border border-ink-700 bg-ink-900 px-2.5 py-1">{t}</span>
            ))}
          </div>
        )}
      </header>
      {down && <div role="alert" className="mb-4 rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-bad">The AutoTruth AI API is not reachable. Start the backend and reload.</div>}

      <nav className="mb-6 flex gap-1 overflow-x-auto border-b border-ink-700/70">
        {TABS.map(([k, label]) => (
          <button key={k} type="button" onClick={() => setTab(k)}
            className={`-mb-px whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-medium ${tab === k ? "border-amber-glow text-ink-100" : "border-transparent text-ink-400 hover:text-ink-100"}`}>
            {label}
            {k === "disagreements" && conflicts.length > 0 && <span className="ml-2 rounded-full bg-bad/20 px-1.5 py-0.5 text-[11px] font-semibold text-bad">{conflicts.length}</span>}
          </button>
        ))}
      </nav>

      {tab === "verify" && <VerifyTab library={library} llm={health?.llm} history={history} onSaved={refresh} current={current} setCurrent={setCurrent} />}
      {tab === "disagreements" && <DisagreementsTab items={conflicts} />}
      {tab === "library" && <LibraryTab library={library} reload={loadLibrary} />}
      {tab === "evaluation" && <EvaluationTab />}
    </div>
  );
}
