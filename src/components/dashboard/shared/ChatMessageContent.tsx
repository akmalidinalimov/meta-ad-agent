import { Fragment, type ReactNode } from 'react'

// A line is a bullet when it opens with -, •, or * followed by whitespace.
const BULLET_RE = /^\s*[-•*]\s+/

// Split one line of text into plain text and **bold** runs. An unmatched or
// stray asterisk is left as literal text, so malformed output never breaks.
function renderInline(text: string): ReactNode[] {
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .filter((part) => part !== '')
    .map((part, index) =>
      /^\*\*[^*]+\*\*$/.test(part) ? (
        <strong key={index}>{part.slice(2, -2)}</strong>
      ) : (
        <Fragment key={index}>{part}</Fragment>
      ),
    )
}

/**
 * Render an agent/chat answer as readable HTML without a markdown dependency.
 *
 * - blank line(s) separate blocks (rendered as separate <p> / <ul>)
 * - a block whose every line is a bullet becomes a <ul>
 * - other blocks become a <p>, preserving single newlines as <br> so numbered
 *   lists and line-per-item template output stay structured (not run together)
 * - inline **bold** becomes <strong>
 *
 * Output is React elements only (no raw HTML injection), so LLM-authored text
 * cannot inject markup.
 */
export function ChatMessageContent({ content }: { content: string }) {
  const text = content.replace(/\r\n/g, '\n').trim()
  if (!text) return null

  const blocks = text.split(/\n{2,}/)

  return (
    <div className="chat-rich">
      {blocks.map((block, blockIndex) => {
        const lines = block.split('\n')
        const isList = lines.every((line) => BULLET_RE.test(line))

        if (isList) {
          return (
            <ul key={blockIndex}>
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>{renderInline(line.replace(BULLET_RE, ''))}</li>
              ))}
            </ul>
          )
        }

        return (
          <p key={blockIndex}>
            {lines.map((line, lineIndex) => (
              <Fragment key={lineIndex}>
                {lineIndex > 0 && <br />}
                {renderInline(line)}
              </Fragment>
            ))}
          </p>
        )
      })}
    </div>
  )
}
