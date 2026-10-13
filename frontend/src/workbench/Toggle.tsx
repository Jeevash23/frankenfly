export function Toggle({
  label,
  subtitle,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  subtitle: string;
  checked: boolean;
  onChange: () => void;
  disabled: boolean;
}) {
  return (
    <label className="toggle-row">
      <span>
        <span className="toggle-label">{label}</span>
        <small>{subtitle}</small>
      </span>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
      />
      <span className="toggle-track" />
    </label>
  );
}
