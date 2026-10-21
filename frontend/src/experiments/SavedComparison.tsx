import {ArrowRight} from 'lucide-react';
import type {Command, SavedRun} from '../types';
import {fmt} from '../format';
import {conditionName} from '../models';

const lineColors = ['#527751', '#ba9152', '#8584b2', '#a26e67'];
// Each overlaid run also gets its own line style, so runs never differ by color alone.
const lineDashes = [undefined, '7 4', '2 3', '9 3 2 3'];

export const runTitle = (run: Pick<SavedRun, 'trial' | 'config'>) =>
  run.trial
    ? conditionName(run.trial.condition) + (run.trial.cell_type ? ` (${run.trial.cell_type})` : '')
    : (run.config.protocol?.name ?? 'Workbench run');

// The selected saved runs: their paths overlaid, and their measured outcomes side by side.
export function SavedComparison({
  details,
  command,
  disabled,
  onLoaded,
}: {
  details: SavedRun[];
  command: Command;
  disabled: boolean;
  onLoaded: () => void;
}) {
  if (!details.length) return null;
  const paths = details.flatMap((d) => d.trajectory ?? []);
  const extent = Math.max(10, ...paths.flatMap((p) => [Math.abs(p[1]), Math.abs(p[2])])) * 1.12;
  return (
    <div className="saved-comparison">
      <section className="panel trajectory-panel">
        <div className="panel-heading">
          <div>
            <h2>Recorded trajectories</h2>
          </div>
          <span className="subtle-label">World coordinates / mm</span>
        </div>
        <svg
          viewBox="0 0 440 340"
          role="img"
          aria-label="Overlay of selected saved fly trajectories"
        >
          <path d="M220 20V310M35 165H405" stroke="#d8dfcf" />
          {details.map((run, i) => (
            <polyline
              key={run.key}
              points={run.trajectory
                ?.map((p) => `${220 + (p[1] / extent) * 150},${165 - (p[2] / extent) * 140}`)
                .join(' ')}
              fill="none"
              stroke={lineColors[i]}
              strokeDasharray={lineDashes[i]}
              strokeWidth="2"
            />
          ))}
          <circle cx="220" cy="165" r="3" fill="#768e61" />
          <text x="220" y="328" textAnchor="middle">
            X ±{fmt(extent, 1)} mm
          </text>
          <text x="15" y="170" transform="rotate(-90,15,170)" textAnchor="middle">
            Y ±{fmt(extent, 1)} mm
          </text>
        </svg>
      </section>
      <section className="comparison-outcomes">
        <h3>Measured outcomes</h3>
        {details.map((run, i) => (
          <div className="outcome" key={run.key}>
            <div>
              <svg width="24" height="8" aria-hidden="true">
                <path
                  d="M1 4H23"
                  stroke={lineColors[i]}
                  strokeWidth="2"
                  strokeDasharray={lineDashes[i]}
                />
              </svg>
              <strong>{runTitle(run)}</strong>
              <span>
                seed {run.config.seed}
                {run.trial?.partial ? ' · partial' : ''}
              </span>
            </div>
            <dl>
              <div>
                <dt>Path</dt>
                <dd>{fmt(run.metrics.path_length_mm)} mm</dd>
              </div>
              <div>
                <dt>Net turn</dt>
                <dd>{fmt(run.metrics.net_turn_deg, 1)}°</dd>
              </div>
              <div>
                <dt>Final target distance</dt>
                <dd>{fmt(run.metrics.target_distance_mm)} mm</dd>
              </div>
            </dl>
            <button
              className="text-button"
              disabled={disabled}
              onClick={async () => {
                const result = await command('reset', run.config);
                if (result) onLoaded();
              }}
            >
              Restore starting configuration <ArrowRight size={12} />
            </button>
          </div>
        ))}
        <p className="microcopy">
          These are descriptive results from the selected runs. Different settings, sensors,
          durations, or target schedules change what a comparison means.
        </p>
      </section>
    </div>
  );
}
