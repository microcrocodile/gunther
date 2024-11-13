from __future__ import annotations

from datetime import datetime, date, time
from dataclasses import dataclass
from typing import Optional, Sequence
from collections import deque
from random import sample, randrange, random

from sqlalchemy.orm import Session
from sqlalchemy.future import select

from gunther.models import User, Quiz, Content
from gunther.misc import write_to_db


@dataclass
class Question:
    text: str
    lang: str
    options: list[Content]
    options_lang: str
    correct_index: int
    content: Content

    def __repr__(self):
        r = ''
        r += f'Question: {self.text} ({self.lang})\n'
        r += f'Answers lang: {self.options_lang}\n'
        r += f'Correct answer: {self.correct_index}\n'

        for opt in self.options:
            if self.options_lang == opt.text_lang:
                r += f'\tAnswer: {opt.text}\n'
            else:
                r += f'\tAnswer: {opt.trans}\n'

        r = r.rstrip()

        return r


class QuizMachine:
    __slots__ = (
        '_dbs',
        '_limit',
        '_user',
        '_quiz_data',
        '_queue',
        '_last_question',
        '_last_corrects',
        '_last_mistakes',
    )

    @property
    def is_enabled(self) -> bool:
        return self._quiz_data.is_enabled

    @property
    def quiz_data(self) -> Quiz:
        return self._quiz_data

    @property
    def last_question(self) -> Optional[Question]:
        return self._last_question

    @property
    def last_corrects(self) -> int:
        return self._last_corrects

    @last_corrects.setter
    def last_corrects(self, value: int) -> None:
        if not isinstance(value, int):
            raise TypeError('Last corrects counter type must be int.')

        if value <= 0:
            raise ValueError('Last corrects counter must be greater than zero.')

        self._last_corrects = value

    @property
    def last_mistakes(self) -> int:
        return self._last_mistakes

    @last_mistakes.setter
    def last_mistakes(self, value: int) -> None:
        if not isinstance(value, int):
            raise TypeError('Last mistakes counter type must be int.')

        if value <= 0:
            raise ValueError('Last mistakes counter must be greater than zero.')

        self._last_mistakes = value

    def __init__(self, db_session: Session, user: User, query_limit: int) -> None:
        self._dbs = db_session
        self._user = user
        self._limit = query_limit

        self._queue: deque[Question] = deque()
        self._last_question: Optional[Question] = None
        self._last_corrects = 0
        self._last_mistakes = 0

        quiz_data = self._dbs.execute(select(Quiz).where(Quiz.user_id == user.id)).scalar_one_or_none()

        if not quiz_data:
            quiz_data = Quiz(user_id=user.id)
            write_to_db(self._dbs, quiz_data)

        self._quiz_data = quiz_data

    def enable(self, questions: int) -> bool:
        if self._quiz_data.is_enabled:
            return True

        self._quiz_data.questions = questions

        self.prepare()  # dry run

        if not self._queue:  # there are no questions, we cannot enable the machine
            return False

        self._quiz_data.is_enabled = True

        write_to_db(self._dbs, self._quiz_data)

        return True

    def disable(self) -> None:
        if not self._quiz_data.is_enabled:
            return

        self._quiz_data.is_enabled = False

        write_to_db(self._dbs, self._quiz_data)

    def update_date(self, value: date) -> None:
        self._quiz_data.quized_on = value

        write_to_db(self._dbs, self._quiz_data)

    def _get_question(self, source: Content, candidates: dict[str, list[Content]], flip=False) -> Optional[Question]:
        to_delete: Optional[Content] = None

        key = source.text_lang if flip else source.trans_lang
        value = source.text if flip else source.trans

        for elem in candidates[key]:  # Do not use id() here! Always compare by inner fields!
            elem_value = elem.text if flip else elem.trans

            if elem_value == value:
                to_delete = elem

        if to_delete:
            candidates[key].remove(to_delete)

        if len(candidates[key]) < 3:  # Not enough options
            return None

        options = sample(candidates[key], 3)

        for opt in options:
            candidates[key].remove(opt)

        options.append(source)
        options.sort(key=lambda _: random())

        if flip:
            return Question(
                text=source.trans,
                lang=source.trans_lang,
                options=options,
                options_lang=source.text_lang,
                correct_index=options.index(source),
                content=source,
            )
        else:
            return Question(
                text=source.text,
                lang=source.text_lang,
                options=options,
                options_lang=source.trans_lang,
                correct_index=options.index(source),
                content=source,
            )

    def _populate(self, targets: Sequence[Content], candidates: dict[str, list[Content]]) -> None:
        for elem in targets[: self._quiz_data.questions]:
            flip_chance = randrange(1, 5)

            if question := self._get_question(elem, candidates, flip=(flip_chance == 3)):
                self._queue.append(question)

    def _algo_v1(self, tend_to_appear=False) -> None:
        """
        This algo selects no more than the system limit of words that were sorted in a descending order based on
        their weight. If `tend_to_appear` selected, it sorts them based on the last appear field.
        """

        def sort_by_last_appear(value: Content) -> float:
            if value.last_appear:
                return datetime.combine(value.last_appear, time()).timestamp()

            return 0.0

        results = self._dbs.scalars(
            select(Content).where(Content.user_id == self._user.id).order_by(Content.weight.desc()).limit(self._limit)
        ).all()

        if not results or not isinstance(results, list):
            return

        candidates: dict[str, list[Content]] = {}

        if tend_to_appear:
            results.sort(key=sort_by_last_appear)

        for elem in results:
            if elem.trans_lang not in candidates:
                candidates[elem.trans_lang] = []

            flag = False

            for cand in candidates[elem.trans_lang]:
                if cand.trans == elem.trans:  # if we already have the same translation
                    flag = True
                    break
            else:
                candidates[elem.trans_lang].append(elem)

            if flag:  # skip it from both lists
                continue

            if elem.text_lang not in candidates:
                candidates[elem.text_lang] = []

            candidates[elem.text_lang].append(elem)

        self._populate(results, candidates)

    def _algo_v2(self) -> None:
        self._algo_v1(tend_to_appear=True)

    def prepare(self) -> None:
        method = f'_algo_{self._quiz_data.algo.lower()}'

        self._queue = deque()
        self._last_question = None
        self._last_corrects = 0
        self._last_mistakes = 0

        if hasattr(self, method):
            getattr(self, method)()
        else:
            self._algo_v1(tend_to_appear=False)  # fallback method

        if len(self._queue) != self._quiz_data.questions:  # not enough questions
            self._queue = deque()

    def next_question(self) -> Optional[Question]:
        if self._queue:
            question = self._queue.popleft()
            self._last_question = question

            return question

        return None

    def switch_algo(self) -> None:
        if self._quiz_data.algo == 'v1':
            self._quiz_data.algo = 'v2'
        else:
            self._quiz_data.algo = 'v1'

        write_to_db(self._dbs, self._quiz_data)

    def top_ten(self) -> Sequence[Content]:
        return self._dbs.scalars(
            select(Content)
            .where(Content.user_id == self._user.id)
            .where(Content.weight > 0)
            .order_by(Content.weight.desc())
            .limit(10)
        ).all()
