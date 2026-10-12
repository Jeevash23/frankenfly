export function FlyMark({small = false}: {small?: boolean}) {
  return (
    <svg
      viewBox="0 0 40 40"
      width={small ? 20 : 31}
      height={small ? 20 : 31}
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M20 9v24M20 15C7 0 2 18 18 23M20 15C33 0 38 18 22 23M15 22l-7 8m17-8 7 8M15 27l-4 7m14-7 4 7"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <ellipse cx="20" cy="24" rx="3.5" ry="8" fill="currentColor" />
      <circle cx="20" cy="10" r="3" fill="currentColor" />
    </svg>
  );
}
