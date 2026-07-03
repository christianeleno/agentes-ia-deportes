const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
const playerView = document.getElementById("player-view");
const emptyState = document.getElementById("empty-state");
const emptyStateText = document.getElementById("empty-state-text");
const suggestionsEl = document.getElementById("suggestions");
const liveGamesEl = document.getElementById("live-games");
const rosterModal = document.getElementById("roster-modal");
const rosterBody = document.getElementById("roster-body");
const rosterTitle = document.getElementById("roster-title");
const sportTabs = document.getElementById("sport-tabs");

const SPORTS = {
  nba: {
    placeholder: "Buscar jugador de NBA (ej. Stephen Curry, LeBron James)...",
    emptyText: "Busca un jugador de NBA arriba para ver sus estadísticas y el análisis del agente de IA.",
    chips: ["Stephen Curry", "LeBron James", "Nikola Jokic", "Giannis Antetokounmpo", "Luka Doncic"],
    statTiles: [
      ["avgPoints", "PPG"],
      ["avgRebounds", "RPG"],
      ["avgAssists", "APG"],
      ["avgSteals", "Robos"],
      ["avgBlocks", "Bloqueos"],
      ["fieldGoalPct", "FG%"],
      ["threePointPct", "3P%"],
      ["freeThrowPct", "TL%"],
    ],
    gamelogCols: [
      ["date", "Fecha"],
      ["opponent", "Rival"],
      ["points", "PTS"],
      ["totalRebounds", "REB"],
      ["assists", "AST"],
      ["steals", "ROB"],
      ["blocks", "BLQ"],
      ["minutes", "MIN"],
    ],
  },
  nhl: {
    placeholder: "Buscar jugador de NHL (ej. Connor McDavid, Auston Matthews)...",
    emptyText: "Busca un jugador de NHL arriba para ver sus estadísticas y el análisis del agente de IA.",
    chips: ["Connor McDavid", "Auston Matthews", "Nathan MacKinnon", "Sidney Crosby", "Connor Bedard"],
    statTilesSkater: [
      ["goals", "Goles"],
      ["assists", "Asistencias"],
      ["points", "Puntos"],
      ["plusMinus", "+/-"],
      ["shots", "Tiros"],
      ["gamesPlayed", "PJ"],
    ],
    statTilesGoalie: [
      ["wins", "Victorias"],
      ["losses", "Derrotas"],
      ["goalsAgainstAvg", "GAA"],
      ["savePctg", "Efectividad"],
      ["shutouts", "Blanqueadas"],
      ["gamesPlayed", "PJ"],
    ],
    gamelogColsSkater: [
      ["gameDate", "Fecha"],
      ["opponentAbbrev", "Rival"],
      ["goals", "G"],
      ["assists", "A"],
      ["points", "PTS"],
      ["plusMinus", "+/-"],
      ["shots", "Tiros"],
      ["toi", "TOI"],
    ],
    gamelogColsGoalie: [
      ["gameDate", "Fecha"],
      ["opponentAbbrev", "Rival"],
      ["decision", "Dec."],
      ["shotsAgainst", "TA"],
      ["goalsAgainst", "GA"],
      ["savePctg", "Efect."],
      ["toi", "TOI"],
    ],
  },
  football: {
    placeholder: "Buscar jugador de fútbol (ej. Mbappé, Messi, Haaland)...",
    emptyText:
      "Busca un goleador de las principales ligas, Champions League, Mundial o Brasileirão. (Ligas europeas: en receso hasta agosto, sin datos de goleadores por ahora.)",
    chips: ["Kylian Mbappé", "Lionel Messi", "Erling Haaland", "Vinicius Junior", "Jude Bellingham"],
    hasGamelog: false,
    hasRoster: false,
    statTiles: [
      ["goals", "Goles"],
      ["assists", "Asistencias"],
      ["penalties", "Penales"],
      ["playedMatches", "PJ"],
    ],
  },
};

const FOOTBALL_STATUS_ES = {
  SCHEDULED: "Programado",
  TIMED: "Programado",
  IN_PLAY: "En vivo",
  PAUSED: "Entretiempo",
  FINISHED: "Final",
  POSTPONED: "Pospuesto",
  SUSPENDED: "Suspendido",
  CANCELLED: "Cancelado",
};

