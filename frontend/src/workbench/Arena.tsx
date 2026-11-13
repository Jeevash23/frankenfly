import type {State, StimulusChange} from '../types';
import {nudgeTarget, targetFromPoint} from '../plot';

export function Arena({
  state,
  compact = false,
  onTarget,
  disabled,
}: {
  state: State | null;
  compact?: boolean;
  onTarget: (change: StimulusChange) => void;
  disabled: boolean;
}) {
  const pose = state?.sample?.pose;
  const target = state?.config.stimulus;
  const extent = 40;
  const point = (x: number, y: number) => [150 + (x / extent) * 150, 150 - (y / extent) * 150];
  const [tx, ty] = target ? point(target.x, target.y) : [150, 150];
  const [fx, fy] = pose ? point(pose.x, pose.y) : [150, 150];
  return (
    <svg
      className={`arena ${compact ? 'compact' : ''}`}
      viewBox="0 0 300 300"
      role="application"
      tabIndex={disabled ? -1 : 0}
      aria-label={`Arena map, coordinates in millimeters${target ? `: target at (${target.x}, ${target.y})` : ''}. Click to place the target, or use the arrow keys to move it by 1 mm (5 mm with Shift).`}
      onKeyDown={(event) => {
        if (disabled || !target || !nudgeTarget(target, event.key, event.shiftKey)) return;
        event.preventDefault();
        // Built on the newest target sent, so quick presses all count.
        onTarget((current) => nudgeTarget(current, event.key, event.shiftKey) ?? {});
      }}
      onPointerDown={(event) => {
        if (disabled) return;
        // SVG's square is letterboxed in the element; use its actual square drawing area.
        const r = event.currentTarget.getBoundingClientRect();
        const side = Math.min(r.width, r.height);
        onTarget(
          targetFromPoint(
            event.clientX,
            event.clientY,
            {
              left: r.left + (r.width - side) / 2,
              top: r.top + (r.height - side) / 2,
              width: side,
              height: side,
            },
            extent,
          ),
        );
      }}
    >
      <defs>
        <pattern
          id={compact ? 'grid-mini' : 'grid-main'}
          width="37.5"
          height="37.5"
          patternUnits="userSpaceOnUse"
        >
          <path d="M37.5 0H0V37.5" fill="none" stroke="var(--chart-grid)" strokeWidth=".7" />
        </pattern>
      </defs>
      <rect width="300" height="300" fill={`url(#${compact ? 'grid-mini' : 'grid-main'})`} />
      <path d="M150 0V300M0 150H300" stroke="var(--chart-axis)" strokeWidth=".7" />
      <text x="286" y="143" className="map-axis">
        x
      </text>
      <text x="156" y="13" className="map-axis">
        y
      </text>
      <polyline
        points={state?.trail.map((p) => point(p[0], p[1]).join(',')).join(' ')}
        fill="none"
        stroke="var(--series-a)"
        strokeOpacity=".5"
        strokeWidth="1.2"
      />
      {pose && target && (
        <line
          x1={fx}
          y1={fy}
          x2={tx}
          y2={ty}
          stroke="#aaa67e"
          strokeDasharray="3 4"
          strokeWidth=".8"
        />
      )}
      {target && (
        <g transform={`translate(${tx},${ty})`}>
          <circle r="14" fill="#bd9956" opacity=".1" />
          <circle r="7" fill="none" stroke="#af8645" strokeWidth="1" />
          <circle r="2" fill="#af8645" />
          <path d="M-11 0h5M6 0h5M0-11v5M0 6v5" stroke="#af8645" strokeWidth=".8" />
        </g>
      )}
      {pose && (
        <g transform={`translate(${fx},${fy}) rotate(${(-pose.yaw * 180) / Math.PI})`}>
          <path d="M8 0L-5-4L-2 0L-5 4Z" fill="var(--ink-strong)" />
          {!compact &&
            pose.legs.map((leg, i) => (
              <polyline
                key={i}
                points={leg
                  .map((p) => {
                    // Convert measured world joint positions into the glyph's local frame.
                    const dx = ((p[0] - pose.x) / extent) * 150;
                    const dy = (-(p[1] - pose.y) / extent) * 150;
                    return `${dx * Math.cos(pose.yaw) - dy * Math.sin(pose.yaw)},${dx * Math.sin(pose.yaw) + dy * Math.cos(pose.yaw)}`;
                  })
                  .join(' ')}
                fill="none"
                stroke="var(--ink-strong)"
                strokeWidth=".8"
              />
            ))}
        </g>
      )}
      <text x="8" y="291" className="map-axis">
        −40
      </text>
      <text x="272" y="291" className="map-axis">
        40 mm
      </text>
    </svg>
  );
}
