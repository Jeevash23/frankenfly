import {useEffect, useState} from 'react';
import {Puzzle} from 'lucide-react';
import {request} from '../api';
import {contributionSummary, contributionNames, type PluginListing} from '../plugins';

// A short section: plugins add sensors, stimulus programs, scorecard tests, metrics and toolkit
// commands, and run only when named, so the defaults never change.
export function PluginsPanel() {
  const [listing, setListing] = useState<PluginListing | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    void request<PluginListing>('GET', '/api/plugins').then((r) => {
      if (cancelled) return;
      if (!r.ok) return setError(r.status === 404 ? '' : `Plugins: ${r.error}`);
      setListing(r.data);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  if (!listing) return error ? <p className="microcopy">{error}</p> : null;
  return (
    <section className="panel plugins-panel" aria-labelledby="plugins-heading">
      <div className="panel-heading">
        <div>
          <h2 id="plugins-heading">Plugins</h2>
        </div>
        <span className="subtle-label">Plugin API {listing.api_version}</span>
      </div>
      {listing.plugins.length === 0 ? (
        <p className="microcopy plugins-empty">
          {listing.enabled
            ? 'No plugins installed. Plugins add sensors, stimulus programs, scorecard tests, metrics and toolkit commands; see docs/PLUGINS.md.'
            : 'Plugins are turned off (DIGITALFLY_PLUGINS=0).'}
        </p>
      ) : (
        <ul>
          {listing.plugins.map((plugin) => (
            <li
              key={`${plugin.name}-${plugin.entry_point}`}
              className={`plugin-row ${plugin.status}`}
            >
              <Puzzle size={14} />
              <span className="plugin-label">
                <strong>{plugin.title}</strong> <code>{plugin.name}</code>
                {plugin.version && <> · {plugin.version}</>}
                <small>
                  {plugin.status === 'ok'
                    ? `Adds ${contributionSummary(plugin)}.`
                    : `Not loaded: ${plugin.error ?? plugin.status}`}
                </small>
                {plugin.status === 'ok' && (
                  <small className="plugin-contributions">
                    {contributionNames(plugin).join(' · ')}
                  </small>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="microcopy plugins-note">
        Plugin code runs only when a run, scorecard or command names it; runs record the plugins
        they used in their provenance manifest.
      </p>
    </section>
  );
}
