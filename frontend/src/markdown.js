// Render assistant Markdown to safe HTML.
// The model replies in Markdown (**bold**, numbered lists, etc.); we parse it
// with `marked` and sanitize with DOMPurify so nothing unsafe reaches v-html.

import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({
  breaks: true, // treat single newlines as line breaks (matches chat expectations)
  gfm: true,
})

export function renderMarkdown(text) {
  const raw = marked.parse(text ?? '')
  return DOMPurify.sanitize(raw)
}
