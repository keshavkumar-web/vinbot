<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { createSession, resetSession, streamChat } from '../api.js'
import { renderMarkdown } from '../markdown.js'

const messages = ref([]) // { role: 'user' | 'assistant', content: string }
const input = ref('')
const sessionId = ref(null)
const isStreaming = ref(false)
const connectionError = ref('')
const scrollEl = ref(null)

const WELCOME = "Hello! I'm Vinbot. How can I help you today?"

onMounted(async () => {
  try {
    sessionId.value = await createSession()
  } catch (err) {
    connectionError.value =
      'Could not reach the backend. Make sure the API is running on port 8000.'
  }
})

async function scrollToBottom() {
  await nextTick()
  const el = scrollEl.value
  if (el) el.scrollTop = el.scrollHeight
}

async function send() {
  const text = input.value.trim()
  if (!text || isStreaming.value || !sessionId.value) return

  connectionError.value = ''
  input.value = ''
  messages.value.push({ role: 'user', content: text })

  // Push an empty assistant message we fill in as tokens arrive.
  messages.value.push({ role: 'assistant', content: '' })
  const index = messages.value.length - 1
  isStreaming.value = true
  scrollToBottom()

  await streamChat(sessionId.value, text, {
    onToken: (token) => {
      messages.value[index].content += token
      scrollToBottom()
    },
    onDone: () => {
      isStreaming.value = false
    },
    onError: (msg) => {
      isStreaming.value = false
      if (!messages.value[index].content) {
        messages.value[index].content = `Sorry, something went wrong: ${msg}`
      }
      connectionError.value = msg
    },
  })
}

async function newChat() {
  if (isStreaming.value || !sessionId.value) return
  try {
    await resetSession(sessionId.value)
  } catch {
    // If reset fails, fall back to a brand-new session.
    try {
      sessionId.value = await createSession()
    } catch {
      connectionError.value = 'Could not start a new chat. Is the backend running?'
      return
    }
  }
  messages.value = []
}

function onKeydown(e) {
  // Enter sends, Shift+Enter inserts a newline.
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <div class="flex flex-col h-full max-w-3xl w-full mx-auto">
    <!-- Header -->
    <header class="bg-brand text-white px-5 py-4 shadow flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="h-9 w-9 rounded-full bg-white/20 flex items-center justify-center text-lg">
          ⚡
        </div>
        <div>
          <h1 class="font-semibold leading-tight">Vinbot</h1>
          <p class="text-xs text-white/70">Enterprise AI Knowledge Assistant</p>
        </div>
      </div>
      <button
        class="text-sm bg-white/15 hover:bg-white/25 transition rounded-md px-3 py-1.5 disabled:opacity-40"
        :disabled="isStreaming"
        @click="newChat"
      >
        New chat
      </button>
    </header>

    <!-- Messages -->
    <div ref="scrollEl" class="flex-1 overflow-y-auto px-4 py-6 space-y-4">
      <!-- Welcome / empty state -->
      <div v-if="messages.length === 0" class="text-center text-slate-500 mt-10 px-6">
        <div class="text-4xl mb-3">💬</div>
        <p>{{ WELCOME }}</p>
      </div>

      <div
        v-for="(m, i) in messages"
        :key="i"
        class="flex"
        :class="m.role === 'user' ? 'justify-end' : 'justify-start'"
      >
        <div
          class="max-w-[80%] rounded-2xl px-4 py-2.5 leading-relaxed shadow-sm"
          :class="[
            m.role === 'user'
              ? 'bg-brand text-white rounded-br-sm whitespace-pre-wrap'
              : 'bg-white text-slate-800 rounded-bl-sm',
          ]"
        >
          <!-- User text is shown verbatim; assistant Markdown is rendered. -->
          <span v-if="m.role === 'user'">{{ m.content }}</span>
          <div
            v-else-if="m.content"
            class="markdown"
            v-html="renderMarkdown(m.content)"
          />
          <span
            v-else-if="isStreaming && m.role === 'assistant'"
            class="inline-flex gap-1 py-1"
          >
            <span class="h-2 w-2 rounded-full bg-slate-400 animate-bounce" />
            <span
              class="h-2 w-2 rounded-full bg-slate-400 animate-bounce"
              style="animation-delay: 0.15s"
            />
            <span
              class="h-2 w-2 rounded-full bg-slate-400 animate-bounce"
              style="animation-delay: 0.3s"
            />
          </span>
        </div>
      </div>
    </div>

    <!-- Connection error banner -->
    <div
      v-if="connectionError"
      class="bg-red-50 text-red-700 text-sm px-4 py-2 border-t border-red-100"
    >
      {{ connectionError }}
    </div>

    <!-- Composer -->
    <div class="border-t border-slate-200 bg-white px-4 py-3">
      <div class="flex items-end gap-2">
        <textarea
          v-model="input"
          rows="1"
          placeholder="Type your question…"
          class="flex-1 resize-none rounded-xl border border-slate-300 px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand max-h-40"
          @keydown="onKeydown"
        />
        <button
          class="bg-brand hover:bg-brand-dark text-white rounded-xl px-5 py-2.5 font-medium transition disabled:opacity-40 disabled:cursor-not-allowed"
          :disabled="isStreaming || !input.trim()"
          @click="send"
        >
          Send
        </button>
      </div>
      <p class="text-[11px] text-slate-400 mt-1.5 px-1">
        Enter to send · Shift+Enter for a new line
      </p>
    </div>
  </div>
</template>

<style scoped>
/* Restore Markdown formatting inside rendered assistant messages
   (Tailwind's preflight removes default list/heading styling). */
.markdown :deep(p) {
  margin: 0 0 0.5rem;
}
.markdown :deep(p:last-child) {
  margin-bottom: 0;
}
.markdown :deep(ul),
.markdown :deep(ol) {
  margin: 0.25rem 0 0.5rem;
  padding-left: 1.25rem;
}
.markdown :deep(ul) {
  list-style: disc;
}
.markdown :deep(ol) {
  list-style: decimal;
}
.markdown :deep(li) {
  margin: 0.15rem 0;
}
.markdown :deep(strong) {
  font-weight: 600;
}
.markdown :deep(h1),
.markdown :deep(h2),
.markdown :deep(h3) {
  font-weight: 600;
  margin: 0.4rem 0;
}
.markdown :deep(code) {
  background: #f1f5f9;
  padding: 0.1rem 0.3rem;
  border-radius: 0.25rem;
  font-size: 0.875em;
}
.markdown :deep(pre) {
  background: #f1f5f9;
  padding: 0.6rem 0.8rem;
  border-radius: 0.5rem;
  overflow-x: auto;
}
.markdown :deep(a) {
  color: #1e4db7;
  text-decoration: underline;
}
</style>
