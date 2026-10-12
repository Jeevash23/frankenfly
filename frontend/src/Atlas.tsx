import {useEffect, useMemo, useRef, useState} from 'react';
import {
  ArrowUpRight,
  Check,
  ChevronDown,
  Eye,
  FileUp,
  Layers3,
  RotateCcw,
  Search,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import type {Command} from './types';
import {fmt} from './format';

type Neuron = {
  id: string;
  cell_type: string;
  points: number[][];
  edges: number[][];
  original_points: number;
  display_points: number;
  cable_length_um: number;
  source_url: string;
};
type Anatomy = {
  sex: string;
  dataset: string;
  release: string;
  space: string;
  units: string;
  coverage: string;
  license: string;
  source_url: string;
  caveat: string;
  neurons: Neuron[];
  surfaces: {name: string; points: number[][]; faces: number[][]}[];
};
const colors: Record<string, string> = {DNa02: '#a9c789', DNp01: '#e3b56d', DNp09: '#aaabde'};

function BrainCanvas({
  data,
  selected,
  type,
  surface,
  includeCord,
}: {
  data: Anatomy;
  selected: string | null;
  type: string;
  surface: boolean;
  includeCord: boolean;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{x: number; y: number} | null>(null);
  const [angle, setAngle] = useState({yaw: -0.12, pitch: 0.13, zoom: 1});
  const [width, setWidth] = useState(700);
  useEffect(() => {
    setAngle({yaw: -0.12, pitch: 0.13, zoom: 1});
  }, [data.sex, includeCord]);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const visibleSurfaces = useMemo(
    () => data.surfaces.filter((s) => includeCord || !s.name.includes('vnc')),
    [data, includeCord],
  );
  const bounds = useMemo(() => {
    const lo = [Infinity, Infinity, Infinity],
      hi = [-Infinity, -Infinity, -Infinity];
    visibleSurfaces.forEach((s) =>
      s.points.forEach((p) =>
        p.forEach((v, i) => {
          lo[i] = Math.min(lo[i], v);
          hi[i] = Math.max(hi[i], v);
        }),
      ),
    );
    return {
      center: lo.map((v, i) => (v + hi[i]) / 2),
      span: Math.max(hi[0] - lo[0], hi[2] - lo[2]),
      size: hi.map((v, i) => v - lo[i]),
      maxZ: hi[2],
    };
  }, [visibleSurfaces]);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const height = 500,
      dpr = Math.min(devicePixelRatio, 2);
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const scale =
      Math.min(
        (width - 90) / bounds.size[0],
        (height - 105) / (bounds.size[2] + bounds.size[1] * 0.25),
      ) * angle.zoom;
    const project = (p: number[]) => {
      const x = p[0] - bounds.center[0],
        y = p[2] - bounds.center[2],
        z = p[1] - bounds.center[1];
      const a = x * Math.cos(angle.yaw) + z * Math.sin(angle.yaw),
        b = -x * Math.sin(angle.yaw) + z * Math.cos(angle.yaw);
      return [
        width / 2 + a * scale,
        height / 2 + (y * Math.cos(angle.pitch) - b * Math.sin(angle.pitch)) * scale,
        y * Math.sin(angle.pitch) + b * Math.cos(angle.pitch),
      ];
    };
    ctx.strokeStyle = '#a6c9b310';
    ctx.lineWidth = 0.5;
    for (let x = 30; x < width; x += 40) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    for (let y = 30; y < height; y += 40) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }
    if (surface) {
      visibleSurfaces.forEach((s) => {
        const stride = Math.max(1, Math.ceil(s.points.length / 7500));
        ctx.fillStyle = '#c0d4b9';
        for (let i = 0; i < s.points.length; i += stride) {
          const p = project(s.points[i]);
          ctx.globalAlpha = 0.1 + Math.max(0, Math.min(0.3, (p[2] / bounds.span + 0.5) * 0.3));
          ctx.fillRect(p[0], p[1], 1.1, 1.1);
        }
      });
    }
    data.neurons
      .filter((n) => type === 'all' || n.cell_type === type)
      .forEach((n) => {
        ctx.globalAlpha = selected && selected !== n.id ? 0.16 : 0.92;
        ctx.strokeStyle = colors[n.cell_type] ?? '#cadabe';
        ctx.lineWidth = selected === n.id ? 1.2 : 0.75;
        ctx.beginPath();
        n.edges.forEach(([a, b]) => {
          if (
            !includeCord &&
            data.sex === 'male' &&
            (n.points[a][2] > bounds.maxZ || n.points[b][2] > bounds.maxZ)
          )
            return;
          const p = project(n.points[a]),
            q = project(n.points[b]);
          ctx.moveTo(p[0], p[1]);
          ctx.lineTo(q[0], q[1]);
        });
        ctx.stroke();
      });
    ctx.globalAlpha = 1;
    ctx.strokeStyle = '#c5d6bf';
    ctx.fillStyle = '#9bae9f';
    ctx.lineWidth = 1;
    const bar = 100 * scale;
    ctx.beginPath();
    ctx.moveTo(26, 464);
    ctx.lineTo(26 + bar, 464);
    ctx.stroke();
    ctx.font = '10px "DM Sans Variable",sans-serif';
    ctx.fillText('100 µm', 26, 483);
    ctx.fillStyle = '#7e9588';
    ctx.fillText('Native coordinates · anatomical reconstruction', width - 270, 483);
  }, [data, selected, type, surface, angle, width, bounds, includeCord, visibleSurfaces]);
  return (
    <div className="brain-view">
      <div className="brain-view-label">
        <span>
          <i />
          ANATOMICAL DATA
        </span>
        <span>{data.space.toUpperCase()} / µm</span>
      </div>
      <canvas
        ref={ref}
        style={{width: '100%', height: 500}}
        tabIndex={0}
        role="img"
        aria-label={`${data.sex} ${data.dataset} anatomical surface and selected neuron skeletons. Drag or use arrow keys to rotate.`}
        onPointerDown={(e) => {
          drag.current = {x: e.clientX, y: e.clientY};
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (!drag.current) return;
          const dx = e.clientX - drag.current.x,
            dy = e.clientY - drag.current.y;
          setAngle((v) => ({...v, yaw: v.yaw + dx * 0.008, pitch: v.pitch + dy * 0.008}));
          drag.current = {x: e.clientX, y: e.clientY};
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
        onKeyDown={(e) => {
          if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
          e.preventDefault();
          setAngle((a) => ({
            ...a,
            yaw: a.yaw + (e.key === 'ArrowLeft' ? -0.1 : e.key === 'ArrowRight' ? 0.1 : 0),
            pitch: a.pitch + (e.key === 'ArrowUp' ? -0.1 : e.key === 'ArrowDown' ? 0.1 : 0),
          }));
        }}
      />
      <div className="brain-tools">
        <span>Drag to rotate</span>
        <button
          onClick={() => setAngle((a) => ({...a, zoom: Math.min(4, a.zoom * 1.2)}))}
          aria-label="Zoom anatomy in"
        >
          <ZoomIn size={16} />
        </button>
        <button
          onClick={() => setAngle((a) => ({...a, zoom: Math.max(0.4, a.zoom / 1.2)}))}
          aria-label="Zoom anatomy out"
        >
          <ZoomOut size={16} />
        </button>
        <button
          onClick={() => setAngle({yaw: -0.12, pitch: 0.13, zoom: 1})}
          aria-label="Reset anatomy camera"
        >
          <RotateCcw size={15} />
        </button>
      </div>
    </div>
  );
}

export function AnatomyPanel() {
  const [sex, setSex] = useState<'female' | 'male'>('female');
  const [cache, setCache] = useState<Partial<Record<'female' | 'male', Anatomy>>>({});
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [type, setType] = useState('all');
  const [surface, setSurface] = useState(true);
  const [includeCord, setIncludeCord] = useState(true);
  const data = cache[sex];
  useEffect(() => {
    setSelected(null);
    setType('all');
    if (data) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError('');
    fetch(`/api/atlas/${sex}`)
      .then((r) => {
        if (!r.ok) throw Error('Anatomy assets could not be loaded.');
        return r.json();
      })
      .then((d) => {
        if (!cancelled) {
          setCache((c) => ({...c, [sex]: d}));
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sex, data]);
  const selectedNeuron = data?.neurons.find((n) => n.id === selected);
  return (
    <>
      <div className="research-intro">
        <div>
          <span className="eyebrow">PUBLISHED ANATOMY</span>
          <h2>Two specimens. A closer look.</h2>
          <p>
            Explore real brain surfaces and selected descending neurons from male and female
            datasets.
          </p>
        </div>
        <div className="sex-selector" aria-label="Anatomical specimen">
          <button className={sex === 'female' ? 'selected' : ''} onClick={() => setSex('female')}>
            <span>♀</span>Female <small>FAFB / FlyWire</small>
          </button>
          <button className={sex === 'male' ? 'selected' : ''} onClick={() => setSex('male')}>
            <span>♂</span>Male <small>MaleCNS v1.0</small>
          </button>
        </div>
      </div>
      <div className="atlas-layout">
        <section className="panel anatomy-panel">
          <div className="panel-heading">
            <div>
              <Layers3 size={16} />
              <h2>{sex === 'female' ? 'Female brain' : 'Male central nervous system'}</h2>
            </div>
            <span className="mini-badge">ANATOMY / 6 NEURONS</span>
          </div>
          {loading || !data ? (
            <div className="brain-placeholder" role="status">
              {error || 'Loading the local anatomical reconstruction…'}
            </div>
          ) : (
            <BrainCanvas
              data={data}
              selected={selected}
              type={type}
              surface={surface}
              includeCord={includeCord}
            />
          )}
          <div className="anatomy-controls">
            <label>
              <input
                type="checkbox"
                checked={surface}
                onChange={(e) => setSurface(e.target.checked)}
              />
              Brain surface
            </label>
            {sex === 'male' && (
              <label>
                <input
                  type="checkbox"
                  checked={includeCord}
                  onChange={(e) => setIncludeCord(e.target.checked)}
                />
                Include nerve cord
              </label>
            )}
            <div className="select-wrap">
              <select
                aria-label="Filter anatomical cell type"
                value={type}
                onChange={(e) => {
                  setType(e.target.value);
                  setSelected(null);
                }}
              >
                <option value="all">All three cell types</option>
                {Object.keys(colors).map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
              <ChevronDown size={13} />
            </div>
          </div>
          <div className="panel-footnote">
            Source geometry, simplified for display · no simulated activity on this anatomy
          </div>
        </section>
        <aside className="atlas-inspector">
          <div className="panel neuron-list">
            <div className="panel-heading">
              <div>
                <h2>Descending neurons</h2>
              </div>
              <button className="text-button" onClick={() => setSelected(null)}>
                Show all
              </button>
            </div>
            {data?.neurons
              .filter((n) => type === 'all' || n.cell_type === type)
              .map((neuron) => (
                <button
                  key={neuron.id}
                  className={`neuron-list-row ${selected === neuron.id ? 'selected' : ''}`}
                  onClick={() => setSelected(neuron.id)}
                >
                  <i style={{background: colors[neuron.cell_type]}} />
                  <span>
                    <strong>{neuron.cell_type}</strong>
                    <small>{neuron.id}</small>
                  </span>
                  <Eye size={14} />
                </button>
              ))}
          </div>
          <div className="panel anatomy-details">
            <span className="eyebrow">
              {selectedNeuron ? 'SELECTED RECONSTRUCTION' : 'DATASET DETAILS'}
            </span>
            <h3>{selectedNeuron?.cell_type ?? data?.dataset ?? 'Anatomy'}</h3>
            <dl>
              {selectedNeuron ? (
                <>
                  <div>
                    <dt>Neuron identifier</dt>
                    <dd className="identifier">{selectedNeuron.id}</dd>
                  </div>
                  <div>
                    <dt>Source skeleton points</dt>
                    <dd>{selectedNeuron.original_points.toLocaleString()}</dd>
                  </div>
                  <div>
                    <dt>Cable length in source</dt>
                    <dd>{fmt(selectedNeuron.cable_length_um, 0)} µm</dd>
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <dt>Specimen sex</dt>
                    <dd>{sex}</dd>
                  </div>
                  <div>
                    <dt>Coverage</dt>
                    <dd>{data?.coverage}</dd>
                  </div>
                  <div>
                    <dt>Loaded connectivity</dt>
                    <dd>Skeletons only</dd>
                  </div>
                </>
              )}
            </dl>
            <a
              href={selectedNeuron?.source_url ?? data?.source_url}
              target="_blank"
              rel="noreferrer"
            >
              View source <ArrowUpRight size={13} />
            </a>
            <p className="microcopy">
              A skeleton describes a neuron's shape. Synapses, physiological weights, and activity
              require additional data.
            </p>
          </div>
        </aside>
      </div>
      <section className="research-note">
        <span className="eyebrow">HOW THIS RELATES TO THE FLY</span>
        <div>
          <h3>Body, wiring, and dynamics are separate models.</h3>
          <p>
            The walking body uses female-derived NeuroMechFly morphology. Selecting male anatomy
            changes this explorer; it does not turn the simulated body into a male or supply a
            sex-specific controller. These specimens also have different coverage and preparation,
            so their shapes alone do not establish sex differences.
          </p>
        </div>
      </section>
      <div className="dataset-links">
        <a href="https://codex.flywire.ai/" target="_blank" rel="noreferrer">
          <strong>FlyWire</strong>
          <span>Female brain</span>
          <ArrowUpRight size={16} />
        </a>
        <a href="https://male-cns.janelia.org/" target="_blank" rel="noreferrer">
          <strong>MaleCNS</strong>
          <span>Male brain & nerve cord</span>
          <ArrowUpRight size={16} />
        </a>
        <a href="https://github.com/htem/BANC-project" target="_blank" rel="noreferrer">
          <strong>BANC</strong>
          <span>Female brain & nerve cord</span>
          <ArrowUpRight size={16} />
        </a>
        <a
          href="https://www.janelia.org/project-team/flyem/manc-connectome"
          target="_blank"
          rel="noreferrer"
        >
          <strong>MANC</strong>
          <span>Male nerve cord</span>
          <ArrowUpRight size={16} />
        </a>
      </div>
    </>
  );
}

type GraphNode = {id: string; label: string; cell_type: string; side: string};
type GraphData = {
  key: string;
  graph: {
    nodes: GraphNode[];
    edges: {pre_id: string; post_id: string; synapse_count: number}[];
    provenance: Record<string, string>;
  };
  summary: {
    nodes: number;
    edges: number;
    synapses: number;
    reciprocal_pairs: number;
    incoming_synapses: Record<string, number>;
    outgoing_synapses: Record<string, number>;
  };
};
export function ConnectivityPanel({command, disabled}: {command: Command; disabled: boolean}) {
  const [data, setData] = useState<GraphData | null>(null);
  const [datasets, setDatasets] = useState<{key: string; provenance: Record<string, string>}[]>([]);
  const [selected, setSelected] = useState('');
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [threshold, setThreshold] = useState(1);
  const refresh = () =>
    fetch('/api/connectivity')
      .then((r) => {
        if (!r.ok) throw Error('Connectivity library is unavailable.');
        return r.json();
      })
      .then((d) => setDatasets(d.datasets))
      .catch((e) => setError(e.message));
  useEffect(() => {
    void refresh();
  }, []);
  const importFile = async (file: File) => {
    try {
      setError('');
      if (file.size > 2_000_000) throw Error('Choose a JSON subset smaller than 2 MB.');
      const json = JSON.parse(await file.text());
      const result = await command('connectivity/import', json);
      if (result) {
        setData(result);
        setSelected('');
        void refresh();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to read this JSON file.');
    }
  };
  const load = async (key: string) => {
    try {
      const response = await fetch(`/api/connectivity/${key}`);
      if (!response.ok) throw Error('Could not load the selected dataset.');
      setData(await response.json());
      setSelected('');
      setError('');
    } catch (e) {
      setError(String(e));
    }
  };
  const nodes = data?.graph.nodes ?? [];
  const visible = nodes.filter((n) =>
    [n.id, n.label, n.cell_type].some((v) => v.toLowerCase().includes(search.toLowerCase())),
  );
  const selectedNode = nodes.find((n) => n.id === selected);
  const edges = (data?.graph.edges ?? []).filter(
    (e) =>
      e.synapse_count >= threshold &&
      (!selected || e.pre_id === selected || e.post_id === selected),
  );
  const positions = Object.fromEntries(
    nodes.map((node, i) => {
      const theta = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
      return [node.id, [300 + 220 * Math.cos(theta), 260 + 210 * Math.sin(theta)]];
    }),
  );
  return (
    <>
      <div className="research-intro">
        <div>
          <span className="eyebrow">CONNECTIVITY EXPLORER</span>
          <h2>Bring a circuit into focus.</h2>
          <p>
            Import a bounded graph, inspect its connections, and retain every source identifier.
          </p>
        </div>
        <label className={`primary-button upload-button ${disabled ? 'disabled' : ''}`}>
          <FileUp size={16} />
          Import connectivity JSON
          <input
            aria-label="Import connectivity JSON"
            type="file"
            accept=".json,application/json"
            disabled={disabled}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void importFile(f);
              e.target.value = '';
            }}
          />
        </label>
      </div>
      {error && (
        <p className="alert error-alert" role="alert">
          {error}
        </p>
      )}
      <div className="connectivity-toolbar">
        <div className="select-wrap">
          <select
            aria-label="Saved connectivity dataset"
            value={data?.key ?? ''}
            onChange={(e) => void load(e.target.value)}
          >
            <option value="" disabled>
              Choose a locally saved dataset
            </option>
            {datasets.map((d) => (
              <option key={d.key} value={d.key}>
                {d.provenance.dataset} · {d.provenance.sex} · {d.provenance.release}
              </option>
            ))}
          </select>
          <ChevronDown size={13} />
        </div>
        <a href="/api/examples/connectivity" download="connectivity-example.json">
          Download format example <ArrowUpRight size={13} />
        </a>
      </div>
      {!data ? (
        <section className="panel empty-research">
          <Layers3 size={30} />
          <h3>A place for real wiring.</h3>
          <p>
            Import up to 300 neurons and 3,000 directed connections from a documented dataset.
            Include specimen sex, release, license, and the subset's coverage.
          </p>
          <p>
            Synapse counts stay structural measurements. Imported graphs are explored here; the
            walking circuit stays independently defined.
          </p>
          <span className="mini-badge">No biological wiring imported</span>
        </section>
      ) : (
        <>
          <div className="graph-provenance">
            <Check size={16} />
            <span>
              <strong>{data.graph.provenance.dataset}</strong> · {data.graph.provenance.release} ·{' '}
              {data.graph.provenance.sex} ·{' '}
              {data.graph.provenance.kind === 'synthetic'
                ? 'SYNTHETIC DATA'
                : 'User-supplied biological provenance'}
            </span>
            <a href={data.graph.provenance.source_url} target="_blank" rel="noreferrer">
              Source <ArrowUpRight size={13} />
            </a>
          </div>
          <div className="atlas-layout">
            <section className="panel">
              <div className="metric-row">
                {[
                  ['Neurons', data.summary.nodes],
                  ['Connections', data.summary.edges],
                  ['Synapses', data.summary.synapses],
                  ['Reciprocal pairs', data.summary.reciprocal_pairs],
                ].map(([label, value]) => (
                  <div key={label}>
                    <span>{label}</span>
                    <strong>{Number(value).toLocaleString()}</strong>
                  </div>
                ))}
              </div>
              <svg
                viewBox="0 0 600 520"
                className="imported-graph"
                role="group"
                aria-label="Imported directed connectivity graph in a circular, non-anatomical layout"
              >
                <defs>
                  <marker
                    id="graph-arrow"
                    markerWidth="6"
                    markerHeight="6"
                    refX="5"
                    refY="3"
                    orient="auto"
                  >
                    <path d="M0 0L6 3L0 6Z" fill="#748c68" />
                  </marker>
                </defs>
                {edges.map((e) => {
                  const a = positions[e.pre_id],
                    b = positions[e.post_id];
                  if (e.pre_id === e.post_id)
                    return (
                      <circle
                        key={`${e.pre_id}-${e.post_id}`}
                        cx={a[0] + 8}
                        cy={a[1] - 8}
                        r="12"
                        fill="none"
                        stroke="#9ba88c"
                      />
                    );
                  return (
                    <line
                      key={`${e.pre_id}-${e.post_id}`}
                      x1={a[0]}
                      y1={a[1]}
                      x2={b[0] + (a[0] - b[0]) * 0.035}
                      y2={b[1] + (a[1] - b[1]) * 0.035}
                      stroke="#718d69"
                      opacity={selected ? 0.7 : 0.18}
                      strokeWidth={Math.min(3, 1 + Math.log10(e.synapse_count))}
                      markerEnd="url(#graph-arrow)"
                    >
                      <title>
                        {e.pre_id} → {e.post_id}: {e.synapse_count} synapses
                      </title>
                    </line>
                  );
                })}
                {nodes.map((n) => (
                  <g
                    key={n.id}
                    onClick={() => setSelected(n.id)}
                    role="button"
                    tabIndex={0}
                    aria-label={`Inspect neuron ${n.label}`}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') setSelected(n.id);
                    }}
                  >
                    <circle
                      cx={positions[n.id][0]}
                      cy={positions[n.id][1]}
                      r={selected === n.id ? 8 : 4}
                      fill={selected === n.id ? '#b58c4e' : '#53764e'}
                    />
                    {(nodes.length < 25 || selected === n.id) && (
                      <text x={positions[n.id][0]} y={positions[n.id][1] - 12} textAnchor="middle">
                        {n.label}
                      </text>
                    )}
                  </g>
                ))}
              </svg>
              <div className="anatomy-controls">
                <label>
                  Minimum synapses{' '}
                  <input
                    aria-label="Minimum synapse count"
                    type="number"
                    min="1"
                    max="100000000"
                    value={threshold}
                    onChange={(e) => setThreshold(Math.max(1, Number(e.target.value) || 1))}
                  />
                </label>
                <button className="text-button" onClick={() => setSelected('')}>
                  Show every connection
                </button>
              </div>
              <div className="panel-footnote">
                Circular graph layout · positions are not anatomical
              </div>
            </section>
            <aside className="atlas-inspector">
              <div className="panel graph-nodes">
                <label className="search-field">
                  <Search size={14} />
                  <input
                    aria-label="Search imported neurons"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Find a neuron or cell type"
                  />
                </label>
                <div className="graph-node-list">
                  {visible.map((n) => (
                    <button
                      key={n.id}
                      className={selected === n.id ? 'selected' : ''}
                      onClick={() => setSelected(n.id)}
                    >
                      <strong>{n.label}</strong>
                      <small>{n.id}</small>
                    </button>
                  ))}
                </div>
              </div>
              <section className="panel anatomy-details">
                <span className="eyebrow">
                  {selectedNode ? 'SELECTED NEURON' : 'SUBSET COVERAGE'}
                </span>
                <h3>{selectedNode?.label ?? 'Data provenance'}</h3>
                {selectedNode ? (
                  <dl>
                    <div>
                      <dt>Incoming synapses</dt>
                      <dd>{data.summary.incoming_synapses[selectedNode.id]}</dd>
                    </div>
                    <div>
                      <dt>Outgoing synapses</dt>
                      <dd>{data.summary.outgoing_synapses[selectedNode.id]}</dd>
                    </div>
                    <div>
                      <dt>Cell type</dt>
                      <dd>{selectedNode.cell_type}</dd>
                    </div>
                  </dl>
                ) : (
                  <p>{data.graph.provenance.coverage}</p>
                )}
                <p className="microcopy">{data.graph.provenance.weight_assumption}</p>
                <p className="microcopy">License: {data.graph.provenance.license}</p>
              </section>
            </aside>
          </div>
        </>
      )}
    </>
  );
}
