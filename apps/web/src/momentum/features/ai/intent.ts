/** Does ⌘K input read like an instruction for Mo rather than a search (S3.2.2)? Local and
 * instant: an imperative verb up front, or a phrase that names a change. Search still runs
 * either way; this only decides whether "✦ Ask Mo to do this" leads the list. */
const VERBS =
  'assign|reassign|unassign|move|complete|finish|close|reopen|mark|set|change|rename|reschedule|postpone|push|delay|create|add|make|delete|remove|archive|schedule|plan|split|break|give|hand|update|prioritize|due';

const LEAD = new RegExp(`^(please\\s+)?(${VERBS})\\b`, 'i');
const PHRASE =
  /\b(to me|as (done|complete)|by (next|this|tomorrow|monday|tuesday|wednesday|thursday|friday)|all (the )?(overdue|open|my)|every|each)\b/i;

export function looksLikeInstruction(query: string): boolean {
  const q = query.trim();
  if (q.split(/\s+/).length < 3) return false;
  return LEAD.test(q) || PHRASE.test(q);
}
