import type {State} from './types.ts';

// Whether a snapshot replaces the one on screen: always after a server restart, otherwise only a
// newer revision. An unchanged revision is skipped, unless its status or error changed (a failed
// worker marks its last snapshot as an error without a new revision).
export function isNewer(previous: State | null, next: State): boolean {
  if (!previous || previous.instance_id !== next.instance_id) return true;
  if (next.revision !== previous.revision) return next.revision > previous.revision;
  return next.status !== previous.status || next.error !== previous.error;
}

// The eye cameras are rendered again for a new run, a new sample time or a moved target (also while
// paused), so the image is refetched then and not on every snapshot.
export function eyeImageUrl(
  state: Pick<State, 'run_id' | 'vision'> & {config: Pick<State['config'], 'stimulus'>},
): string {
  const {x, y, intensity} = state.config.stimulus;
  const version = [state.run_id, state.vision.sample_time_s ?? '', x, y, intensity].join('_');
  return `/api/eyes?v=${encodeURIComponent(version)}`;
}
