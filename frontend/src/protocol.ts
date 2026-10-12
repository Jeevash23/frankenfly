import type {Protocol, ProtocolEvent} from './types';

export const presets = ['Target reversal', 'Steady target', 'Stimulus pulse'];

export function preset(name: string, seconds: number): Protocol {
  const steps = Math.round(seconds * 100),
    half = Math.floor(steps / 2);
  const stimulus = {x: 12, y: 8, intensity: 1};
  return {
    name,
    duration_steps: steps,
    events:
      name === 'Target reversal'
        ? [{step: half, stimulus: {...stimulus, y: -8}}]
        : name === 'Stimulus pulse'
          ? [
              {step: Math.floor(steps / 3), stimulus: {...stimulus, intensity: 0}},
              {step: Math.floor((steps * 2) / 3), stimulus},
            ]
          : [],
  };
}

// Any manual edit turns a preset into a custom sequence, so a later duration
// change keeps the user's events instead of regenerating the preset.
export function edited(protocol: Protocol, events: ProtocolEvent[]): Protocol {
  return {...protocol, name: 'Custom sequence', events};
}

// Changing the duration rescales a preset but never discards custom events.
export function withDuration(protocol: Protocol, seconds: number): Protocol {
  return presets.includes(protocol.name)
    ? preset(protocol.name, seconds)
    : {...protocol, duration_steps: Math.round(seconds * 100)};
}

// A new change goes halfway between the latest change and the end, on an unused step.
export function freeStep(protocol: Protocol): number {
  const used = new Set(protocol.events.map((e) => e.step));
  const last = Math.max(-1, ...protocol.events.map((e) => e.step));
  const start = Math.floor((last + protocol.duration_steps) / 2);
  for (let step = start; step < protocol.duration_steps; step++) if (!used.has(step)) return step;
  for (let step = start - 1; step >= 0; step--) if (!used.has(step)) return step;
  return 0;
}

// Mirrors the server's schedule rules so problems read as plain sentences.
export function scheduleProblem(protocol: Protocol): string | null {
  const seconds = (steps: number, digits = 2) => (steps / 100).toFixed(digits);
  for (const [i, event] of protocol.events.entries()) {
    if (event.step < 0) return `Change ${i + 1} needs a time of 0 s or later.`;
    if (event.step >= protocol.duration_steps)
      return `Change ${i + 1} at ${seconds(event.step)} s is not before the end (${seconds(protocol.duration_steps, 1)} s). Move it earlier or lengthen the protocol.`;
  }
  const steps = protocol.events.map((e) => e.step);
  if (new Set(steps).size !== steps.length)
    return 'Two stimulus changes happen at the same time. Give each one a different time.';
  return null;
}

// The server requires events in time order; the editor table keeps the user's order.
export function sortedEvents(protocol: Protocol): Protocol {
  return {...protocol, events: [...protocol.events].sort((a, b) => a.step - b.step)};
}
