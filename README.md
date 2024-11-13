*Gunther* is a multiuser translation bot, it uses the Google API as a translation service, and the Telegram Bot API as a frontend. One can use a bot alone, share it with family and friends, or provide it for a broader audience.
# Functionality
## User`s input
The goal is to translate single words or simple phrases, not texts. However, an administrator can alter input parameters, such as the number of words, total length, etc.
## Translation API
The default and currently only translation API is the [Cloud Translation API](https://cloud.google.com/translate/docs/reference/rest) by Google. An API type can be set in a per-user manner, Gunther supports the addition of other APIs with minimal code changes.

Unfortunately, the Google API does not support several translations of a request and yields the first one. Gunther is not able to change this behavior. Future APIs must follow this design too.
## Database
Users and their settings are stored in the DB. Gunther uses PostgreSQL.

In base mode, Gunther asks a user to specify the native language (all input will be translated to it) and the source language (all requests are expected to belong to it). These languages are stored in the DB for the user and never asked again. A user can change any of these languages or both of them at any time by the `/config` command.

Gunther saves history per user. If a user asks for the same translation again, the bot will fetch the result from the DB, not the API. The user is notified how many times this translation was previously done. It helps to pay extra attention to it (and saves the API calls too).
## Cache
Gunther saves translations in a common user-independent cache. It helps save the translation API calls. Gunther uses Redis.
## Daily quota
If a translation is not available in the DB or cache, Gunther calls the translation API. A user is restricted this way based on a daily limit. An administrator can configure the limit per user.
## Quiz mode
When a translation is stored in the user\`s history, it has a zero weight. Every next request for this translation from the user increases this weight by one. This allows to sort the user\`s history by the most problematic positions.

A user is able to activate and deactivate the quiz mode with the `/quiz` command. Gunther asks the user for a time zone setting and a count of questions per daily quiz. The quiz mode can be activated only if the user\`s history has at least four records.

After the quiz mode is active, Gunther offers to start a quiz every hour from 9 am to 8 pm (based on the provided time zone). Once the user agrees to start the quiz, Gunther stops offering the quiz that day.

The quiz is based on the Telegram Poll and comprises questions each of which has one correct and three incorrect possible answers. Gunther records correct and incorrect results.
### Quiz algorithms
Gunther uses the user\`s history to provide questions for a quiz. The weight attribute is the key aspect in the process of the selection of records from this history. Currently, there are two algorithms. A user can switch between them by the `/switch` command. Gunther supports the addition of other algorithms with minimal code changes. The first algorithm sorts the history based on the maximum weight value only. The second accounts for the last appearance attribute and tends to show user records evenly.
### Incorrect answer
When a user gives a wrong answer there are two mistakes. One is for a question itself, and the other is for an incorrect answer. Gunther increases the weight for both records.
### Correct answer and the hold attribute
For a correct answer, Gunther does not decrease the weight. Instead, it decreases a special hold attribute. The hold attribute is set to its maximum whenever the weight increases. The maximum is a global value set by an administrator. Every correct answer decreases the hold, and when it reaches zero, the weight is set to zero too. Simple, right?
# Requirements
Gunther requires the Google API and Telegram Bot tokens. Obtaining these tokens is out of the scope of this doc, but it is easy and completely free (at least at this moment). The GAPI token is expected to be present in a separate JSON file. The Telegram token is provided via the EVN variable.
# Dockerization
Gunther is Docker-ready. It is expected that a hosting server has the Docker Compose tool. Please, edit the `docker-compose.yml` before deploying!