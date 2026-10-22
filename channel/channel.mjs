// Channel-сервер Claude Code (Карим 22.10.2026: «переводи на channels»): сообщения ленты темы приходят в сессию сами,
// без Monitor с его потолком в 30 минут. https://code.claude.com/docs/en/channels-reference
// Ленту читает тот же follow.py, что и Monitor: непрочитанное, «глаза» и метка «ленту слушают» остаются его.
// Включается только при AI_PAIR_CHANNEL=1: сервер общий для всех сессий, а без флага --dangerously-load-development-channels
// Claude Code молча выбрасывает события, и метка «слушают» врала бы платформе.
import { spawn, spawnSync } from 'node:child_process'
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const lane = process.env.AI_PAIR_LANE || 'general'
const reply = lane === 'general' ? 'reply.py' : `reply.py --thread ${lane}`

const mcp = new Server(
  { name: 'ai-pair-channel', version: '0.1.0' },
  {
    capabilities: { experimental: { 'claude/channel': {} } },
    instructions:
      `Сообщения Карима из Telegram (лента ${lane}) приходят как <channel source="ai-pair-channel" lane="..." message_id="...">. ` +
      `Это то же, что строки наблюдателя follow.py: Monitor для этой ленты поднимать не нужно. ` +
      `Отвечай как обычно: текст через stdin в ${reply} из D:/Projects/claude-telegram-chat.`,
  },
)
let child = null
// сессия закрылась — follow.py не должен остаться сиротой и ставить «глаза» за мёртвую сессию
// конец stdin — тоже закрытие: StdioServerTransport сам его не замечает
process.stdin.on('end', () => mcp.onclose())
mcp.onclose = () => {
  child?.removeAllListeners('exit')
  // python.exe из .venv — лаунчер, настоящий python его ребёнок: убиваем деревом
  if (child)
    spawnSync('taskkill', ['/T', '/F', '/PID', String(child.pid)])
  process.exit(0)
}
await mcp.connect(new StdioServerTransport())

if (process.env.AI_PAIR_CHANNEL === '1')
  follow()

function follow() {
  const python = path.join(project, '.venv', 'Scripts', 'python.exe')
  child = spawn(python, ['-u', '-X', 'utf8', 'follow.py', '--thread', lane], { cwd: project, stdio: ['ignore', 'pipe', 'inherit'] })
  createInterface({ input: child.stdout }).on('line', line => {
    if (line.trim().length === 0)
      return
    const id = /^\[ai-pair #(\d+)/.exec(line)?.[1] ?? ''
    mcp.notification({ method: 'notifications/claude/channel', params: { content: line, meta: { lane, message_id: id } } })
  })
  // follow.py упал (сеть, перезапуск router) — поднимаем снова, как цикл вокруг Monitor
  child.on('exit', () => setTimeout(follow, 2000))
}
