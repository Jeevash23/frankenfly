import {useEffect, useState} from 'react';
import {ArrowDownToLine, Check, Copy, FileText, X} from 'lucide-react';
import {request} from '../api';
import type {MethodsText} from '../api.gen';

// Whether this server can write NWB (pynwb installed), asked once per page load.
let nwbCheck: Promise<boolean> | null = null;
export function nwbAvailable(): Promise<boolean> {
  nwbCheck ??= request<{nwb_export?: boolean}>('GET', '/api/capabilities').then(
    (r) => r.ok && r.data.nwb_export === true,
  );
  return nwbCheck;
}

export function useNwbAvailable(): boolean {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    let live = true;
    void nwbAvailable().then((ok) => live && setAvailable(ok));
    return () => {
      live = false;
    };
  }, []);
  return available;
}

const runPath = (key: string) => `/api/runs/${encodeURIComponent(key)}`;
export const NWB_MISSING =
  'NWB export needs pynwb: install backend/requirements-nwb.lock, then restart DigitalFly';

// A saved run's files: the ZIP, NWB, the provenance manifest and the drafted methods paragraph.
export function RunExports({
  runKey,
  zipUrl,
  methodsOpen,
  toggleMethods,
}: {
  runKey: string;
  zipUrl: string;
  methodsOpen: boolean;
  toggleMethods: () => void;
}) {
  const nwb = useNwbAvailable();
  return (
    <details className="run-exports">
      <summary aria-label={`Export run ${runKey}`} title="Download or describe this run">
        <ArrowDownToLine size={15} />
      </summary>
      <div className="run-exports-menu" role="group" aria-label={`Exports of run ${runKey}`}>
        <a href={zipUrl} download title="All files, with the provenance manifest and methods draft">
          ZIP
        </a>
        {nwb ? (
          <a
            href={`${runPath(runKey)}/nwb`}
            download={`${runKey}.nwb`}
            title="Neurodata Without Borders file"
          >
            NWB
          </a>
        ) : (
          <span className="run-exports-off" title={NWB_MISSING}>
            NWB (needs pynwb)
          </span>
        )}
        <a
          href={`${runPath(runKey)}/manifest`}
          download={`${runKey}-ro-crate-metadata.json`}
          title="RO-Crate provenance manifest (JSON)"
        >
          Manifest
        </a>
        <button
          className="text-button"
          aria-expanded={methodsOpen}
          onClick={toggleMethods}
          title="A methods paragraph drafted from the manifest"
        >
          Methods
        </button>
      </div>
    </details>
  );
}

// A drafted methods paragraph (GET …/methods), with a copy button. `path` is a run's or a comparison's.
export function MethodsDraft({path, close}: {path: string; close: () => void}) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let live = true;
    void request<MethodsText>('GET', path).then((r) => {
      if (!live) return;
      if (r.ok) setText(r.data.markdown);
      else setError(r.error);
    });
    return () => {
      live = false;
    };
  }, [path]);
  const copy = async () => {
    if (text === null) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setError('Copying needs clipboard access; select the text instead.');
    }
  };
  return (
    <div className="methods-draft" role="region" aria-label="Methods draft">
      <div className="methods-draft-head">
        <FileText size={14} />
        <strong>Methods draft</strong>
        <small>from the provenance manifest · check and edit before use</small>
        <button className="text-button" onClick={() => void copy()} disabled={text === null}>
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button className="icon-button" onClick={close} aria-label="Close the methods draft">
          <X size={14} />
        </button>
      </div>
      {error ? (
        <p className="methods-draft-error">{error}</p>
      ) : text === null ? (
        <p>Drafting…</p>
      ) : (
        <pre>{text}</pre>
      )}
    </div>
  );
}
