/* ─── State ─────────────────────────────────────────────────────────────── */
const state = {
  location:      null,         // full geocode object
  analysis_type: 'brand',      // 'brand' | 'cuisine'
  distance:      5,            // numeric distance value
  distance_unit: 'mi',         // 'mi' | 'km'
  signals:       [],           // [{id, name, kind, subtype}]
  age_groups:    new Set(),
  signal_tab:    'entity',
  activeCardId:  null,
};

const MI_TO_M = 1609.34;
const KM_TO_M = 1000;

function radiusMeters() {
  return state.distance * (state.distance_unit === 'mi' ? MI_TO_M : KM_TO_M);
}

/* ─── Map state ─────────────────────────────────────────────────────────── */
let map            = null;
let centerMarker   = null;
let ringLayers     = [];
let poiLayers      = {};
let cuisineMarkers = [];

/* ─── DOM refs ──────────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);

const locationInput    = $('location-input');
const locationDropdown = $('location-dropdown');
const locationPill     = $('location-pill');

const distanceInput = $('distance-input');
const unitToggle    = $('unit-toggle');
const radiusHint    = $('radius-hint');

const signalInput    = $('signal-input');
const signalDropdown = $('signal-dropdown');
const signalPills    = $('signal-pills');

const ageGrid        = $('age-grid');
const analyzeBtn     = $('analyze-btn');
const sidebarResults = $('sidebar-results');

const emptyState = $('empty-state');
const loadingEl  = $('loading');
const errorState = $('error-state');
const errorMsg   = $('error-msg');

/* ─── Utility ───────────────────────────────────────────────────────────── */
function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function hideOverlays() {
  [emptyState, loadingEl, errorState].forEach(el => el.classList.add('hidden'));
}

function show(el) { el.classList.remove('hidden'); }

function checkEnabled() {
  analyzeBtn.disabled = !state.location;
}

/* ─── Distance controls ─────────────────────────────────────────────────── */
distanceInput.addEventListener('input', () => {
  const v = parseFloat(distanceInput.value);
  if (!isNaN(v) && v > 0) state.distance = v;
});

unitToggle.querySelectorAll('.unit-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    unitToggle.querySelectorAll('.unit-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.distance_unit = btn.dataset.unit;
  });
});

/* ─── Radius hint helper ─────────────────────────────────────────────────── */
function updateRadiusHint() {
  if (state.analysis_type === 'cuisine') {
    radiusHint.textContent = 'Straight-line radius from your address';
  } else {
    radiusHint.textContent = 'Used for void assessment — affinity signals are drawn from a 2-block area around the address';
  }
}

/* ─── Analysis type toggle ──────────────────────────────────────────────── */
document.getElementById('analysis-type-toggle').querySelectorAll('.mode-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.getElementById('analysis-type-toggle').querySelectorAll('.mode-btn')
      .forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.analysis_type = btn.dataset.type;
    analyzeBtn.textContent = state.analysis_type === 'cuisine'
      ? 'Analyze Cuisine Voids' : 'Analyze Voids';
    updateRadiusHint();
  });
});

/* ─── Location typeahead ────────────────────────────────────────────────── */
const onLocationInput = debounce(async () => {
  const q = locationInput.value.trim();
  if (q.length < 3) { locationDropdown.classList.add('hidden'); return; }
  try {
    const res = await fetch(
      `/api/geocode-suggest?q=${encodeURIComponent(q)}&mode=address`
    );
    const results = await res.json();
    buildDropdown(locationDropdown, results.map(r => ({
      id:   `${r.lat},${r.lon}`,
      name: r.display_name,
      _raw: r,
    })), item => selectLocation(item._raw));
  } catch (_) {}
}, 350);

function selectLocation(raw) {
  state.location = raw;
  locationInput.value = '';
  locationDropdown.classList.add('hidden');
  locationPill.innerHTML = '';
  const pill = document.createElement('span');
  pill.className = 'pill blurple';
  const short = raw.display_name.split(',').slice(0, 2).join(',').trim();
  pill.innerHTML = `${escHtml(short)} <span class="pill-x" title="Remove">×</span>`;
  pill.querySelector('.pill-x').addEventListener('click', () => {
    state.location = null;
    locationPill.innerHTML = '';
    checkEnabled();
  });
  locationPill.appendChild(pill);
  checkEnabled();
  if (map) map.setView([raw.lat, raw.lon], 13);
}

locationInput.addEventListener('input', onLocationInput);
locationInput.addEventListener('blur', () =>
  setTimeout(() => locationDropdown.classList.add('hidden'), 150)
);

