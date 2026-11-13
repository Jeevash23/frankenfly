// Applies the stored light or dark theme before the first paint, so a reload never flashes the
// other one (src/theme.ts manages the choice afterwards). A file, not an inline script, because
// the server's Content-Security-Policy allows scripts from 'self' only.
try {
  var theme = localStorage.getItem('digitalfly.theme');
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
} catch (e) {
  // Storage unavailable: follow the system theme.
}
