// Wire formats an AI channel can speak; the backend builds the request path
// from the format, so the address only needs the host (a trailing /v1 is fine).
export const AI_API_FORMATS = Object.freeze([
  { value: 'openai', label: 'OpenAI 格式', endpoint: '/v1/chat/completions', urlPlaceholder: 'https://api.openai.com/v1', modelPlaceholder: 'gpt-4o-mini' },
  { value: 'anthropic', label: 'Anthropic 格式', endpoint: '/v1/messages', urlPlaceholder: 'https://api.anthropic.com', modelPlaceholder: 'claude-opus-5-5' },
  { value: 'gemini', label: 'Gemini 格式', endpoint: '/v1beta/models/模型名:streamGenerateContent', urlPlaceholder: 'https://generativelanguage.googleapis.com', modelPlaceholder: 'gemini-3-flash' },
])

export function aiFormatInfo(value) {
  return AI_API_FORMATS.find((item) => item.value === value) || AI_API_FORMATS[0]
}