/* ─── Signal search ─────────────────────────────────────────────────────── */
const onSignalInput = debounce(async () => {
  const q = signalInput.value.trim();
  if (q.length < 2) { signalDropdown.classList.add('hidden'); return; }
  const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&kind=${state.signal_tab}`);
  const results = await res.json();
  buildDropdown(signalDropdown, results, addSignal);
}, 300);

signalInput.addEventListener('input', onSignalInput);
signalInput.addEventListener('blur', () =>
  setTimeout(() => signalDropdown.classList.add('hidden'), 150)
);

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.signal_tab = btn.dataset.tab;
    signalInput.value = '';
    signalDropdown.classList.add('hidden');
  });
});

function addSignal(item) {
  if (state.signals.find(s => s.id === item.id)) return;
  state.signals.push(item);
  signalInput.value = '';
  signalDropdown.classList.add('hidden');
  renderSignalPills();
}

function removeSignal(id) {
  state.signals = state.signals.filter(s => s.id !== id);
  renderSignalPills();
}

function renderSignalPills() {
  signalPills.innerHTML = '';
  state.signals.forEach(s => {
    const pill = document.createElement('span');
    pill.className = 'pill green';
    const badge = s.subtype
      ? ` <span class="pill-badge">${escHtml(s.subtype)}</span>` : '';
    pill.innerHTML = `${escHtml(s.name)}${badge} <span class="pill-x">×</span>`;
    pill.querySelector('.pill-x').addEventListener('click', () => removeSignal(s.id));
    signalPills.appendChild(pill);
  });
}

/* ─── Age groups ────────────────────────────────────────────────────────── */
ageGrid.querySelectorAll('.age-option').forEach(label => {
  label.addEventListener('click', e => {
    e.preventDefault();
    const key = label.dataset.key;
    if (state.age_groups.has(key)) {
      state.age_groups.delete(key);
      label.classList.remove('checked');
    } else {
      state.age_groups.add(key);
      label.classList.add('checked');
    }
  });
});

/* ─── Dropdown builder ──────────────────────────────────────────────────── */
function buildDropdown(dropdown, items, onSelect) {
  dropdown.innerHTML = '';
  if (!items.length) { dropdown.classList.add('hidden'); return; }
  items.forEach(item => {
    const div = document.createElement('div');
    div.className = 'search-dropdown-item';
    div.innerHTML = `${escHtml(item.name)}${item.subtype
      ? ` <span class="item-badge">${escHtml(item.subtype)}</span>` : ''}`;
    div.addEventListener('mousedown', e => { e.preventDefault(); onSelect(item); });
    dropdown.appendChild(div);
  });
  dropdown.classList.remove('hidden');
}

/* ─── Map init ──────────────────────────────────────────────────────────── */
function initMap() {
  map = L.map('map', { zoomControl: true }).setView([39.8, -98.6], 4);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map);
}

function clearMapLayers() {
  if (centerMarker) { map.removeLayer(centerMarker); centerMarker = null; }
  ringLayers.forEach(l => map.removeLayer(l));
  ringLayers = [];
  Object.values(poiLayers).forEach(g => map.removeLayer(g));
  poiLayers = {};
  clearCuisineMarkers();
}

function dotIcon(statusClass) {
  return L.divIcon({
    className: '',
    html: `<div class="map-dot dot-${statusClass}"></div>`,
    iconSize: [10, 10],
    iconAnchor: [5, 5],
  });
}

function renderMapPins(location, brands) {
  clearMapLayers();

  centerMarker = L.circleMarker([location.lat, location.lon], {
    radius: 8, color: '#003366', fillColor: '#003366', fillOpacity: 0.9, weight: 2,
  }).addTo(map).bindPopup(`<b>${escHtml(location.display_name.split(',')[0])}</b>`);

  const voidCount = brands.filter(b => b.status === 'Hard Void' || b.status === 'Near Void').length;
  const ringColor = voidCount >= 10 ? '#CC0033' : voidCount >= 5 ? '#FF6600' : '#003366';

  const dist = state.distance;
  const toM  = state.distance_unit === 'mi' ? MI_TO_M : KM_TO_M;
  const unit = state.distance_unit;

  // Single ring at chosen distance
  const r = L.circle([location.lat, location.lon], {
    radius:    dist * toM,
    color:     ringColor,
    weight:    2,
    fill:      false,
  }).addTo(map).bindTooltip(`${dist} ${unit}`);
  ringLayers.push(r);

  map.fitBounds(
    L.circle([location.lat, location.lon], { radius: dist * toM }).getBounds(),
    { padding: [24, 24] }
  );
}

/* ─── Results rendering ─────────────────────────────────────────────────── */
const STATUS_LEGEND_LOCALITY = [
  { cls: 'hard-void',   label: 'Pop-up Candidate',
    desc: 'No permanent locations found. Brand may be DTC or digitally native — strong pop-up or experiential opportunity.' },
  { cls: 'near-void',   label: 'Near Void',
    desc: 'Has physical presence elsewhere, but none confirmed in this region.' },
  { cls: 'underserved', label: 'Underserved',
    desc: 'In this state or metro but absent from this locality. Proximity gap exists.' },
  { cls: 'present',     label: 'Present',
    desc: 'Already operating in this city. Consider co-tenancy or expansion.' },
];

const STATUS_LEGEND_ADDRESS = [
  { cls: 'hard-void',   label: 'Pop-up Candidate',
    desc: 'No permanent locations found. Brand may be DTC or digitally native — strong pop-up or experiential opportunity.' },
  { cls: 'near-void',   label: 'Near Void',
    desc: 'Has physical presence, but none confirmed in this region.' },
  { cls: 'available',   label: 'Available',
    desc: 'Located within this state — accessible within ~25–50 miles of this address.' },
  { cls: 'underserved', label: 'Underserved',
    desc: 'In the metro area but not at this specific location.' },
  { cls: 'present',     label: 'Present',
    desc: 'Operating in this city. Consider co-tenancy or expansion.' },
];

const STATUS_LEGEND_CUISINE = [
  { cls: 'cuisine-void', label: 'Cuisine Void',
    desc: 'No restaurants of this type found within the search radius or nearby.' },
  { cls: 'near-void',    label: 'Near Void',
    desc: 'None within your radius — nearest option found beyond it.' },
  { cls: 'underserved',  label: 'Underserved',
    desc: 'Above-median demand but below-median share of the local restaurant mix. Real opportunity.' },
  { cls: 'niche',        label: 'Niche',
    desc: 'Below-median demand and below-median distribution — small market, currently balanced.' },
  { cls: 'present',      label: 'Well Represented',
    desc: 'Demand and supply share are proportionate — market is served.' },
  { cls: 'saturated',    label: 'Saturated',
    desc: 'Above-median distribution but below-median demand — more supply than the audience warrants.' },
];

function renderResults(data) {
  sidebarResults.innerHTML = '';

  // ── Export button ─────────────────────────────────────────────
  const exportBtn = document.createElement('button');
  exportBtn.className = 'export-pdf-btn';
  exportBtn.innerHTML = '⬇ Export PDF';
  exportBtn.addEventListener('click', () => exportBrandPDF(data));
  sidebarResults.appendChild(exportBtn);

  // ── Summary chips ─────────────────────────────────────────────
  const summary = document.createElement('div');
  summary.className = 'void-summary';
  summary.id = 'void-summary';
  sidebarResults.appendChild(summary);

  // ── Status legend ─────────────────────────────────────────────
  const legend = document.createElement('div');
  legend.className = 'void-legend';
  legend.innerHTML = `<div class="void-legend-header">Void Status Key</div>` +
    STATUS_LEGEND_ADDRESS.map(({ cls, label, desc }) => `
      <div class="void-legend-item">
        <span class="void-legend-dot dot-${cls}"></span>
        <span class="void-legend-label">${label}</span>
        <span class="void-legend-desc">${escHtml(desc)}</span>
      </div>`).join('');
  sidebarResults.appendChild(legend);

  // ── Brand cards ───────────────────────────────────────────────
  data.brands.forEach(brand => {
    const card = document.createElement('div');
    card.className = 'void-card';
    card.dataset.id = brand.id;

    const nearbyHtml = (brand.nearby || []).slice(0, 1).map(loc => {
      const parts = [loc.city, loc.state].filter(Boolean).join(', ');
      return `<div class="void-nearby">${escHtml(loc.name)}${parts
        ? ` <span class="void-nearby-loc">${escHtml(parts)}</span>` : ''}</div>`;
    }).join('');

    const descHtml = brand.description
      ? `<div class="void-card-desc">${escHtml(brand.description)}</div>` : '';

    card.innerHTML = `
      <div class="void-card-top">
        <span class="void-card-name">${escHtml(brand.name)}</span>
        <span class="status-badge status-${brand.status_class}">${escHtml(brand.status)}</span>
      </div>
      ${descHtml}
      ${nearbyHtml}
    `;
    card.addEventListener('click', () => focusBrand(brand));
    sidebarResults.appendChild(card);
  });

  // ── Populate chips after cards exist ─────────────────────────
  let activeFilter = null;
  const counts = {};
  data.brands.forEach(b => { counts[b.status] = (counts[b.status] || 0) + 1; });
  [
    { cls: 'hard-void',   status: 'Pop-up Candidate' },
    { cls: 'near-void',   status: 'Near Void' },
    { cls: 'available',   status: 'Available' },
    { cls: 'underserved', status: 'Underserved' },
    { cls: 'present',     status: 'Present' },
  ].filter(c => counts[c.status] > 0).forEach(({ cls, status }) => {
    const chip = document.createElement('span');
    chip.className = `void-summary-chip chip-${cls}`;
    chip.textContent = `${counts[status]} ${status}`;
    chip.addEventListener('click', () => {
      if (activeFilter === status) {
        activeFilter = null;
        chip.classList.remove('chip-active');
        sidebarResults.querySelectorAll('.void-card').forEach(c => c.classList.remove('hidden'));
      } else {
        activeFilter = status;
        summary.querySelectorAll('.void-summary-chip').forEach(c => c.classList.remove('chip-active'));
        chip.classList.add('chip-active');
        sidebarResults.querySelectorAll('.void-card').forEach(c => {
          const brand = data.brands.find(b => b.id === c.dataset.id);
          c.classList.toggle('hidden', !brand || brand.status !== status);
        });
      }
    });
    summary.appendChild(chip);
  });
}

function focusBrand(brand) {
  document.querySelectorAll('.void-card').forEach(c => c.classList.remove('active'));
  const card = document.querySelector(`.void-card[data-id="${brand.id}"]`);
  if (card) { card.classList.add('active'); card.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
  state.activeCardId = brand.id;

  const toM = state.distance_unit === 'mi' ? MI_TO_M : KM_TO_M;
  if (state.location) {
    map.fitBounds(
      L.circle([state.location.lat, state.location.lon],
        { radius: state.distance * toM }).getBounds(),
      { padding: [40, 40] }
    );
  }
}

/* ─── Cuisine map helpers ────────────────────────────────────────────────── */
function clearCuisineMarkers() {
  cuisineMarkers.forEach(m => map && map.removeLayer(m));
  cuisineMarkers = [];
}

async function plotCuisineVenues(places, mapBtn) {
  clearCuisineMarkers();
  const addresses = places.slice(0, 5).map(p => p.address || '');
  mapBtn.disabled = true;
  mapBtn.textContent = 'Loading…';
  try {
    const res = await fetch('/api/geocode-venues', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ addresses }),
    });
    const geos = await res.json();
    geos.forEach((geo, i) => {
      if (!geo) return;
      const venue = places[i];
      const marker = L.circleMarker([geo.lat, geo.lon], {
        radius: 7, color: '#FF6600', fillColor: '#FF6600', fillOpacity: 0.85, weight: 2,
      }).addTo(map).bindPopup(
        `<b>${escHtml(venue.name || '')}</b>${venue.address ? '<br>' + escHtml(venue.address) : ''}`
      );
      cuisineMarkers.push(marker);
    });
  } catch (err) {
    console.error('geocode-venues error:', err);
  }
  mapBtn.disabled = false;
  mapBtn.textContent = '📍 Map';
}

/* ─── Cuisine results rendering ─────────────────────────────────────────── */
function renderCuisineResults(data) {
  sidebarResults.innerHTML = '';
  clearCuisineMarkers();

  // Address context header
  const loc = data.location;
  const localityName = loc.display_name || loc.city || 'this area';
  const ctxEl = document.createElement('div');
  ctxEl.className = 'cuisine-locality-ctx';
  ctxEl.innerHTML =
    `<span class="cuisine-locality-label">Address assessed</span>` +
    `<span class="cuisine-locality-name">${escHtml(localityName)}</span>` +
    `<span class="cuisine-locality-note">Top 12 cuisines by demand signal · Supply counted within radius</span>`;
  sidebarResults.appendChild(ctxEl);

  // Legend
  const legend = document.createElement('div');
  legend.className = 'void-legend';
  legend.innerHTML = `<div class="void-legend-header">Cuisine Void Key</div>` +
    STATUS_LEGEND_CUISINE.map(({ cls, label, desc }) => `
      <div class="void-legend-item">
        <span class="void-legend-dot dot-${cls}"></span>
        <span class="void-legend-label">${label}</span>
        <span class="void-legend-desc">${escHtml(desc)}</span>
      </div>`).join('') +
    `<div class="void-legend-note">Affinity = median local relevance score of found restaurants · Supply = count of matching venues in Qloo's catalog within radius</div>`;
  sidebarResults.appendChild(legend);

  // Export button
  const exportBtn = document.createElement('button');
  exportBtn.className = 'export-pdf-btn';
  exportBtn.innerHTML = '⬇ Export PDF';
  exportBtn.addEventListener('click', () => exportCuisinePDF(data));
  sidebarResults.appendChild(exportBtn);

  // Summary chips with clickable filter
  const summary = document.createElement('div');
  summary.className = 'void-summary';
  const counts = { 'Cuisine Void': 0, 'Near Void': 0, 'Underserved': 0, 'Niche': 0, 'Well Represented': 0, 'Saturated': 0 };
  data.cuisines.forEach(c => { counts[c.status] = (counts[c.status] || 0) + 1; });
  let cuisineActiveFilter = null;
  [
    { cls: 'cuisine-void', label: `${counts['Cuisine Void']} Cuisine Voids`,       status: 'Cuisine Void' },
    { cls: 'near-void',    label: `${counts['Near Void']} Near Voids`,             status: 'Near Void' },
    { cls: 'underserved',  label: `${counts['Underserved']} Underserved`,           status: 'Underserved' },
    { cls: 'niche',        label: `${counts['Niche']} Niche`,                       status: 'Niche' },
    { cls: 'present',      label: `${counts['Well Represented']} Well Represented`, status: 'Well Represented' },
    { cls: 'saturated',    label: `${counts['Saturated']} Saturated`,               status: 'Saturated' },
  ].filter(c => parseInt(c.label) > 0).forEach(({ cls, label, status }) => {
    const chip = document.createElement('span');
    chip.className = `void-summary-chip chip-${cls}`;
    chip.textContent = label;
    chip.dataset.filter = status;
    chip.addEventListener('click', () => {
      const cards = sidebarResults.querySelectorAll('.cuisine-card');
      if (cuisineActiveFilter === status) {
        cuisineActiveFilter = null;
        chip.classList.remove('chip-active');
        cards.forEach(c => c.classList.remove('hidden'));
      } else {
        cuisineActiveFilter = status;
        summary.querySelectorAll('.void-summary-chip').forEach(c => c.classList.remove('chip-active'));
        chip.classList.add('chip-active');
        cards.forEach(c => {
          c.classList.toggle('hidden', c.dataset.status !== status);
        });
      }
    });
    summary.appendChild(chip);
  });
  sidebarResults.appendChild(summary);

  // Cuisine cards (expandable — local venues shown immediately)
  data.cuisines.forEach(cuisine => {
    const card = document.createElement('div');
    card.className = 'void-card cuisine-card';
    card.dataset.status = cuisine.status;

    const cityLabel = escHtml(loc.city || localityName);
    const totalSampled = data.total_sampled || 0;
    const demandCount  = cuisine.demand_count || 0;
    const demandPct    = totalSampled > 0
      ? Math.round((demandCount / totalSampled) * 100) : 0;
    const radiusMi = Math.round((data.radius_m || 8047) / 1609.34 * 10) / 10;
    let supplyText;
    if (cuisine.supply_count > 0) {
      supplyText = `${cuisine.supply_count} venue${cuisine.supply_count === 1 ? '' : 's'} within ${radiusMi} mi`;
    } else if (cuisine.nearest_venue) {
      supplyText = `None within ${radiusMi} mi — nearest within ${cuisine.found_at_radius_mi} mi: ${escHtml(cuisine.nearest_venue)}`;
    } else {
      supplyText = `None found within 50 mi`;
    }

    const demandHtml = totalSampled > 0
      ? `<div class="cuisine-demand-row">
           <span class="cuisine-demand-label">Demand signal</span>
           <div class="cuisine-demand-bar-wrap">
             <div class="cuisine-demand-bar" style="width:${Math.min(demandPct * 5, 100)}%"></div>
           </div>
           <span class="cuisine-demand-pct">${demandCount} of ${totalSampled}</span>
         </div>`
      : '';

    const localPlaces  = (cuisine.places || []).filter(p => p.local);
    const globalPlaces = (cuisine.places || []).filter(p => !p.local);
    const hasPlaces    = localPlaces.length > 0 || globalPlaces.length > 0;
    const hasAddresses = (cuisine.places || []).some(p => p.address);

    card.innerHTML = `
      <div class="void-card-top">
        <span class="void-card-name">${escHtml(cuisine.cuisine)}</span>
        <span class="status-badge status-${cuisine.status_class}">${escHtml(cuisine.status)}</span>
      </div>
      ${demandHtml}
      <div class="cuisine-supply">
        ${supplyText}
        ${hasPlaces ? `<span class="cuisine-expand-toggle">▸ Venues</span>` : ''}
        ${hasAddresses ? `<button class="cuisine-map-btn">📍 Map</button>` : ''}
      </div>
      <div class="cuisine-place-list hidden"></div>
    `;

    if (!hasPlaces) {
      sidebarResults.appendChild(card);
      return;
    }

    const toggle = card.querySelector('.cuisine-expand-toggle');
    const list   = card.querySelector('.cuisine-place-list');
    const mapBtn = card.querySelector('.cuisine-map-btn');

    // Build venue list HTML once from already-loaded data
    let html = '';
    if (localPlaces.length) {
      html += `<div class="cuisine-place-group-label">In ${cityLabel}</div>`;
      html += localPlaces.map(p => placeRow(p)).join('');
    }
    if (globalPlaces.length) {
      html += `<div class="cuisine-place-group-label cuisine-place-group-global">Also in Qloo's catalog</div>`;
      html += globalPlaces.map(p => placeRow(p, true)).join('');
    }
    list.innerHTML = html;

    toggle.addEventListener('click', e => {
      e.stopPropagation();
      const open = !list.classList.contains('hidden');
      list.classList.toggle('hidden', open);
      toggle.textContent = open ? '▸ Venues' : '▾ Venues';
    });

    if (mapBtn) {
      mapBtn.addEventListener('click', e => {
        e.stopPropagation();
        plotCuisineVenues(cuisine.places || [], mapBtn);
      });
    }

    sidebarResults.appendChild(card);
  });
}

function placeRow(p, showCity = false) {
  const affStr  = p.affinity != null
    ? `<span class="cuisine-place-aff">${(p.affinity * 100).toFixed(0)}%</span>` : '';
  const addrStr = p.address
    ? `<span class="cuisine-place-addr">${escHtml(p.address)}</span>` : '';
  const cityStr = showCity && p.city && !p.address
    ? `<span class="cuisine-place-city">${escHtml(p.city)}</span>` : '';
  return `<div class="cuisine-place-row">
    <div class="cuisine-place-main">
      <span class="cuisine-place-name">${escHtml(p.name)}</span>
      ${addrStr}${cityStr}
    </div>
    <span class="cuisine-place-meta">${affStr}</span>
  </div>`;
}

/* ─── PDF Export ────────────────────────────────────────────────────────── */
function exportCuisinePDF(data) {
  const loc        = data.location;
  const radiusMi   = Math.round((data.radius_m || 8047) / 1609.34 * 10) / 10;
  const addrLabel  = loc.display_name || loc.city || 'Unknown address';
  const signals    = state.signals.map(s => s.name).join(', ') || 'None';
  const ageGroups  = [...state.age_groups].join(', ') || 'All';
  const now        = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });

  const STATUS_COLORS = {
    'Cuisine Void':    '#7A0026',
    'Near Void':       '#FF6600',
    'Underserved':     '#B38600',
    'Niche':           '#2596BE',
    'Well Represented':'#007A3D',
    'Saturated':       '#7B4FBF',
  };

  const rowsHtml = data.cuisines.map(c => {
    const color     = STATUS_COLORS[c.status] || '#646E78';
    const distShare = c.distribution_share != null
      ? (c.distribution_share * 100).toFixed(1) + '%' : '—';
    const supply    = c.supply_count > 0
      ? c.supply_count
      : (c.nearest_venue ? `0 (nearest: ${c.nearest_venue}, ~${c.found_at_radius_mi} mi)` : '0');
    return `<tr>
      <td style="font-weight:600">${escHtml(c.cuisine)}</td>
      <td><span style="background:${color}18;color:${color};border:1px solid ${color}33;
        padding:2px 7px;border-radius:4px;font-size:11px;font-weight:600;white-space:nowrap">
        ${escHtml(c.status)}</span></td>
      <td style="text-align:right">${c.demand_count}</td>
      <td style="text-align:right">${supply}</td>
      <td style="text-align:right">${distShare}</td>
    </tr>`;
  }).join('');

  const interpretRows = [
    ['Cuisine Void',    '#7A0026', 'No restaurants of this type found within the search radius or anywhere within 50 mi.'],
    ['Near Void',       '#FF6600', 'None within your radius — nearest option was found just beyond it.'],
    ['Underserved',     '#B38600', 'Above-median demand but below-median distribution share. A real market opportunity.'],
    ['Niche',           '#2596BE', 'Below-median demand and below-median distribution — small but currently balanced.'],
    ['Well Represented','#007A3D', 'Demand and supply share are proportionate — the market is well served.'],
    ['Saturated',       '#7B4FBF', 'More supply than the audience warrants — above-median distribution, below-median demand.'],
  ].map(([label, color, desc]) =>
    `<tr>
      <td style="white-space:nowrap"><span style="display:inline-block;width:8px;height:8px;
        border-radius:50%;background:${color};margin-right:6px;vertical-align:middle"></span>
        <strong>${label}</strong></td>
      <td style="color:#646E78">${desc}</td>
    </tr>`
  ).join('');

  const html = `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Void Analysis Report — ${escHtml(addrLabel)}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 12px; color: #282832; padding: 32px; }
  h1 { font-size: 20px; color: #003366; margin-bottom: 4px; }
  h2 { font-size: 13px; color: #003366; margin: 20px 0 8px; border-bottom: 1px solid #D0D8E2; padding-bottom: 4px; text-transform: uppercase; letter-spacing: 0.08em; }
  .meta { color: #646E78; font-size: 11px; margin-bottom: 20px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
  th { text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: #646E78; padding: 6px 8px; border-bottom: 2px solid #D0D8E2; }
  td { padding: 7px 8px; border-bottom: 1px solid #E6EBF0; vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  .inputs-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 24px; margin-bottom: 8px; }
  .input-row { display: flex; gap: 6px; }
  .input-label { color: #646E78; min-width: 80px; }
  .footer { margin-top: 28px; font-size: 10px; color: #B4BEC8; border-top: 1px solid #E6EBF0; padding-top: 10px; }
  @media print { body { padding: 16px; } }
</style>
</head>
<body>
  <h1>Void Analysis — Cuisine Report</h1>
  <div class="meta">Generated ${now} · Powered by Qloo Taste AI™</div>

  <h2>Inputs</h2>
  <div class="inputs-grid">
    <div class="input-row"><span class="input-label">Address</span><strong>${escHtml(addrLabel)}</strong></div>
    <div class="input-row"><span class="input-label">Radius</span><strong>${radiusMi} mi</strong></div>
    <div class="input-row"><span class="input-label">Signals</span><strong>${escHtml(signals)}</strong></div>
    <div class="input-row"><span class="input-label">Age groups</span><strong>${escHtml(ageGroups)}</strong></div>
    <div class="input-row"><span class="input-label">Sampled</span><strong>${data.total_sampled || 0} venues for demand signal</strong></div>
    <div class="input-row"><span class="input-label">Cuisines</span><strong>Top 12 by demand rank</strong></div>
  </div>

  <h2>Cuisine Void Results</h2>
  <table>
    <thead><tr>
      <th>Cuisine</th><th>Status</th>
      <th style="text-align:right">Demand Count</th>
      <th style="text-align:right">Supply (within ${radiusMi} mi)</th>
      <th style="text-align:right">Distribution Share</th>
    </tr></thead>
    <tbody>${rowsHtml}</tbody>
  </table>

  <h2>How to Interpret Results</h2>
  <p style="color:#646E78;font-size:11px;margin-bottom:8px">
    Demand is measured by how often a cuisine appears in a locally-sampled restaurant mix.
    Distribution share is each cuisine's proportion of the total supply count within the radius.
    Status is assigned by comparing each cuisine's demand and distribution share to the median across all cuisines.
  </p>
  <table>
    <thead><tr><th>Status</th><th>Meaning</th></tr></thead>
    <tbody>${interpretRows}</tbody>
  </table>

  <div class="footer">Void Analysis · Qloo Taste AI™ · ${now}</div>
</body>
</html>`;

  const win = window.open('', '_blank');
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 600);
}

