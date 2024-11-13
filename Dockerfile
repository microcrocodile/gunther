FROM python:3.11.1-slim
WORKDIR /opt/gunther/
COPY gunther /opt/gunther/gunther/
COPY translations /opt/gunther/translations/
RUN pip install --no-cache-dir "python-telegram-bot[job-queue]==21.6" \
    "python-i18n[yaml]==0.3.9" \
    "sqlalchemy==2.0.36" \
    "psycopg2-binary==2.9.10" \
    "redis==5.2.0" \
    "google-cloud-translate==3.17.0"
CMD [ "python", "-m", "gunther"]