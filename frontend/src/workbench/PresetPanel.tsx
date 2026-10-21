import {useCallback, useEffect, useState} from 'react';
import {Bookmark, ChevronDown, Save, Trash2} from 'lucide-react';
import type {Command, Config, PresetInfo, State} from '../types';
import {request} from '../api';
import {
  DESCRIPTION_LIMIT,
  presetConfig,
  presetOption,
  presetProblem,
  runInProgress,
} from '../presets';

// Named configurations: load one (a fresh run with its configuration), save the current settings
// under a name, delete presets saved on this computer. The shipped presets cannot be changed.
export function PresetPanel({
  state,
  command,
  disabled,
}: {
  state: State | null;
  command: Command;
  disabled: boolean;
}) {
  const [presets, setPresets] = useState<PresetInfo[]>([]);
  const [listError, setListError] = useState('');
  const [chosen, setChosen] = useState('');
  // 'load' or 'delete' while that step waits for a second click.
  const [confirming, setConfirming] = useState<'load' | 'delete' | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{error: boolean; text: string} | null>(null);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const list = useCallback(async () => {
    const r = await request<{configs: PresetInfo[]}>('GET', '/api/configs');
    if (r.ok) {
      setPresets(r.data.configs);
      setListError('');
    } else
      setListError(
        r.status === 404 ? 'This server version has no presets.' : `Presets: ${r.error}`,
      );
  }, []);
  useEffect(() => {
    void list();
  }, [list]);
  const selected = presets.find((p) => p.name === chosen) ?? null;
  const unavailable = presets.filter((p) => !p.available);
  const problem = presetProblem(name, description, presets);
  const replacing = presets.some((p) => p.name === name && p.source === 'local');

  const load = async () => {
    if (!selected?.available || busy) return;
    if (runInProgress(state) && confirming !== 'load') return setConfirming('load');
    setConfirming(null);
    setBusy(true);
    setMessage(null);
    const r = await request<{config: Config}>(
      'GET',
      `/api/configs/${encodeURIComponent(selected.name)}`,
    );
    if (!r.ok) setMessage({error: true, text: r.error});
    else if (await command('reset', r.data.config))
      setMessage({error: false, text: `Loaded ${selected.name}. The run starts paused.`});
    setBusy(false);
  };
  const save = async () => {
    if (!state || problem || busy) return;
    setBusy(true);
    setMessage(null);
    const r = await request<PresetInfo>('POST', '/api/configs', {
      name,
      description: description.trim(),
      config: presetConfig(state),
    });
    setBusy(false);
    if (!r.ok) return setMessage({error: true, text: r.error});
    setMessage({error: false, text: `Saved the current settings as ${name}.`});
    setSaving(false);
    setChosen(name);
    setName('');
    setDescription('');
    void list();
  };
  const remove = async () => {
    if (selected?.source !== 'local' || busy) return;
    if (confirming !== 'delete') return setConfirming('delete');
    setConfirming(null);
    setBusy(true);
    const r = await request('DELETE', `/api/configs/${encodeURIComponent(selected.name)}`);
    setBusy(false);
    if (!r.ok && r.status !== 404) return setMessage({error: true, text: r.error});
    setMessage({error: false, text: `Deleted ${selected.name}.`});
    setChosen('');
    void list();
  };

  return (
    <section className="preset-panel panel">
      <div className="panel-heading">
        <div>
          <Bookmark size={16} />
          <h2>Presets</h2>
        </div>
        <span className="mini-badge">CONFIGS/</span>
      </div>
      <div className="inspector-body">
        {listError ? (
          <p className="microcopy">{listError}</p>
        ) : (
          <>
            <label className="field-label">
              Named configuration
              <div className="select-wrap">
                <select
                  value={chosen}
                  disabled={disabled || !presets.length}
                  onChange={(e) => {
                    setChosen(e.target.value);
                    setConfirming(null);
                    setMessage(null);
                  }}
                >
                  <option value="">
                    {presets.length ? 'Choose a preset' : 'Loading presets…'}
                  </option>
                  {presets.map((p) => (
                    <option
                      key={p.name}
                      value={p.name}
                      disabled={!p.available}
                      title={p.error ?? p.reason ?? p.description}
                    >
                      {presetOption(p)}
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} />
              </div>
            </label>
            {selected && <p className="microcopy">{selected.description}</p>}
            {confirming === 'load' ? (
              <div className="confirm-row" role="group" aria-label="Replace the current run?">
                <span>Loading starts a fresh run; the current one is lost unless exported.</span>
                <button className="secondary-button" autoFocus onClick={() => void load()}>
                  Load {selected?.name}
                </button>
                <button className="text-button" onClick={() => setConfirming(null)}>
                  Keep the run
                </button>
              </div>
            ) : confirming === 'delete' ? (
              <div className="confirm-row" role="group" aria-label={`Delete ${selected?.name}?`}>
                <span>Delete the preset {selected?.name} from configs/local/?</span>
                <button className="secondary-button" autoFocus onClick={() => void remove()}>
                  Delete
                </button>
                <button className="text-button" onClick={() => setConfirming(null)}>
                  Keep it
                </button>
              </div>
            ) : (
              <div className="preset-actions">
                <button
                  className="secondary-button"
                  disabled={disabled || !selected?.available}
                  aria-busy={busy}
                  onClick={() => void load()}
                >
                  Load preset
                </button>
                {selected?.source === 'local' && (
                  <button
                    className="icon-button"
                    disabled={disabled}
                    aria-label={`Delete preset ${selected.name}`}
                    title="Delete this preset saved on this computer"
                    onClick={() => void remove()}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            )}
            {unavailable.length > 0 && (
              <details className="preset-unavailable">
                <summary>
                  {unavailable.length} {unavailable.length === 1 ? 'preset' : 'presets'} unavailable
                  here
                </summary>
                <ul>
                  {unavailable.map((p) => (
                    <li key={p.name}>
                      <strong>{p.name}</strong>: {p.error ?? p.reason}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {saving ? (
              <form
                className="preset-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void save();
                }}
              >
                <label className="field-label">
                  Preset name
                  <input
                    value={name}
                    maxLength={48}
                    placeholder="e.g. steering-seed-7"
                    autoFocus
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <label className="field-label">
                  Description (optional)
                  <input
                    value={description}
                    maxLength={DESCRIPTION_LIMIT}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </label>
                {name && problem && (
                  <p className="microcopy" role="status">
                    {problem}
                  </p>
                )}
                {replacing && !problem && (
                  <p className="microcopy">Replaces the preset {name} saved on this computer.</p>
                )}
                <div className="preset-actions">
                  <button
                    className="secondary-button"
                    disabled={disabled || !!problem || !state}
                    aria-busy={busy}
                  >
                    <Save size={13} />
                    {replacing ? 'Replace preset' : 'Save preset'}
                  </button>
                  <button type="button" className="text-button" onClick={() => setSaving(false)}>
                    Cancel
                  </button>
                </div>
                <p className="microcopy">
                  Saves the configuration with the interventions in force now (with a protocol, its
                  starting ones) to configs/local/.
                </p>
              </form>
            ) : (
              <button
                className="text-button"
                disabled={disabled || !state}
                onClick={() => {
                  setSaving(true);
                  setMessage(null);
                }}
              >
                Save current settings as preset
              </button>
            )}
          </>
        )}
        {message && (
          <p
            className={message.error ? 'form-error' : 'microcopy'}
            role={message.error ? 'alert' : 'status'}
          >
            {message.text}
          </p>
        )}
      </div>
    </section>
  );
}