function exportBrandPDF(data) {
  const loc        = data.location;
  const radiusMi   = Math.round((data.radius_m || 8047) / 1609.34 * 10) / 10;
  const addrLabel  = loc.display_name || loc.city || 'Unknown address';
  const signals    = state.signals.map(s => s.name).join(', ') || 'None';
  const ageGroups  = [...state.age_groups].join(', ') || 'All';
  const now        = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });

  const STATUS_COLORS = {
    'Pop-up Candidate': '#CC0033',
    'Near Void':        '#FF6600',
    'Available':        '#2596BE',
    'Underserved':      '#B38600',
    'Present':          '#007A3D',
  };

  const rowsHtml = data.brands.map(b => {
    const color = STATUS_COLORS[b.status] || '#646E78';
    return `<tr>
      <td style="font-weight:600">${escHtml(b.name)}</td>
      <td>${escHtml(b.tier || '')}</td>
      <td><span style="background:${color}18;color:${color};border:1px solid ${color}33;
        padding:2px 7px;border-radius:4px;font-size:11px;font-weight:600;white-space:nowrap">
        ${escHtml(b.status)}</span></td>
    </tr>`;
  }).join('');

  const interpretRows = [
    ['Pop-up Candidate', '#CC0033', 'No permanent locations found. Strong pop-up or experiential opportunity.'],
    ['Near Void',        '#FF6600', 'Has physical presence elsewhere, but none confirmed in this region.'],
    ['Available',        '#2596BE', 'Located within this state — accessible within ~25–50 miles of this address.'],
    ['Underserved',      '#B38600', 'In the metro area but not at this specific location.'],
    ['Present',          '#007A3D', 'Operating in this city. Consider co-tenancy or expansion.'],
  ].map(([label, color, desc]) =>
    `<tr>
      <td style="white-space:nowrap"><span style="display:inline-block;width:8px;height:8px;
        border-radius:50%;background:${color};margin-right:6px;vertical-align:middle"></span>
        <strong>${label}</strong></td>
      <td style="color:#646E78">${desc}</td>
    </tr>`
  ).join('');

  const html = `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Void Analysis Report — ${escHtml(addrLabel)}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 12px; color: #282832; padding: 32px; }
  h1 { font-size: 20px; color: #003366; margin-bottom: 4px; }
  h2 { font-size: 13px; color: #003366; margin: 20px 0 8px; border-bottom: 1px solid #D0D8E2; padding-bottom: 4px; text-transform: uppercase; letter-spacing: 0.08em; }
  .meta { color: #646E78; font-size: 11px; margin-bottom: 20px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
  th { text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: #646E78; padding: 6px 8px; border-bottom: 2px solid #D0D8E2; }
  td { padding: 7px 8px; border-bottom: 1px solid #E6EBF0; vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  .inputs-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 24px; margin-bottom: 8px; }
  .input-row { display: flex; gap: 6px; }
  .input-label { color: #646E78; min-width: 80px; }
  .footer { margin-top: 28px; font-size: 10px; color: #B4BEC8; border-top: 1px solid #E6EBF0; padding-top: 10px; }
  @media print { body { padding: 16px; } }
</style>
</head>
<body>
  <h1>Void Analysis — Brand Report</h1>
  <div class="meta">Generated ${now} · Powered by Qloo Taste AI™</div>

  <h2>Inputs</h2>
  <div class="inputs-grid">
    <div class="input-row"><span class="input-label">Address</span><strong>${escHtml(addrLabel)}</strong></div>
    <div class="input-row"><span class="input-label">Radius</span><strong>${radiusMi} mi</strong></div>
    <div class="input-row"><span class="input-label">Signals</span><strong>${escHtml(signals)}</strong></div>
    <div class="input-row"><span class="input-label">Age groups</span><strong>${escHtml(ageGroups)}</strong></div>
  </div>

  <h2>Brand Void Results (${data.brands.length} brands)</h2>
  <table>
    <thead><tr><th>Brand</th><th>Affinity Tier</th><th>Status</th></tr></thead>
    <tbody>${rowsHtml}</tbody>
  </table>

  <h2>How to Interpret Results</h2>
  <table>
    <thead><tr><th>Status</th><th>Meaning</th></tr></thead>
    <tbody>${interpretRows}</tbody>
  </table>

  <div class="footer">Void Analysis · Qloo Taste AI™ · ${now}</div>
</body>
</html>`;

  const win = window.open('', '_blank');
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 600);
}

