from gunther.bot import GuntherBot

import os

from gunther.misc import err_print


def check_env(keys: tuple[str, ...]) -> None:
    for key in keys:
        if not os.environ.get(key):
            err_print(f'There is no key "{key}" or its value is not present.')
            exit(1)


if __name__ == '__main__':
    check_env(
        (
            'TOKEN',
            'GOOGLE_APPLICATION_CREDENTIALS',
            'DB_HOST',
            'DB_USER',
            'DB_PASS',
            'DB_NAME',
            'DB_PORT',
            'REDIS_HOST',
            'REDIS_PORT',
            'REDIS_PASS',
            'TRANS_PATH',
        )
    )

    TOKEN = os.environ['TOKEN']
    DB_URL = 'postgresql://{USR}:{PWD}@{HOST}:{PORT}/{DB}'.format(
        USR=os.environ['DB_USER'],
        PWD=os.environ['DB_PASS'],
        HOST=os.environ['DB_HOST'],
        PORT=os.environ['DB_PORT'],
        DB=os.environ['DB_NAME'],
    )
    REDIS_URL = 'redis://:{PASS}@{HOST}:{PORT}/'.format(
        HOST=os.environ['REDIS_HOST'], PASS=os.environ['REDIS_PASS'], PORT=os.environ['REDIS_PORT']
    )
    TRANS_PATH = os.environ['TRANS_PATH']
    TG_API_URL = os.environ.get('TG_API', '')

    GuntherBot(token=TOKEN, db_url=DB_URL, cache_url=REDIS_URL, trans_path=TRANS_PATH, api_url=TG_API_URL)
