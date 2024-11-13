import sys

import i18n  # type: ignore

from datetime import datetime, timezone, timedelta
from typing import Sequence

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from gunther.models import Langs


def err_print(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)


def init_i18n(path: str) -> None:
    i18n.set('filename_format', '{locale}.{format}')
    i18n.load_path.append(path)
    i18n.set('locale', 'en')
    i18n.set('fallback', 'en')


def write_to_db(session: Session, data: object) -> None:
    if not session or type(session) is not Session or not data:
        return

    if type(data) is list or type(data) is tuple:
        for elem in data:
            session.add(elem)
    else:
        session.add(data)

    try:
        session.commit()
    except IntegrityError as err:
        session.rollback()
        raise Exception(f'write_to_db: fail to write data into db - "{err}", rolling back.')


def rate_limit(data: dict, delta_limit: int, start: int, tries_limit: int, max: int) -> None:
    """
    `data` - object to store temporary user's data.

    `delta_limit` - number of seconds between two consecutive messages.

    `start` - minumum restriction time (cannot be greater than `max`) in seconds.

    `tries_limit` - maximum of allowed messages per `delta_limit`.

    `max` - maximum restriction time in seconds.
    """

    if start > max:
        raise Exception('rate_limit: start cannot be greater than max.')

    ts = datetime.now(timezone.utc)

    if prev_ts := data.get('ts'):  # this is a second message or more
        if type(prev_ts) is not datetime:
            raise Exception('rate_limit: prev_ts must be a datetime object.')

        delta = ts - prev_ts  # calculate the delta between to consequent messages

        if delta.seconds < delta_limit:  # these two messages are in the delta limit
            if 'is_banned' not in data:  # user is not banned yet
                if 'count' not in data:
                    data['count'] = 0

                data['count'] += 1  # start count messages in the delta limits

                if data['count'] > tries_limit:  # number of these messages more then tries limit
                    data['is_banned'] = True  # ban the user
                    data['last_ban'] = start  # set the first restriction time for the user
            else:  # user is already banned, increase the ban time if user isn't keeping calm
                prev_bt = data['last_ban']

                if prev_bt * 2 < max:
                    data['last_ban'] = prev_bt * 2  # increase ban time twice if it is less than max
                else:
                    data['last_ban'] = max  # set max time
        else:  # these two messages are not in the delta limit
            if 'is_banned' in data:  # check the user is banned
                if delta.seconds > data['last_ban']:  # message is after the ban time so release the user
                    del data['is_banned']
                    del data['last_ban']

                    if 'is_notified' in data:
                        del data['is_notified']

            if 'count' in data:
                del data['count']

    data['ts'] = ts


def langs_keyboard(options: Sequence[Langs], cb_prefix: str, columns=4) -> InlineKeyboardMarkup:
    outer: list[list[InlineKeyboardButton]] = []
    inner: list[InlineKeyboardButton] = []

    counter = 0

    for lang in options:
        inner.append(InlineKeyboardButton(text=lang.full_name, callback_data=cb_prefix.format(lang.lang)))
        counter += 1

        if counter == columns:
            outer.append(inner)
            inner = []
            counter = 0

    if inner:
        outer.append(inner)

    return InlineKeyboardMarkup(outer)


def yes_no_keyboard(prefix: str, options: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(options[0], callback_data=f'{prefix}_yes'),
                InlineKeyboardButton(options[1], callback_data=f'{prefix}_no'),
            ],
        ]
    )


def shift_time(interval: int) -> int:
    ct = datetime.now()
    minute = ct.minute
    second = ct.second

    if extra := interval % 60:
        return (extra - (minute % extra)) * 60 - second

    return (60 - minute) * 60 - second


def return_time(params: str) -> datetime:
    ct = datetime.now(timezone.utc)

    if params.startswith('-'):
        offset = int(params[1:])
        return ct - timedelta(hours=offset)
    else:
        offset = int(params)
        return ct + timedelta(hours=offset)
