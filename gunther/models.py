from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import CheckConstraint
from sqlalchemy import ForeignKey, String, Integer, BigInteger, DateTime, Date, Text, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase): ...


class System(Base):
    __tablename__ = 'systems'

    id: Mapped[int] = mapped_column(BigInteger, nullable=False, primary_key=True)
    max_word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_word_len: Mapped[int] = mapped_column(Integer, nullable=False, default=32)
    max_text_len: Mapped[int] = mapped_column(Integer, nullable=False, default=192)
    min_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    polling_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    quiz_query_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    user_ban_time_mins: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    time_left_bound_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=9)
    time_right_bound_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=21)

    __table_args__ = (
        CheckConstraint(min_questions <= max_questions),
        CheckConstraint(time_left_bound_hours <= time_right_bound_hours),
    )


class Langs(Base):
    __tablename__ = 'langs'

    id: Mapped[int] = mapped_column(BigInteger, nullable=False, primary_key=True)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(64), nullable=False)
    gcode: Mapped[str] = mapped_column(String(8), nullable=False)


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(BigInteger, nullable=False, primary_key=True)
    state: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    native_lang: Mapped[str] = mapped_column(ForeignKey('langs.lang'), default='ru')
    trans_lang: Mapped[str] = mapped_column(ForeignKey('langs.lang'), default='en')
    tz_offset: Mapped[str] = mapped_column(String(3), nullable=False, default='0')
    api_day_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    api_day_quota_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    algo: Mapped[str] = mapped_column(String(8), nullable=False, default='GAPI')
    created_on: Mapped[datetime] = mapped_column(DateTime, default=datetime.now())
    updated_on: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(), onupdate=datetime.now())


class Content(Base):
    """
    text -- contains the user's input (a word or phrase).

    trans -- contains the translation of the text to the trans_lang.

    occurs -- is a number of how many times the user translated this word. Showed in the translation message.

    weight -- is the same as the occurs but used for the quiz mode. Can be zeroed at any time.

    appears -- is a number of appearances of the text int the quiz. Just a stat.

    hold -- is a number of holding the weight greater than 0. With 0 for hold the weight becomes 0 too.

    last_appear -- is the date when this text appeared in the quiz for the last time.
    """

    __tablename__ = 'content'

    id: Mapped[int] = mapped_column(BigInteger, nullable=False, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_lang: Mapped[str] = mapped_column(ForeignKey('langs.lang'))
    trans: Mapped[str] = mapped_column(Text, nullable=False)
    trans_lang: Mapped[str] = mapped_column(ForeignKey('langs.lang'))
    occurs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    appears: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_on: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now())
    last_appear: Mapped[date] = mapped_column(Date)

    def __repr__(self) -> str:
        r = ''
        r += f'Text: {self.text}\n'
        r += f'Text lang: {self.text_lang.upper()}\n'
        r += f'Translation: {self.trans}\n'
        r += f'Translated to: {self.trans_lang.upper()}\n'
        r += f'Last appear: {self.last_appear}\n'
        r += f'Weight: {self.weight}\n'
        r += f'Hold: {self.hold}'

        return r


class Quiz(Base):
    __tablename__ = 'quiz'

    id: Mapped[int] = mapped_column(BigInteger, nullable=False, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    algo: Mapped[str] = mapped_column(String(8), nullable=False, default='v2')
    revoke: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    questions: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    is_enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    corrects: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mistakes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quized_on: Mapped[date] = mapped_column(Date)
