from __future__ import annotations

import re
import logging
import i18n  # type: ignore

from typing import Optional
from datetime import time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.future import select

from telegram import Update, InlineKeyboardMarkup, CallbackQuery, Poll
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    ContextTypes,
    CommandHandler,
    TypeHandler,
    PollHandler,
    CallbackQueryHandler,
    MessageHandler,
    CallbackContext,
    filters,
)
from telegram.constants import ParseMode

from gunther import DB_CONNECT_TIMEOUT_SECS, TIMEZONE_PATTERN
from gunther.misc import init_i18n, write_to_db, rate_limit, langs_keyboard, yes_no_keyboard, shift_time, return_time
from gunther.models import System, User, Langs
from gunther.translator import Translator
from gunther.quiz_machine import QuizMachine, Question


logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class GuntherBot:
    __slots__ = (
        '_dbs',
        '_sys',
        '_app',
        '_users',
        '_quizers',
        '_traslator',
    )

    INIT, NEXT, AWAIT_FOR_TZ, AWAIT_FOR_QN, QUIZ = range(5)

    def __init__(self, token: str, db_url: str, cache_url: str, trans_path: str, api_url: str) -> None:
        self._users: dict[int, User] = {}
        self._quizers: dict[int, QuizMachine] = {}

        try:
            if api_url:
                self._app = Application.builder().base_url(api_url).token(token).build()
            else:
                self._app = Application.builder().token(token).build()
        except Exception:
            logger.error('Connection to Telegram API is failed.')
            exit(1)

        if not self._app.job_queue:
            logger.error('Application scheduler is absent, check apscheduler package.')
            exit(1)

        try:
            self._dbs = Session(create_engine(db_url, connect_args={'connect_timeout': DB_CONNECT_TIMEOUT_SECS}))
            self._sys = self._dbs.execute(select(System).where(System.id == 0)).scalar_one()
        except Exception:
            logger.error('Connection to DB is failed.')
            exit(1)

        self._traslator = Translator(self._dbs, cache_url)

        init_i18n(trans_path)

        self._app.add_error_handler(self.error_handler)
        self._app.add_handler(CommandHandler('start', self.command_start))
        self._app.add_handler(CommandHandler('config', self.command_config))
        self._app.add_handler(CommandHandler('quiz', self.command_quiz_mode))
        self._app.add_handler(CommandHandler('go', self.command_go))
        self._app.add_handler(CommandHandler('switch', self.command_switch))
        self._app.add_handler(CommandHandler('top10', self.command_top10))
        self._app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.text_message_handler))
        self._app.add_handler(MessageHandler(filters.COMMAND, self.unknown_command_handler))
        self._app.add_handler(CallbackQueryHandler(self.confirm_native_lang, pattern=r'^native_lang_[a-z]+$'))
        self._app.add_handler(CallbackQueryHandler(self.confirm_trans_lang, pattern=r'^trans_lang_[a-z]+$'))
        self._app.add_handler(CallbackQueryHandler(self.confirm_quiz_start, pattern=r'^quiz_(?:yes|no)$'))
        self._app.add_handler(PollHandler(self.confirm_quiz_question))
        self._app.add_handler(TypeHandler(Update, self.pre_handler), -1)

        self._app.job_queue.run_daily(self.job_update_quota, time(0, 0, 0, 0))

        try:
            self._app.run_polling()
        except KeyboardInterrupt:  # in case, when the run_polling failed to handle it itself
            print('Bye.')
        except Exception as error:
            logger.error(f'Unexpected error: "{error}".')
            exit(1)

    def set_user_state(self, user: User, state: int) -> None:
        user.state = state
        write_to_db(self._dbs, user)

    # HANDLERS

    async def error_handler(self, update: Optional[object], context: ContextTypes.DEFAULT_TYPE) -> None:
        if update and isinstance(update, Update) and update.effective_user:
            uid = update.effective_user.id
            user = self._users.get(uid)

            if user and user.state > 1:  # if there is an error and user is not in NEXT, user can stuck
                self.set_user_state(user, self.NEXT)
                logger.info(f'Set user #{uid} state to NEXT at the error handler.')

        logger.error(context.error)

    async def unknown_command_handler(self, update: Update, _) -> None:
        if not update.effective_user or not update.effective_message:
            return

        uid = update.effective_user.id
        user = self._users.get(uid)

        if not user:
            return

        msg = i18n.t('wrong_cmd', locale=user.native_lang)
        await update.effective_message.reply_text(msg)

    async def pre_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.callback_query or update.poll:  # skip handler for these types of updates
            return

        if not update.effective_user:
            raise ApplicationHandlerStop

        uid = update.effective_user.id
        username = update.effective_user.username

        if user := self._users.get(uid):
            if not isinstance(context.user_data, dict):
                raise ApplicationHandlerStop

            rate_limit(
                data=context.user_data, delta_limit=3, start=5, tries_limit=3, max=self._sys.user_ban_time_mins * 60
            )

            if context.user_data.get('is_banned'):
                if not context.user_data.get('is_notified'):
                    msg = i18n.t('rate-limit', locale=user.native_lang)

                    if update.effective_message:
                        await update.effective_message.reply_text(msg)
                        context.user_data['is_notified'] = True

                    msg = f'User {uid} banned.'

                    if username:
                        msg += f' Username {username}.'

                    logger.info(msg)

                raise ApplicationHandlerStop
        else:
            user = self._dbs.execute(select(User).where(User.id == uid)).scalar_one_or_none()
            logger.info(f'Fetching user #{uid} from DB.')

            if not user:
                user = User(id=uid)
                logger.info(f'Creating user #{uid}.')

            if user.state == self.QUIZ:  # bugfix for a process crash during the quiz
                user.state = self.NEXT

            write_to_db(self._dbs, user)

            self._users[uid] = user
            self._quizers[uid] = QuizMachine(self._dbs, user, self._sys.quiz_query_limit)

            if self._quizers[uid].is_enabled:
                self.alter_user_polling(user)

        if update.message and (text := update.message.text):
            msg = f'User #{uid} sent: "{text}".'

            if username:
                msg += f' Username: {username}.'

            logger.info(msg)

    async def text_message_handler(self, update: Update, _) -> None:
        if not update.effective_user or not update.effective_message:
            return

        uid = update.effective_user.id
        user = self._users.get(uid)

        if not user:
            return

        if user.state == self.INIT:
            msg = i18n.t('choose_lang', locale=user.native_lang)
            await update.effective_message.reply_text(msg)
        elif user.state == self.NEXT:
            if not update.message or not update.message.text:
                msg = i18n.t('code_1', locale=user.native_lang)
                await update.effective_message.reply_text(msg)
                logger.error(f'Failed to complete translation for {uid}.')
                return

            if msg := self.process_translation(update.message.text, user):
                await update.effective_message.reply_markdown(msg)
        elif user.state == self.AWAIT_FOR_TZ:
            if not update.message or not update.message.text:
                msg = i18n.t('code_1', locale=user.native_lang)
                await update.effective_message.reply_text(msg)
                logger.error(f'Failed to ask timezone for {uid}.')
                return

            if msg := self.process_timezone(update.message.text, user):
                await update.effective_message.reply_markdown(msg)
        elif user.state == self.AWAIT_FOR_QN:
            if not update.message or not update.message.text:
                msg = i18n.t('code_1', locale=user.native_lang)
                await update.effective_message.reply_text(msg)
                logger.error(f'Failed to ask questions number for {uid}.')
                return

            if msg := self.process_questions_number(update.message.text, user):
                await update.effective_message.reply_markdown(msg)

    # COMMANDS

    async def command_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.effective_message:
            return

        uid = update.effective_user.id
        user = self._users.get(uid)

        if not user:
            return

        if user.state != self.INIT:
            msg = i18n.t('wrong_start', locale=user.native_lang)
            await update.effective_message.reply_markdown(msg)
            return

        lang_present = False

        if context.args and (param := context.args[0]):  # for the "/start ARG" case
            statement = select(Langs).where(Langs.lang == param)
            lang = self._dbs.execute(statement).scalar_one()
            user.native_lang = lang.lang
            write_to_db(self._dbs, user)
            lang_present = True

        if not lang_present:  # when user didn't specify a native lang in "/start ARG"
            msg = i18n.t('native_lang', locale=user.native_lang)
            markup = self.kb_native_lang()
            await update.effective_message.reply_markdown(text=msg, reply_markup=markup)
        else:
            msg = i18n.t('trans_lang', locale=user.native_lang)
            markup = self.kb_trans_lang(user)
            await update.effective_message.reply_markdown(text=msg, reply_markup=markup)

    async def command_config(self, update: Update, _) -> None:
        if not update.effective_user or not update.effective_message:
            return

        uid = update.effective_user.id
        user = self._users.get(uid)

        if not user:
            return

        if user.state != self.INIT and user.state != self.NEXT:
            msg = i18n.t('wrong_config', locale=user.native_lang)
            await update.effective_message.reply_markdown(msg)
            return

        self.set_user_state(user, self.INIT)

        msg = i18n.t('native_lang', locale=user.native_lang)
        markup = self.kb_native_lang()
        await update.effective_message.reply_markdown(text=msg, reply_markup=markup)

    async def command_quiz_mode(self, update: Update, _) -> None:
        if not update.effective_user or not update.effective_message:
            return

        uid = update.effective_user.id
        user = self._users.get(uid)

        if not user:
            return

        if user.state != self.NEXT:
            msg = i18n.t('wrong_quiz', locale=user.native_lang)
            await update.effective_message.reply_markdown(msg)
            return

        machine = QuizMachine(self._dbs, user, self._sys.quiz_query_limit)
        self._quizers[uid] = machine

        if not machine.is_enabled:
            self.set_user_state(user, self.AWAIT_FOR_TZ)
            msg = i18n.t('offset', locale=user.native_lang)
            await update.effective_message.reply_markdown(msg)
        else:
            machine.disable()
            self.alter_user_polling(user, stop=True)  # disable user's polling
            mess = i18n.t('quiz_disabled', locale=user.native_lang)
            await update.effective_message.reply_markdown(mess)

    async def command_go(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.effective_message:
            return

        uid = update.effective_user.id
        user = self._users.get(uid)

        if not user:
            return

        machine = self._quizers.get(uid)

        if user.state != self.NEXT or not machine or not machine.is_enabled:
            msg = i18n.t('wrong_go', locale=user.native_lang)
            await update.effective_message.reply_markdown(msg)
            return

        machine.prepare()

        if question := machine.next_question():
            self.alter_user_polling(user, stop=True)
            self.set_user_state(user, self.QUIZ)
            machine.update_date(return_time(user.tz_offset).date())
            await self.display_question(user, context, question, number=1, total=machine.quiz_data.questions)
        else:
            msg = i18n.t('empty_quiz', locale=user.native_lang)
            await update.effective_message.reply_text(msg)

    async def command_switch(self, update: Update, _) -> None:
        if not update.effective_user or not update.effective_message:
            return

        uid = update.effective_user.id
        user = self._users.get(uid)

        if not user:
            return

        machine = self._quizers.get(uid)

        if user.state != self.NEXT or not machine or not machine.is_enabled:
            msg = i18n.t('wrong_go', locale=user.native_lang)
            await update.effective_message.reply_markdown(msg)
            return

        machine.switch_algo()

        msg = i18n.t('switched', locale=user.native_lang)
        await update.effective_message.reply_text(msg)

    async def command_top10(self, update: Update, _) -> None:
        if not update.effective_user or not update.effective_message:
            return

        uid = update.effective_user.id
        user = self._users.get(uid)

        if not user:
            return

        machine = self._quizers.get(uid)

        if user.state != self.NEXT or not machine or not machine.is_enabled:
            msg = i18n.t('wrong_go', locale=user.native_lang)
            await update.effective_message.reply_markdown(msg)
            return

        msg = ''

        for elem in machine.top_ten():
            if msg:
                msg += '\n\n'

            msg += i18n.t(
                key='top10',
                locale=user.native_lang,
                text=elem.text,
                text_lang=elem.text_lang,
                trans=elem.trans,
                trans_lang=elem.trans_lang,
                weight=elem.weight,
                hold=elem.hold,
                last_appear=elem.last_appear if elem.last_appear else '...',
            )

        if not msg:
            msg = i18n.t('empty_top10', locale=user.native_lang)

        await update.effective_message.reply_markdown(msg)

    # KEYBOARDS

    def kb_native_lang(self) -> InlineKeyboardMarkup:
        langs = self._dbs.scalars(select(Langs)).all()
        return langs_keyboard(langs, 'native_lang_{}')

    def kb_trans_lang(self, user: User) -> InlineKeyboardMarkup:
        langs = self._dbs.scalars(select(Langs)).all()
        filtered = [x for x in langs if x.lang != user.native_lang]
        return langs_keyboard(filtered, 'trans_lang_{}')

    # CONFIRMATIONS

    async def confirm_native_lang(self, update: Update, _) -> None:
        query = update.callback_query

        if not query or not query.message or not query.data:
            return

        await query.answer()

        uid = query.message.chat.id
        user = self._users.get(uid)

        if not user or user.state != self.INIT:
            await query.delete_message()
            return

        lang = query.data.replace('native_lang_', '')
        user.native_lang = lang
        write_to_db(self._dbs, user)

        # ask user's translation language
        msg = i18n.t('trans_lang', locale=user.native_lang)
        markup = self.kb_trans_lang(user)
        await query.edit_message_text(text=msg, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

    async def confirm_trans_lang(self, update: Update, _) -> None:
        query = update.callback_query

        if not query or not query.message or not query.data:
            return

        await query.answer()

        uid = query.message.chat.id
        user = self._users.get(uid)

        if not user or user.state != self.INIT:
            await query.delete_message()
            return

        lang = query.data.replace('trans_lang_', '')
        user.trans_lang = lang
        write_to_db(self._dbs, user)

        self.set_user_state(user, self.NEXT)
        msg = i18n.t('finish_lang', locale=user.native_lang)
        await query.edit_message_text(text=msg, parse_mode=ParseMode.MARKDOWN)

    async def confirm_quiz_start(self, update: Update, _) -> None:
        query = update.callback_query

        if not query or not query.message or not query.data:
            return

        await query.answer()

        uid = query.message.chat.id
        user = self._users.get(uid)

        if not user or user.state != self.NEXT or not self._quizers.get(uid) or not self._quizers[uid].is_enabled:
            await query.delete_message()
            return

        answer = query.data.replace('quiz_', '')

        if answer == 'yes':
            machine = self._quizers[uid]
            machine.prepare()

            if question := machine.next_question():
                self.alter_user_polling(user, stop=True)
                self.set_user_state(user, self.QUIZ)
                machine.update_date(return_time(user.tz_offset).date())
                await self.display_question(user, query, question, number=1, total=machine.quiz_data.questions)
            else:
                msg = i18n.t('empty_quiz', locale=user.native_lang)
                await query.edit_message_text(msg)
        else:
            msg = i18n.t('next_time', locale=user.native_lang)
            await query.edit_message_text(msg)

    async def confirm_quiz_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.poll:
            return

        metadata = context.bot_data.get(update.poll.id)

        if not metadata or not isinstance(metadata, dict):
            return

        uid = metadata.get('uid')
        last_number = metadata.get('number')

        if not uid or not isinstance(uid, int) or not last_number or not isinstance(last_number, int):
            return

        if update.poll.is_closed:
            user = self._users.get(uid)

            if not user:
                return

            machine = self._quizers.get(uid)

            if not machine or not machine.last_question:
                return

            last = machine.last_question.content

            if not last:
                return

            correct = update.poll.correct_option_id

            if not isinstance(correct, int):
                return

            if update.poll.options[correct].voter_count:  # user gave a correct answer
                machine.quiz_data.corrects += 1
                machine.last_corrects += 1

                if last.weight and last.hold:
                    if last.hold == 1:
                        last.weight = 0

                    last.hold -= 1
            else:  # an answer was incorrect
                machine.quiz_data.mistakes += 1
                machine.last_mistakes += 1

                last.weight += 1  # mark a correct option as unchoosen
                last.hold = machine.quiz_data.revoke  # return a maximum hold value

                for option_index, option in enumerate(update.poll.options):  # look for the chosen option
                    if not option.voter_count:
                        continue

                    assert -1 < option_index < 4

                    chosen = machine.last_question.options[option_index]

                    chosen.weight += 1
                    chosen.hold = machine.quiz_data.revoke

                    write_to_db(self._dbs, chosen)
                    break

            last.appears += 1
            last.last_appear = return_time(user.tz_offset).date()
            write_to_db(self._dbs, (last, machine.quiz_data))

            if question := machine.next_question():
                await self.display_question(user, context, question, last_number, total=machine.quiz_data.questions)
            else:
                msg = i18n.t(
                    'finish_quiz',
                    corrects=machine.last_corrects,
                    mistakes=machine.last_mistakes,
                    locale=user.native_lang,
                )
                await context.bot.send_message(uid, msg, ParseMode.MARKDOWN)

                self.set_user_state(user, self.NEXT)
                self.alter_user_polling(user)
        else:
            if update.poll.total_voter_count >= 1:
                if (msg_id := metadata.get('msg_id')) and isinstance(msg_id, int):
                    await context.bot.stop_poll(uid, msg_id)
                else:
                    logger.error(f'Cannot stop poll for user #{uid}.')

    # MISC

    def process_translation(self, text: str, user: User) -> str:
        result = self._traslator.translate(text, user)

        if result.status == 'ok':
            if result.occurs:
                return i18n.t(
                    key='trans_again',
                    text=result.text,
                    lang=result.text_lang,
                    trans=result.trans,
                    tries=result.occurs,
                    locale=user.native_lang,
                )
            else:
                return i18n.t(
                    key='trans_first',
                    text=result.text,
                    lang=result.text_lang,
                    trans=result.trans,
                    locale=user.native_lang,
                )
        else:
            return result.fail_reason

    def process_timezone(self, text: str, user: User) -> str:
        if not re.match(TIMEZONE_PATTERN, text):
            return i18n.t('wrong_tz', locale=user.native_lang)

        sign = text[0] if text[0] in ('+', '-') else ''
        offset = int(text[1:]) if sign else int(text)

        if 0 <= offset <= 14 and (sign == '+' or not sign):
            user.tz_offset = str(offset)
        elif 1 <= offset <= 12 and sign == '-':
            user.tz_offset = f'-{offset}'
        else:
            return i18n.t('wrong_tz', locale=user.native_lang)

        self.set_user_state(user, self.AWAIT_FOR_QN)

        return i18n.t('qnum', locale=user.native_lang, min_qn=self._sys.min_questions, max_qn=self._sys.max_questions)

    def process_questions_number(self, text: str, user: User) -> str:
        if not text.isdigit():
            return i18n.t('wrong_qn', locale=user.native_lang)

        num = int(text)

        min_num = self._sys.min_questions
        max_num = self._sys.max_questions

        if not (min_num <= num <= max_num):
            return i18n.t('wrong_qn_value', min=min_num, max=max_num, locale=user.native_lang)

        if machine := self._quizers.get(user.id):
            if machine.enable(num):
                self.alter_user_polling(user)
                msg = i18n.t('qn_ok', locale=user.native_lang)
            else:  # We can't run a machine if there are no questions in it
                msg = i18n.t('empty_quiz', locale=user.native_lang)
        else:
            logger.error(f'Cannot retrieve a quiz machine for {user.id} during the numbers selection.')
            msg = i18n.t('sww', locale=user.native_lang)

        self.set_user_state(user, self.NEXT)
        return msg

    # QUIZ-RELATED

    async def quiz_start(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if (
            not context.job
            or not context.job.data
            or not isinstance(context.job.data, dict)
            or not context.job.data.get('uid')
        ):
            logger.error('Cannot run the quiz, no user ID.')
            return

        uid = context.job.data.get('uid')

        if not isinstance(uid, int):
            logger.error(f'UID is not int: {uid}.')
            return

        user = self._users.get(uid)

        if not user or user.state != self.NEXT:
            logger.error(f'Either no user with UID {uid} or its state is not NEXT.')
            return

        usertime = return_time(user.tz_offset)

        if usertime.hour <= self._sys.time_left_bound_hours or usertime.hour >= self._sys.time_right_bound_hours:
            logger.debug(f'Incorrect time for quiz of UID {uid}.')
            return

        machine = self._quizers.get(uid)

        if not machine:
            machine = QuizMachine(self._dbs, user, self._sys.quiz_query_limit)
            self._quizers[uid] = machine

        if not machine.is_enabled:
            logger.error(f'Trying to quiz a disabled user {uid}.')
            return

        if machine.quiz_data.quized_on and machine.quiz_data.quized_on == usertime.date():
            logger.debug(f'User {uid} was quizzed today.')
            return

        if prev_msg_id := context.job.data.get('msg_id'):
            try:
                await context.bot.delete_message(uid, prev_msg_id)
                logger.info(f'Previous message #{prev_msg_id} was deleted for user {uid}.')
            except Exception as error:
                logger.error(f'Failed to delete the previous message (#{prev_msg_id}) for user {uid}: {error}.')

        text = i18n.t('are_u_ready', locale=user.native_lang)
        options = i18n.t('yes_no', locale=user.native_lang).split()

        msg = await context.bot.send_message(
            chat_id=uid, text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=yes_no_keyboard('quiz', options)
        )
        context.job.data['msg_id'] = msg.message_id

    async def display_question(
        self,
        user: User,
        context: CallbackQuery | ContextTypes.DEFAULT_TYPE,
        question: Question,
        number: int,
        total: int,
    ) -> None:
        if isinstance(context, CallbackQuery):
            await context.delete_message()

            display_func = context.get_bot().send_poll
        elif isinstance(context, CallbackContext):
            display_func = context.bot.send_poll

        else:
            logger.error(f'Failed to display question for {user.id}.')
            return

        options: list[str] = []

        for elem in question.options:
            if question.options_lang == elem.text_lang:
                options.append(elem.text)
            else:
                options.append(elem.trans)

        msg = await display_func(
            chat_id=user.id,
            question=i18n.t('quiz_q', text=question.text, number=number, total=total, locale=user.native_lang),
            options=options,
            type=Poll.QUIZ,
            correct_option_id=question.correct_index,  # type: ignore
        )

        if not msg.poll:
            logger.error(f'Failed to display question for {user.id}.')
            return

        number += 1

        self._app.bot_data.update({msg.poll.id: {'uid': user.id, 'msg_id': msg.message_id, 'number': number}})

    # JOBS

    async def job_update_quota(self, _) -> None:
        for user in self._users.values():
            try:
                user.api_day_quota = user.api_day_quota_limit
                write_to_db(self._dbs, user)
            except Exception as error:
                logger.error(f'Job failed to update qouta for {user.id}: {error}.')

    def alter_user_polling(self, user: User, *, stop=False) -> None:
        job_name = f'quiz_polling_{user.id}'
        job_queue = self._app.job_queue

        if not job_queue:
            return

        for job in job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()
            logger.info(f'Job "{job.name}" is scheduled to be removed for user {user.id}.')

        if stop:
            return

        data = {'uid': user.id}
        interval = self._sys.polling_interval
        skew = shift_time(interval)

        logger.info(f'Job "{job_name}" is starting in {skew // 60} min (or {skew} sec).')

        job_queue.run_repeating(
            callback=self.quiz_start,
            name=job_name,
            interval=interval * 60,
            first=skew,
            data=data,
            chat_id=user.id,
            job_kwargs={'misfire_grace_time': None},
        )
