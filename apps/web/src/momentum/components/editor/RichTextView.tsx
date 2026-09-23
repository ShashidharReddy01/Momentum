import type { JSONContent } from '@tiptap/react';
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { cn } from '@/lib/cn';

/**
 * Read-only rendering of rich text (Tiptap JSON) straight to React elements: no editor instance
 * per comment, and only the node/mark types the server allows (core/richtext.py). Unknown nodes
 * render their text only; links keep http(s)/mailto only.
 */
export function RichTextView({
  doc,
  className,
  personName,
}: {
  doc: JSONContent | null | undefined;
  className?: string;
  /** Display name for user mentions (falls back to the label stored in the mention). */
  personName?: (id: string) => string | undefined;
}) {
  if (!doc) return null;
  return <div className={cn('mo-prose mo-prose-compact', className)}>{renderChildren(doc, personName)}</div>;
}

const SAFE = /^(https?:|mailto:)/i;

function renderChildren(node: JSONContent, personName?: (id: string) => string | undefined): ReactNode {
  return (node.content ?? []).map((child, i) => <Node key={i} node={child} personName={personName} />);
}

function Node({ node, personName }: { node: JSONContent; personName?: (id: string) => string | undefined }) {
  const kids = renderChildren(node, personName);
  switch (node.type) {
    case 'paragraph':
      return <p>{kids}</p>;
    case 'heading': {
      const level = node.attrs?.level;
      return level === 1 ? <h1>{kids}</h1> : level === 3 ? <h3>{kids}</h3> : <h2>{kids}</h2>;
    }
    case 'bulletList':
      return <ul>{kids}</ul>;
    case 'orderedList':
      return <ol start={typeof node.attrs?.start === 'number' ? node.attrs.start : undefined}>{kids}</ol>;
    case 'listItem':
      return <li>{kids}</li>;
    case 'taskList':
      return <ul data-type="taskList">{kids}</ul>;
    case 'taskItem': {
      const checked = !!node.attrs?.checked;
      return (
        <li data-checked={checked}>
          <label>
            <input type="checkbox" checked={checked} disabled readOnly />
            <span className="sr-only">{checked ? 'Done' : 'Not done'}</span>
          </label>
          <div>{kids}</div>
        </li>
      );
    }
    case 'codeBlock':
      return (
        <pre>
          <code>{kids}</code>
        </pre>
      );
    case 'blockquote':
      return <blockquote>{kids}</blockquote>;
    case 'hardBreak':
      return <br />;
    case 'horizontalRule':
      return <hr />;
    case 'mention':
      return <Mention node={node} personName={personName} />;
    case 'text':
      return <Text node={node} />;
    default:
      return <>{kids}</>;
  }
}

function Mention({
  node,
  personName,
}: {
  node: JSONContent;
  personName?: (id: string) => string | undefined;
}) {
  const id = String(node.attrs?.id ?? '');
  const kind = node.attrs?.kind ?? 'user';
  const label = String(node.attrs?.label ?? '');
  if (kind === 'task')
    return (
      <Link to={`/task/${id}`} className="mo-mention">
        {label}
      </Link>
    );
  if (kind === 'project')
    return (
      <Link to={`/projects/${id}`} className="mo-mention">
        {label}
      </Link>
    );
  return <span className="mo-mention">@{personName?.(id) ?? label}</span>;
}

function Text({ node }: { node: JSONContent }) {
  let out: ReactNode = node.text ?? '';
  for (const mark of node.marks ?? []) {
    switch (mark.type) {
      case 'bold':
        out = <strong>{out}</strong>;
        break;
      case 'italic':
        out = <em>{out}</em>;
        break;
      case 'strike':
        out = <s>{out}</s>;
        break;
      case 'underline':
        out = <u>{out}</u>;
        break;
      case 'code':
        out = <code>{out}</code>;
        break;
      case 'link': {
        const href = String(mark.attrs?.href ?? '');
        if (SAFE.test(href.trim()))
          out = (
            <a href={href} target="_blank" rel="noopener noreferrer nofollow">
              {out}
            </a>
          );
        break;
      }
    }
  }
  return <>{out}</>;
}
