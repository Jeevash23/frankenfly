import {useState} from 'react';
import {Check, Copy, ShieldCheck} from 'lucide-react';

// A short how-to for the MCP server, from docs/USAGE.md ("Agents and the MCP server").

const SETUP = `./scripts/setup.sh --with mcp
./scripts/start.sh
backend/.venv/bin/python scripts/mcp.py --list-tools`;
const CLAUDE = `claude mcp add digitalfly -- /path/to/frankenfly/backend/.venv/bin/python /path/to/frankenfly/scripts/mcp.py`;
const JSON_ENTRY = `{"mcpServers": {"digitalfly": {
  "command": "/path/to/frankenfly/backend/.venv/bin/python",
  "args": ["/path/to/frankenfly/scripts/mcp.py", "--url", "http://127.0.0.1:8000"]}}}`;
const VFB = `claude mcp add --transport http virtual-fly-brain https://vfb3-mcp.virtualflybrain.org`;

function CodeBlock({label, code}: {label: string; code: string}) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="code-block">
      <pre aria-label={label}>
        <code>{code}</code>
      </pre>
      <button
        type="button"
        className="icon-button"
        aria-label={`Copy: ${label}`}
        title="Copy"
        onClick={() => {
          void navigator.clipboard
            ?.writeText(code)
            .then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            })
            .catch(() => undefined);
        }}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  );
}

export function AgentsPage() {
  return (
    <div className="doc-page">
      <section className="panel doc-section">
        <h2>What an agent can do</h2>
        <p>
          DigitalFly includes an <a href="https://modelcontextprotocol.io">MCP</a> server. An AI
          agent such as Claude Code can then drive this running app through the same local API and
          Python client as your scripts, so the app’s own validation and refusals apply:
        </p>
        <ul>
          <li>
            run, pause and step the live experiment, and change its target, interventions and
            connectome parameters;
          </li>
          <li>start comparisons, toolkit trials and sweeps, and score models on the scorecard;</li>
          <li>query the connectivity explorer;</li>
          <li>read saved runs with their provenance manifest and methods draft, and export NWB.</li>
        </ul>
        <p className="microcopy">
          The app runs one experiment for every client, so this page shows what the agent does.
        </p>
      </section>
      <section className="panel doc-section">
        <h2>Set it up</h2>
        <p>Install the MCP SDK (1–7 MB), start the app, and list the tools:</p>
        <CodeBlock label="Setup commands" code={SETUP} />
        <h3>Add it to Claude Code</h3>
        <p>Use absolute paths, so the server starts from any folder:</p>
        <CodeBlock label="Claude Code command" code={CLAUDE} />
        <p className="microcopy">
          Add <code>--scope project</code> to share it through <code>.mcp.json</code>; append{' '}
          <code>--url http://127.0.0.1:8001</code> for an app on another port.{' '}
          <code>claude mcp list</code> shows whether it connects; the tools appear as{' '}
          <code>mcp__digitalfly__status</code> and so on.
        </p>
        <h3>Other MCP clients</h3>
        <p>Claude Desktop, Cursor and VS Code start the same stdio command:</p>
        <CodeBlock label="MCP client JSON entry" code={JSON_ENTRY} />
      </section>
      <section className="panel doc-section">
        <h2>Next to Virtual Fly Brain</h2>
        <p>
          The hosted Virtual Fly Brain MCP server answers anatomy, cell-type, expression and
          literature questions. With both added, an agent can look a neuron up in VFB, then silence
          or activate it here and measure the behaviour; both use FlyWire names such as DNa02.
        </p>
        <CodeBlock label="Virtual Fly Brain command" code={VFB} />
      </section>
      <section className="panel doc-section">
        <h2>
          <ShieldCheck size={16} aria-hidden /> Safety and the audit log
        </h2>
        <ul>
          <li>
            Read-only tools carry the MCP <code>readOnlyHint</code>. No tool deletes or overwrites
            saved runs, presets or circuits.
          </li>
          <li>
            <code>reset_run</code> and <code>start_comparison</code> refuse while the live run has
            recorded samples unless the call says <code>discard_current: true</code>.
          </li>
          <li>
            Toolkit tools run at most 4 workers, one command at a time, with a timeout; the server
            chooses where results are written.
          </li>
          <li>
            Every call is appended to <code>audit/mcp.jsonl</code> (mode 0600, ignored by git)
            before and after it runs.
          </li>
        </ul>
        <p className="microcopy">
          The full tool list and options are in docs/USAGE.md, under “Agents and the MCP server”.
        </p>
      </section>
    </div>
  );
}