let currentSport = "nba";
let currentIsGoalie = false;
let searchTimer = null;
let liveTimer = null;

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed: ${url}`);
  return res.json();
}

function api(path) {
  return `/api/${currentSport}${path}`;
}

// --- Selector de deporte ----------------------------------------------

sportTabs.querySelectorAll(".sport-tab:not(.disabled)").forEach((tab) => {
  tab.addEventListener("click", () => switchSport(tab.dataset.sport));
});

function switchSport(sport) {
  if (sport === currentSport) return;
  currentSport = sport;
  sportTabs.querySelectorAll(".sport-tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.sport === sport);
  });
  searchInput.value = "";
  searchInput.placeholder = SPORTS[sport].placeholder;
  emptyStateText.textContent = SPORTS[sport].emptyText;
  renderSuggestions();
  playerView.classList.add("hidden");
  emptyState.classList.remove("hidden");
  searchResults.classList.add("hidden");
  loadLiveScoreboard();
}

function renderSuggestions() {
  suggestionsEl.innerHTML = SPORTS[currentSport].chips
    .map((name) => `<button class="chip" data-name="${name}">${name}</button>`)
    .join("");
  suggestionsEl.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      searchInput.value = chip.dataset.name;
      runSearch(chip.dataset.name, true);
    });
  });
}

// --- Búsqueda ------------------------------------------------------------

searchInput.addEventListener("input", () => {
  const q = searchInput.value.trim();
  clearTimeout(searchTimer);
  if (q.length < 2) {
    searchResults.classList.add("hidden");
    return;
  }
  searchTimer = setTimeout(() => runSearch(q), 250);
});

document.addEventListener("click", (e) => {
  if (!searchResults.contains(e.target) && e.target !== searchInput) {
    searchResults.classList.add("hidden");
  }
});

async function runSearch(q, autopick = false) {
  try {
    const data = await fetchJson(api(`/search?q=${encodeURIComponent(q)}`));
    if (autopick && data.results.length) {
      loadPlayer(data.results[0].id);
      searchResults.classList.add("hidden");
      return;
    }
    renderSearchResults(data.results);
  } catch (err) {
    console.error(err);
  }
}

function renderSearchResults(results) {
  if (!results.length) {
    searchResults.innerHTML = `<div class="search-result-item"><span class="sr-meta">Sin resultados</span></div>`;
    searchResults.classList.remove("hidden");
    return;
  }
  searchResults.innerHTML = results
    .map(
      (r) => `
      <div class="search-result-item" data-id="${r.id}">
        <span class="sr-name">${r.fullName}</span>
        <span class="sr-meta">${r.position}${r.team ? " · " + r.team : ""}</span>
      </div>`
    )
    .join("");
  searchResults.classList.remove("hidden");
  searchResults.querySelectorAll(".search-result-item[data-id]").forEach((el) => {
    el.addEventListener("click", () => {
      loadPlayer(el.dataset.id);
      searchResults.classList.add("hidden");
    });
  });
}

// --- Vista de jugador ------------------------------------------------------

async function loadPlayer(id) {
  emptyState.classList.add("hidden");
  playerView.classList.remove("hidden");
  document.getElementById("ai-headline").textContent = "Cargando análisis…";
  document.getElementById("ai-bullets").innerHTML = "";
  document.getElementById("props-list").innerHTML = "Cargando líneas estimadas…";

  const supportsGamelog = SPORTS[currentSport].hasGamelog !== false;
  document.getElementById("gamelog-section").classList.toggle("hidden", !supportsGamelog);

  try {
    const [profile, gamelog, insight, props] = await Promise.all([
      fetchJson(api(`/player/${id}`)),
      supportsGamelog ? fetchJson(api(`/player/${id}/gamelog`)) : Promise.resolve({ games: [] }),
      fetchJson(api(`/player/${id}/insight`)),
      fetchJson(api(`/player/${id}/prop-lines`)),
    ]);
    currentIsGoalie = !!profile.isGoalie;
    renderProfile(profile);
    renderStats(profile);
    renderInsight(insight);
    if (supportsGamelog) renderGamelog(gamelog);
    renderPropLines(props);
  } catch (err) {
    console.error(err);
    document.getElementById("ai-headline").textContent = "No se pudo cargar la información del jugador.";
  }
}

function renderProfile(p) {
  const photo = document.getElementById("player-photo");
  if (p.headshot) {
    photo.src = p.headshot;
    photo.style.visibility = "visible";
  } else {
    photo.style.visibility = "hidden";
  }
  document.getElementById("player-name").textContent = p.fullName;
  const teamName = p.team ? p.team.name || p.team.abbreviation : "Sin equipo";
  const extra = p.age
    ? `${p.age} años`
    : p.sweaterNumber
    ? `#${p.sweaterNumber}`
    : p.nationality
    ? p.nationality
    : "";
  document.getElementById("player-sub").textContent = `${p.position || ""} · ${teamName || ""} · ${extra}`;
  const gp = (p.seasonStats || {}).gamesPlayed ?? (p.seasonStats || {}).playedMatches;
  document.getElementById("player-badge").textContent = gp ? `${gp} partidos esta temporada` : "Temporada actual";
}

