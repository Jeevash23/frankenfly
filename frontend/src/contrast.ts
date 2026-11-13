// WCAG 2 contrast between two sRGB colors written #rgb or #rrggbb. Small text needs at least 4.5:1.

export const AA_SMALL_TEXT = 4.5;

function channels(hex: string): [number, number, number] {
  const digits = hex.trim().replace(/^#/, '');
  const full = digits.length === 3 ? [...digits].map((d) => d + d).join('') : digits;
  if (!/^[0-9a-f]{6}$/i.test(full)) throw new Error(`Not a #rgb or #rrggbb color: ${hex}`);
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255) as [number, number, number];
}

export function luminance(hex: string): number {
  const [r, g, b] = channels(hex).map((c) =>
    c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

// The custom properties declared in a stylesheet's :root rules, e.g. {'--paper': '#fbfbf7'}.
export function rootTokens(css: string): Record<string, string> {
  const tokens: Record<string, string> = {};
  for (const block of css.matchAll(/:root\s*\{([^}]*)\}/g))
    for (const [, name, value] of block[1].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g))
      tokens[name] = value.trim();
  return tokens;
}

// The light tokens (:root), and the dark ones twice: under prefers-color-scheme (when no light
// theme was chosen) and under data-theme="dark" (when the dark theme was chosen).
export function themeTokens(css: string): {
  light: Record<string, string>;
  dark: Record<string, string>;
  darkMedia: Record<string, string>;
} {
  const block = (pattern: RegExp) => {
    const tokens: Record<string, string> = {};
    const body = css.match(pattern)?.[1] ?? '';
    for (const [, name, value] of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g))
      tokens[name] = value.trim();
    return tokens;
  };
  return {
    light: rootTokens(css),
    dark: block(/:root\[data-theme='dark'\]\s*\{([^}]*)\}/),
    darkMedia: block(
      /@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme='light'\]\)\s*\{([^}]*)\}/,
    ),
  };
}
