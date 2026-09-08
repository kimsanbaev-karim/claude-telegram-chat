"""Вопрос с кнопками в тему задачи и ожидание выбора человека.

Хук PreToolUse перехватывает AskUserQuestion, зовёт post_question, ждёт wait_answer
и отдаёт выбор модели через permissionDecisionReason. Нажатие ловит router: он
единственный слушает Telegram, поэтому ответ приходит сюда файлом в answers/.

Свободный текст в теме тоже считается ответом — router кладёт его в тот же файл,
если вопрос ждёт: не всякий ответ укладывается в предложенные варианты.
"""

import json
import time
import uuid
from pathlib import Path

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest

import state

CONNECT_TIMEOUT = 20.0
READ_TIMEOUT = 30.0
POOL_TIMEOUT = 20.0
POLL_SECONDS = 1.0
MAX_OPTION_LENGTH = 60
GENERAL_LANE = "general"


def answers_dir() -> Path:
    path = state.state_dir() / "answers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def answer_path(question_id: str) -> Path:
    return answers_dir() / f"{question_id}.json"


def waiting_path(lane: str) -> Path:
    path = state.state_dir() / "waiting"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{lane}.json"


def make_bot(token: str) -> Bot:
    client = HTTPXRequest(connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT, pool_timeout=POOL_TIMEOUT)
    return Bot(token, request=client)


def keyboard(question_id: str, options: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for index, option in enumerate(options):
        label = option[:MAX_OPTION_LENGTH]
        rows.append([InlineKeyboardButton(label, callback_data=f"{question_id}:{index}")])
    return InlineKeyboardMarkup(rows)


def lane_key(thread: int) -> str:
    """Ключ ленты: у темы это её id, у General — общее имя, как его пишет router."""
    if thread > 0:
        return str(thread)
    return GENERAL_LANE


async def post_question(bot: Bot, chat_id: int, thread: int, question: str, options: list[str]) -> str:
    question_id = uuid.uuid4().hex[:12]
    markup = keyboard(question_id, options)
    topic = thread if thread > 0 else None
    async with bot:
        sent = await bot.send_message(chat_id, question, message_thread_id=topic, reply_markup=markup)
    payload = {"question_id": question_id, "options": options, "message_id": sent.message_id, "chat_id": chat_id}
    waiting_path(lane_key(thread)).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return question_id


def wait_answer(question_id: str, thread: int, timeout_seconds: float) -> str:
    path = answer_path(question_id)
    lane = lane_key(thread)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.is_file() is True:
            answer = json.loads(path.read_text(encoding="utf-8"))["answer"]
            path.unlink()
            waiting_path(lane).unlink(missing_ok=True)
            return answer
        time.sleep(POLL_SECONDS)
    waiting_path(lane).unlink(missing_ok=True)
    raise TimeoutError(f"ответа из Telegram нет {int(timeout_seconds)} с")


def record_answer(question_id: str, answer: str) -> None:
    answer_path(question_id).write_text(json.dumps({"answer": answer}, ensure_ascii=False), encoding="utf-8")


def pending_question(lane: str) -> dict:
    path = waiting_path(lane)
    if path.is_file() is True:
        return json.loads(path.read_text(encoding="utf-8"))
    return {}
