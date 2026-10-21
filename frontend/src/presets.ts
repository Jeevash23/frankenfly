import type {Config, PresetInfo, State} from './types.ts';

// Named run configurations (GET/POST/DELETE /api/configs). The server validates again.

export const PRESET_NAME = /^[a-z0-9][a-z0-9_-]{0,47}$/;
export const DESCRIPTION_LIMIT = 200;

// Plain-language problem with a preset name and description, or null.
export function presetProblem(
  name: string,
  description: string,
  presets: PresetInfo[],
): string | null {
  if (!PRESET_NAME.test(name))
    return 'Name it with lowercase letters, digits, - and _ (up to 48 characters), starting with a letter or digit.';
  if (presets.some((p) => p.name === name && p.source === 'shipped'))
    return `${name} is a preset shipped with DigitalFly. Choose another name.`;
  if (description.length > DESCRIPTION_LIMIT)
    return `Keep the description to ${DESCRIPTION_LIMIT} characters.`;
  return null;
}

// What "current settings" saves: the configuration with the interventions in force now. With a
// protocol, scheduled events change interventions, so its initial ones are kept instead.
export function presetConfig(state: Pick<State, 'config' | 'interventions'>): Config {
  return state.config.protocol
    ? state.config
    : {...state.config, initial_interventions: state.interventions};
}

// Whether loading a preset would discard a run in progress (one that has advanced).
export function runInProgress(state: Pick<State, 'status' | 'sample'> | null): boolean {
  return !!state && (state.status === 'running' || (state.sample?.step ?? 0) > 0);
}

// The option text of a preset in the picker.
export function presetOption(preset: PresetInfo): string {
  const source = preset.source === 'local' ? ' (saved here)' : '';
  if (preset.error) return `${preset.name}${source} · unreadable`;
  if (!preset.available) return `${preset.name}${source} · unavailable`;
  return `${preset.name}${source}`;
}
