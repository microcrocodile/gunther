from __future__ import annotations

import i18n  # type: ignore
import re
import redis

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session
from sqlalchemy.future import select

from google.cloud import translate_v2 as gapi  # type: ignore

from html import unescape

from gunther.models import User, Content, System, Langs
from gunther.misc import write_to_db


RE_PATTERN_1 = r'^(?:\d|\W)+$'
RE_PATTERN_2 = r'^\W.*'


@dataclass
class Translation:
    status: Literal['ok', 'fail']
    fail_reason: str
    text: str
    text_lang: str
    trans: str
    trans_lang: str
    occurs: int


class Translator:
    __slots__ = ('_dbs', '_cache_url')

    def __init__(self, db_session: Session, cache_url: str) -> None:
        self._cache_url = cache_url
        self._dbs = db_session

    def _validate(self, text: str, locale: str) -> str:
        sys = self._dbs.execute(select(System).where(System.id == 0)).scalar_one()

        if len(text) > sys.max_text_len:
            return i18n.t('code_2', locale=locale, text_len=sys.max_text_len)

        if words := text.split():
            if len(words) > sys.max_word_count:
                return i18n.t('code_3', locale=locale, words_count=sys.max_word_count)

            for word in words:
                if len(word) > sys.max_word_len:
                    return i18n.t('code_4', locale=locale, word_len=sys.max_word_len)

                if re.match(RE_PATTERN_1, word) or re.match(RE_PATTERN_2, word):
                    return i18n.t('code_5', locale=locale)

        return ''

    def _check_cache(self, text: str, native_lang: str, trans_lang: str) -> str:
        try:
            cache = redis.from_url(self._cache_url + native_lang)
            result = cache.hget(trans_lang, text)

            if result and isinstance(result, bytes):
                return result.decode('utf-8')
        except Exception:
            pass

        return ''

    def _update_cache(self, text: str, trans: str, native_lang: str, trans_lang: str) -> None:
        try:
            cache = redis.from_url(self._cache_url + native_lang)
            cache.hset(trans_lang, text, trans)
        except Exception:
            pass

    def translate(self, text: str, user: User) -> Translation:
        method = f'_translate_{user.algo.lower()}'

        if hasattr(self, method):
            return getattr(self, method)(text, user)

        return self._translate_gapi(text, user)  # fallback method

    def _translate_gapi(self, text: str, user: User) -> Translation:
        def convert_lang_code(lang_code: str) -> str:
            lang = self._dbs.execute(select(Langs).where(Langs.lang == lang_code)).scalar_one()
            return lang.gcode

        def on_fail(code: str, **kwargs) -> Translation:
            return Translation(
                status='fail',
                fail_reason=i18n.t(code, locale=user.native_lang, **kwargs),
                text='',
                text_lang='',
                trans='',
                trans_lang='',
                occurs=0,
            )

        text = text.strip().lower()

        if validate_result := self._validate(text, locale=user.native_lang):
            return Translation(
                status='fail',
                fail_reason=validate_result,
                text='',
                text_lang='',
                trans='',
                trans_lang='',
                occurs=0,
            )

        if content := self._dbs.execute(
            (
                select(Content)
                .where(Content.user_id == user.id)
                .where(Content.text == text)
                .where(Content.text_lang == user.trans_lang)
                .where(Content.trans_lang == user.native_lang)
            )
        ).scalar_one_or_none():  # There is a translation in DB
            content.occurs += 1
            content.weight += 1

            write_to_db(self._dbs, content)

            return Translation(
                status='ok',
                fail_reason='',
                text=content.text,
                text_lang=content.text_lang,
                trans=content.trans,
                trans_lang=content.trans_lang,
                occurs=content.occurs,
            )
        else:  # No translation is available
            trans_result = self._check_cache(text, user.native_lang, user.trans_lang)  # Look it in the common cache

            if trans_result:  # There is a cache option
                return Translation(
                    status='ok',
                    fail_reason='',
                    text=text,
                    text_lang=user.native_lang,
                    trans=trans_result,
                    trans_lang=user.trans_lang,
                    occurs=0,
                )
            else:  # Use the GAPI to translate
                if not user.api_day_quota:  # User is above the limit
                    return on_fail('code_6', api_quota=user.api_day_quota_limit)

                user.api_day_quota -= 1
                write_to_db(self._dbs, user)

                native_lang = convert_lang_code(user.native_lang)
                text_lang = convert_lang_code(user.trans_lang)

                client = gapi.Client(target_language=native_lang)
                result = client.translate(text, source_language=text_lang, target_language=native_lang)

                if not result or not isinstance(result, dict) or not result.get('translatedText'):
                    return on_fail('trans_no_response')

                trans_result = result['translatedText']

                if not isinstance(trans_result, str):
                    return on_fail('trans_no_response')

                trans_result = trans_result.lower()
                trans_result = unescape(trans_result)

                if trans_result == text:
                    return on_fail('code_8')

                if self._cache_url:  # Update the cache
                    self._update_cache(text, trans_result, user.native_lang, user.trans_lang)

                content = Content(
                    user_id=user.id,
                    text=text,
                    text_lang=user.trans_lang,
                    trans=trans_result,
                    trans_lang=user.native_lang,
                )
                write_to_db(self._dbs, content)

                return Translation(
                    status='ok',
                    fail_reason='',
                    text=content.text,
                    text_lang=content.text_lang,
                    trans=content.trans,
                    trans_lang=content.trans_lang,
                    occurs=content.occurs,
                )