function renderStats(p) {
  let tiles;
  if (currentSport === "nhl") {
    tiles = currentIsGoalie ? SPORTS.nhl.statTilesGoalie : SPORTS.nhl.statTilesSkater;
  } else {
    tiles = SPORTS[currentSport].statTiles;
  }
  const stats = p.seasonStats || {};
  const grid = document.getElementById("stats-grid");
  grid.innerHTML = tiles
    .map(([key, label]) => {
      let value = stats[key];
      if (typeof value === "number") {
        if (key.toLowerCase().includes("pct") && value <= 1) value = (value * 100).toFixed(1) + "%";
        else value = Number.isInteger(value) ? value : value.toFixed(1);
      }
      return `
      <div class="stat-tile">
        <div class="stat-value">${value ?? "—"}</div>
        <div class="stat-label">${label}</div>
      </div>`;
    })
    .join("");
}

function renderInsight(insight) {
  document.getElementById("ai-headline").textContent = insight.headline;
  const pill = document.getElementById("ai-rating");
  pill.textContent = insight.rating;
  pill.className = `rating-pill ${insight.rating}`;
  document.getElementById("ai-bullets").innerHTML = insight.bullets.map((b) => `<li>${b}</li>`).join("");

  const prob = insight.probability;
  const box = document.getElementById("player-semaphore");
  if (prob) {
    box.className = `semaphore-box ${prob.level}`;
    document.getElementById("player-semaphore-pct").textContent = `${prob.pct}%`;
    document.getElementById("player-semaphore-label").textContent = prob.label;
  }
}

function renderPropLines(props) {
  const list = document.getElementById("props-list");
  const lines = props.lines || [];
  if (!lines.length) {
    list.innerHTML = `<p style="color:var(--muted); font-size:12px;">No hay suficientes partidos jugados esta temporada para estimar líneas.</p>`;
    return;
  }
  list.innerHTML = lines
    .map(
      (l) => `
      <div class="prop-row">
        <span class="pr-title">${l.statLabel}</span>
        <span class="pr-line">Más de ${l.line}</span>
        <span class="pr-pct ${l.level}">${l.pct}% probabilidad</span>
      </div>`
    )
    .join("");
}

function renderGamelog(gamelog) {
  const head = document.getElementById("gamelog-head");
  const body = document.getElementById("gamelog-body");
  let cols;
  if (currentSport === "nhl") {
    cols = currentIsGoalie ? SPORTS.nhl.gamelogColsGoalie : SPORTS.nhl.gamelogColsSkater;
  } else {
    cols = SPORTS.nba.gamelogCols;
  }
  head.innerHTML = `<tr>${cols.map(([, label]) => `<th>${label}</th>`).join("")}</tr>`;
  body.innerHTML = (gamelog.games || [])
    .map((g) => `<tr>${cols.map(([key]) => `<td>${formatCell(key, g[key])}</td>`).join("")}</tr>`)
    .join("");
}

function formatCell(key, value) {
  if (value === undefined || value === null || value === "") return "—";
  if (key === "gameDate" || key === "date") return String(value).slice(0, 10);
  if (key === "savePctg" && typeof value === "number") return (value * 100).toFixed(1) + "%";
  return value;
}

document.getElementById("gamelog-toggle").addEventListener("click", () => {
  document.getElementById("gamelog-section").classList.toggle("open");
});

