CREATE TABLE IF NOT EXISTS langs
(
    id BIGSERIAL NOT NULL PRIMARY KEY,
    lang CHARACTER VARYING(8) UNIQUE NOT NULL,
    full_name CHARACTER VARYING(64) NOT NULL,
    gcode CHARACTER VARYING(8) NOT NULL
);


CREATE TABLE IF NOT EXISTS users
(
    id BIGSERIAL NOT NULL PRIMARY KEY,
    state INTEGER NOT NULL DEFAULT 0,
    native_lang CHARACTER VARYING(8) NOT NULL DEFAULT 'ru',
    trans_lang CHARACTER VARYING(8) NOT NULL DEFAULT 'en',
    tz_offset CHARACTER VARYING(3) NOT NULL DEFAULT '0',
    api_day_quota INTEGER NOT NULL DEFAULT 100,
    api_day_quota_limit INTEGER NOT NULL DEFAULT 100,
    algo CHARACTER VARYING(8) NOT NULL DEFAULT 'GAPI',
    created_on TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    updated_on TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_langs_users_a FOREIGN KEY (native_lang)
        REFERENCES langs (lang) MATCH SIMPLE,
    CONSTRAINT fk_langs_users_b FOREIGN KEY (trans_lang)
        REFERENCES langs (lang) MATCH SIMPLE
);


CREATE TABLE IF NOT EXISTS systems
(
    id BIGSERIAL NOT NULL PRIMARY KEY,
    max_word_count INTEGER NOT NULL DEFAULT 5,
    max_word_len INTEGER NOT NULL DEFAULT 32,
    max_text_len INTEGER NOT NULL DEFAULT 192,
    min_questions INTEGER NOT NULL DEFAULT 10,
    max_questions INTEGER NOT NULL DEFAULT 20,
    polling_interval INTEGER NOT NULL DEFAULT 180,
    quiz_query_limit INTEGER NOT NULL DEFAULT 1000,
    user_ban_time_mins INTEGER NOT NULL DEFAULT 3,
    time_left_bound_hours INTEGER NOT NULL DEFAULT 9,
    time_right_bound_hours INTEGER NOT NULL DEFAULT 21,
    CHECK (min_questions <= max_questions),
    CHECK (time_left_bound_hours <= time_right_bound_hours)
);


CREATE TABLE IF NOT EXISTS content
(
    id BIGSERIAL NOT NULL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    text TEXT NOT NULL,
    text_lang CHARACTER VARYING(8) NOT NULL,
    trans TEXT NOT NULL,
    trans_lang CHARACTER VARYING(8) NOT NULL,
    occurs INTEGER NOT NULL DEFAULT 0,
    weight INTEGER NOT NULL DEFAULT 0,
    appears INTEGER NOT NULL DEFAULT 0,
    hold INTEGER NOT NULL DEFAULT 0,
    created_on TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    last_appear DATE,
    CONSTRAINT fk_users_content_a FOREIGN KEY (user_id)
        REFERENCES users (id) MATCH SIMPLE,
    CONSTRAINT fk_langs_content_a FOREIGN KEY (text_lang)
        REFERENCES langs (lang) MATCH SIMPLE,
    CONSTRAINT fk_langs_content_b FOREIGN KEY (trans_lang)
        REFERENCES langs (lang) MATCH SIMPLE
);


CREATE TABLE IF NOT EXISTS quiz
(
    id BIGSERIAL NOT NULL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    algo CHARACTER VARYING(8) NOT NULL DEFAULT 'v2',
    revoke INTEGER NOT NULL DEFAULT 3,
    is_enabled BOOLEAN NOT NULL DEFAULT false,
    questions INTEGER NOT NULL DEFAULT 15,
    corrects INTEGER NOT NULL DEFAULT 0,
    mistakes INTEGER NOT NULL DEFAULT 0,
    quized_on DATE,
    CONSTRAINT fk_users_quiz_a FOREIGN KEY (user_id)
        REFERENCES users (id) MATCH SIMPLE
);



INSERT INTO langs (lang, full_name, gcode) VALUES ('ru', 'Русский', 'ru');
INSERT INTO langs (lang, full_name, gcode) VALUES ('ua', 'Український', 'uk');
INSERT INTO langs (lang, full_name, gcode) VALUES ('en', 'English', 'en');
INSERT INTO langs (lang, full_name, gcode) VALUES ('de', 'Deutsch', 'de');
INSERT INTO langs (lang, full_name, gcode) VALUES ('fr', 'Français', 'fr');
INSERT INTO langs (lang, full_name, gcode) VALUES ('es', 'Español', 'es');
INSERT INTO langs (lang, full_name, gcode) VALUES ('it', 'Italiano', 'it');
INSERT INTO systems (id, max_word_count, max_word_len, max_text_len, min_questions, max_questions, polling_interval, quiz_query_limit, user_ban_time_mins, time_left_bound_hours, time_right_bound_hours) VALUES (0, 5, 32, 192, 10, 20, 180, 1000, 3, 9, 21);