/* ─── Analyze ───────────────────────────────────────────────────────────── */
analyzeBtn.addEventListener('click', async () => {
  if (!state.location) return;
  hideOverlays();
  const wrap   = loadingEl.querySelector('.progress-bar-wrap');
  const oldBar = wrap.querySelector('.progress-bar');
  const newBar = oldBar.cloneNode(true);
  wrap.replaceChild(newBar, oldBar);
  show(loadingEl);

  const entity_signals = state.signals.filter(s => s.kind === 'entity').map(s => s.id);
  const tag_signals    = state.signals.filter(s => s.kind === 'tag').map(s => s.id);

  try {
    let res, data;

    const loadingMsg = document.getElementById('loading-msg');
    if (loadingMsg) {
      loadingMsg.textContent = state.analysis_type === 'cuisine'
        ? 'Classifying cuisine supply & measuring local affinity… (may take ~30s)'
        : 'Fetching brand affinities & mapping proximity…';
    }

    if (state.analysis_type === 'cuisine') {
      res = await fetch('/api/analyze-cuisine', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          location:      state.location,
          location_mode: 'address',
          radius_m:      radiusMeters(),
        }),
      });
    } else {
      res = await fetch('/api/analyze', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          location:       state.location,
          location_mode:  'address',
          radius_m:       radiusMeters(),
          age_groups:     [...state.age_groups],
          entity_signals,
          tag_signals,
        }),
      });
    }

    data = await res.json();
    hideOverlays();

    if (!res.ok) {
      errorMsg.textContent = data.error || 'Something went wrong.';
      show(errorState);
      return;
    }

    try {
      renderMapPins(data.location, data.brands || []);
    } catch (renderErr) {
      console.error('renderMapPins failed:', renderErr);
    }

    if (state.analysis_type === 'cuisine') {
      renderCuisineResults(data);
    } else {
      renderResults(data);
    }

  } catch (err) {
    hideOverlays();
    console.error('Fetch/parse error:', err);
    errorMsg.textContent = 'Network error — is the server running?';
    show(errorState);
  }
});

/* ─── Init ──────────────────────────────────────────────────────────────── */
initMap();
show(emptyState);