// --- Marcador en vivo -------------------------------------------------------

function footballDetail(g) {
  const label = FOOTBALL_STATUS_ES[g.status] || g.status || "";
  if (g.status === "FINISHED" || g.status === "IN_PLAY" || g.status === "PAUSED") {
    return `${g.competition || ""} · ${label}`;
  }
  const time = g.date
    ? new Intl.DateTimeFormat("es-EC", { timeZone: "America/Guayaquil", hour: "numeric", minute: "2-digit", hour12: true }).format(new Date(g.date))
    : "";
  return `${g.competition || ""} · ${label} ${time}`;
}

async function loadLiveScoreboard() {
  liveGamesEl.textContent = "Cargando partidos de hoy…";
  const hasRoster = SPORTS[currentSport].hasRoster !== false;
  try {
    const data = await fetchJson(api("/live"));
    if (!data.games.length) {
      liveGamesEl.innerHTML = `<span style="color:var(--muted); font-size:12px;">No hay partidos programados hoy.</span>`;
      return;
    }
    liveGamesEl.innerHTML = data.games
      .map((g) => {
        const wp = g.winProbability;
        const wpText = wp ? `Prob. victoria: ${g.away.abbreviation || g.away.name} ${wp.away}% · ${g.home.abbreviation || g.home.name} ${wp.home}%` : "";
        const detail = currentSport === "football" ? footballDetail(g) : g.detail || "";
        return `
        <div class="live-game${hasRoster ? "" : " no-roster"}" data-game-id="${g.id}" data-matchup="${g.away.name} @ ${g.home.name}">
          <span class="lg-status">${detail}</span>
          ${g.away.name} ${g.away.score ?? ""} @ ${g.home.name} ${g.home.score ?? ""}
          ${wpText ? `<span class="lg-winprob">${wpText}</span>` : ""}
        </div>`;
      })
      .join("");
    if (hasRoster) {
      liveGamesEl.querySelectorAll(".live-game[data-game-id]").forEach((el) => {
        el.addEventListener("click", () => openRoster(el.dataset.gameId, el.dataset.matchup));
      });
    }
  } catch (err) {
    console.error(err);
    liveGamesEl.textContent = "No se pudo cargar el marcador en vivo.";
  }
}

async function openRoster(gameId, titleText) {
  rosterModal.classList.remove("hidden");
  rosterTitle.textContent = titleText || "Alineaciones";
  rosterBody.innerHTML = "Cargando alineaciones…";
  try {
    const data = await fetchJson(api(`/game/${gameId}/roster`));
    rosterBody.innerHTML = `
      <div class="roster-teams">
        ${renderRosterTeam(data.away)}
        ${renderRosterTeam(data.home)}
      </div>`;
    rosterBody.querySelectorAll(".roster-player[data-id]").forEach((el) => {
      el.addEventListener("click", () => {
        closeRoster();
        loadPlayer(el.dataset.id);
      });
    });
  } catch (err) {
    console.error(err);
    rosterBody.innerHTML = "No se pudieron cargar las alineaciones de este partido.";
  }
}

function renderRosterTeam(team) {
  const players = (team && team.players) || [];
  if (!players.length) {
    return `<div class="roster-team"><h4>${(team && team.teamName) || ""}</h4><p style="color:var(--muted); font-size:12px;">Alineación no disponible aún.</p></div>`;
  }
  return `
    <div class="roster-team">
      <h4>${team.teamName || ""}</h4>
      ${players
        .map(
          (p) => `
        <div class="roster-player" data-id="${p.id}">
          <span class="rp-name">${p.fullName}</span>
          <span class="rp-pos">${p.position || ""}</span>
          <span class="rp-pts">${p.points ?? ""}</span>
        </div>`
        )
        .join("")}
    </div>`;
}

function closeRoster() {
  rosterModal.classList.add("hidden");
}

document.getElementById("roster-close").addEventListener("click", closeRoster);
rosterModal.addEventListener("click", (e) => {
  if (e.target === rosterModal) closeRoster();
});

// --- Arranque ----------------------------------------------------------------

renderSuggestions();
searchInput.placeholder = SPORTS[currentSport].placeholder;
loadLiveScoreboard();
liveTimer = setInterval(loadLiveScoreboard, 30000);
