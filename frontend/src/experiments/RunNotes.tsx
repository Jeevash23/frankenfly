import {useId, useState} from 'react';
import {Save} from 'lucide-react';
import type {SavedRun} from '../types';
import {annotationProblem, NOTES_LIMIT, parseTags, TAG_LIMIT} from '../library';

// Edits a saved run's tags and notes (PATCH /api/runs/{key}); metadata.json never changes.
// `save` answers null, or the server's refusal as a sentence.
export function RunNotes({
  run,
  save,
  close,
}: {
  run: Pick<SavedRun, 'key' | 'tags' | 'notes'>;
  save: (tags: string[], notes: string) => Promise<string | null>;
  close: () => void;
}) {
  const id = useId();
  const [tagText, setTagText] = useState((run.tags ?? []).join(', '));
  const [notes, setNotes] = useState(run.notes ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const tags = parseTags(tagText);
  const problem = annotationProblem(tags, notes);
  const submit = async () => {
    if (problem || saving) return;
    setSaving(true);
    setError('');
    const refused = await save(tags, notes);
    setSaving(false);
    if (refused) setError(refused);
    else close();
  };
  return (
    <form
      className="run-notes-form"
      aria-label={`Tags and notes of run ${run.key}`}
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') close();
      }}
    >
      <label className="field-label">
        Tags
        <input
          aria-describedby={`${id}-tags`}
          value={tagText}
          placeholder="e.g. pilot, LC10 sweep"
          autoFocus
          onChange={(e) => setTagText(e.target.value)}
        />
      </label>
      <small id={`${id}-tags`} className="microcopy">
        Separate tags with commas: up to {TAG_LIMIT}, each up to 24 letters, digits, spaces, _ or -.
      </small>
      <label className="field-label">
        Notes
        <textarea
          aria-describedby={`${id}-notes`}
          value={notes}
          rows={3}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
      <small id={`${id}-notes`} className="microcopy">
        {notes.length.toLocaleString('en')} / {NOTES_LIMIT.toLocaleString('en')} characters. Kept in
        the run's annotations.json; its metadata never changes.
      </small>
      {problem && (
        <p className="microcopy" role="status">
          {problem}
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          The tags and notes could not be saved: {error}
        </p>
      )}
      <div className="preset-actions">
        <button className="secondary-button" disabled={!!problem} aria-busy={saving}>
          <Save size={13} />
          Save tags and notes
        </button>
        <button type="button" className="text-button" onClick={close}>
          Cancel
        </button>
      </div>
    </form>
  );
}
