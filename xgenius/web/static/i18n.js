'use strict';
const I18N = (() => {
  const rows = `
select_filtered|Выбрать найденные|Select matching profiles|Вибрати знайдені
select_page|Выбрать страницу|Select this page|Вибрати сторінку
selection_hidden|Вне фильтра: {n}|Outside filters: {n}|Поза фільтром: {n}
in_progress|В процессе|In progress|У процесі
proxy_filter|Состояние прокси|Proxy status|Стан проксі
all_proxies|Все прокси|All proxies|Усі проксі
proxy_working|Прокси работает|Working proxy|Проксі працює
proxy_unchecked|Не проверен|Not checked|Не перевірено
check_proxies|Проверить прокси|Check proxies|Перевірити проксі
location_unavailable|Регион не определён|Location unavailable|Регіон не визначено
proxy_progress|Проверено {done} из {total}|Checked {done} of {total}|Перевірено {done} з {total}
proxy_batch_result|Проверка завершена: работают — {ok}, ошибки — {failed}. Подробности в строках профилей.|Proxy checks complete: {ok} working, {failed} failed. Details are in profile rows.|Перевірку завершено: працюють — {ok}, помилки — {failed}. Подробиці в рядках профілів.
package_missing_session|В пакете отсутствуют файлы сессий. Экспортируйте профили заново.|The package is missing session files. Export the profiles again.|У пакеті відсутні файли сесій. Експортуйте профілі повторно.
workspace_access|Не удалось сохранить профили: нет доступа на запись в рабочую папку. Проверьте её разрешения.|Cannot save profiles: check write access to the workspace folder.|Не вдалося зберегти профілі: немає доступу на запис до робочої папки. Перевірте її дозволи.
workspace_space|Недостаточно места для импорта профилей. Освободите место в рабочей папке.|Not enough disk space to import profiles. Free space in the workspace folder.|Недостатньо місця для імпорту профілів. Звільніть місце в робочій папці.
transfer_done|Перенос профилей завершён.|Profile transfer completed.|Перенесення профілів завершено.
transfer_partial|Перенос завершён. Не удалось перенести профилей: {n}. Откройте отчёт с причинами.|Transfer completed with {n} profile errors. Open the report for details.|Перенесення завершено. Помилки у {n} профілях. Відкрийте звіт із причинами.
transfer_failed|Перенос не удался. Откройте отчёт.|Transfer failed. Open the report.|Перенесення не вдалося. Відкрийте звіт.
transfer_cancelled|Перенос остановлен. Готовые профили сохранены.|Transfer stopped. Completed profiles were saved.|Перенесення зупинено. Готові профілі збережено.
proxy_geo_failed|Прокси работает, но сервис геолокации не ответил. Повторите проверку позже.|The proxy works, but geolocation is unavailable. Check again later.|Проксі працює, але сервіс геолокації не відповів. Повторіть перевірку пізніше.
proxy_changed|Прокси изменился во время проверки. Проверьте его ещё раз.|The proxy changed during the check. Check it again.|Проксі змінився під час перевірки. Перевірте його ще раз.
launch_timeout|Запуск или вход занял больше 240 секунд. Проверьте прокси и повторите попытку.|Launch or sign-in took over 240 seconds. Check the proxy and retry.|Запуск або вхід тривав понад 240 секунд. Перевірте проксі та повторіть спробу.
launch_failed|Не удалось запустить профиль. Проверьте прокси, Chrome и ChromeDriver.|Could not launch the profile. Check the proxy, Chrome and ChromeDriver.|Не вдалося запустити профіль. Перевірте проксі, Chrome та ChromeDriver.
sign_in_failed|Не удалось войти в X. Проверьте сессию, токен или пройдите проверку в открытом браузере.|X sign-in failed. Check the session, token or verification in the open browser.|Не вдалося увійти в X. Перевірте сесію, токен або пройдіть перевірку у відкритому браузері.
update_wait_check|Дождитесь завершения проверки обновлений, затем повторите загрузку.|Wait for the update check to finish, then download again.|Дочекайтеся завершення перевірки оновлень, потім повторіть завантаження.
updates|Обновления|Updates|Оновлення
update_available|Доступна XAnty {version}|XAnty {version} is available|Доступна XAnty {version}
update_banner_text|Посмотрите изменения и обновите приложение в удобный момент.|Review the changes and update when convenient.|Перегляньте зміни та оновіть застосунок у зручний час.
update_details|Подробнее|Details|Докладніше
update_current|Текущая версия: {version}|Current version: {version}|Поточна версія: {version}
update_current_ok|Установлена актуальная версия.|You are up to date.|Встановлена актуальна версія.
update_not_configured|Канал обновлений ещё не подключён разработчиком. Проверка станет доступна после его подключения.|The developer has not connected the update channel yet. Update checks will become available once it is connected.|Розробник ще не підключив канал оновлень. Перевірка стане доступною після його підключення.
update_no_notes|Описание изменений не добавлено.|No release notes provided.|Опис змін не додано.
update_github|Открыть релиз на GitHub|Open release on GitHub|Відкрити реліз на GitHub
update_manual_only|Автообновление доступно в однофайловой Windows-сборке. Для этой версии скачайте приложение со страницы релиза.|Self-updating is available in the Windows onefile build. Download this version from the release page.|Автооновлення доступне в однофайловій Windows-збірці. Для цієї версії завантажте застосунок зі сторінки релізу.
update_check|Проверить обновления|Check for updates|Перевірити оновлення
update_download|Обновить|Update|Оновити
update_loading|Загрузка…|Downloading…|Завантаження…
update_downloading|Загружено {n}% · проверка SHA-256 после загрузки|Downloaded {n}% · SHA-256 verification follows|Завантажено {n}% · перевірка SHA-256 після завантаження
update_ready|Обновление загружено и проверено.|The update is downloaded and verified.|Оновлення завантажено й перевірено.
update_install|Установить и перезапустить|Install and restart|Встановити й перезапустити
update_close_profiles|Закройте все профили и дождитесь завершения переносов. XAnty перезапустится; аккаунты и сессии сохранятся.|Close all profiles and wait for transfers. XAnty will restart; accounts and sessions are preserved.|Закрийте всі профілі й дочекайтеся завершення перенесень. XAnty перезапуститься; акаунти та сесії збережуться.
update_restarting|Устанавливаем обновление. XAnty сейчас закроется и откроется снова.|Installing the update. XAnty will close and reopen.|Встановлюємо оновлення. XAnty зараз закриється й відкриється знову.
update_previous_failed|Предыдущее обновление не удалось установить. Повторите загрузку.|The previous update could not be installed. Download it again.|Попереднє оновлення не вдалося встановити. Повторіть завантаження.
update_no_release|Публичный релиз не найден. Опубликуйте первый релиз и проверьте адрес репозитория.|No public release found. Publish the first release and check the repository name.|Публічний реліз не знайдено. Опублікуйте перший реліз і перевірте адресу репозиторію.
update_network|Не удалось подключиться к GitHub. Проверьте соединение и повторите попытку.|Cannot connect to GitHub. Check your connection and retry.|Не вдалося підключитися до GitHub. Перевірте з’єднання та повторіть спробу.
update_hash|Контрольная сумма обновления не совпала. Файл не установлен. Повторите загрузку.|The update checksum does not match. The file was not installed. Download again.|Контрольна сума оновлення не збіглася. Файл не встановлено. Повторіть завантаження.
update_busy_profiles|Перед установкой обновления закройте все профили.|Close all profiles before installing the update.|Перед встановленням оновлення закрийте всі профілі.
update_busy_actions|Дождитесь завершения запуска и закрытия профилей.|Wait for profile start and close actions to finish.|Дочекайтеся завершення запуску й закриття профілів.
update_busy_transfer|Дождитесь завершения переноса профилей перед обновлением.|Wait for profile transfers before updating.|Дочекайтеся завершення перенесення профілів перед оновленням.
update_download_failed|Не удалось загрузить обновление. Проверьте соединение и свободное место.|Cannot download the update. Check the connection and free disk space.|Не вдалося завантажити оновлення. Перевірте з’єднання й вільне місце.
update_write_failed|Не удалось подготовить обновление. Проверьте доступ на запись в папку программы.|Cannot prepare the update. Check write access to the application folder.|Не вдалося підготувати оновлення. Перевірте доступ на запис до папки програми.
workspace|Рабочее пространство|Workspace|Робочий простір
profiles|Профили браузера|Browser profiles|Профілі браузера
all_profiles|Все профили|All profiles|Усі профілі
unfiled|Без папки|No folder|Без папки
folders|Папки|Folders|Папки
find_folder|Найти папку|Find a folder|Знайти папку
create_folder|Создать папку|Create folder|Створити папку
rename_folder|Переименовать папку|Rename folder|Перейменувати папку
delete_folder|Удалить папку|Delete folder|Видалити папку
folder_name|Название папки|Folder name|Назва папки
folder|Папка|Folder|Папка
search|Имя, папка, IP или регион…|Name, folder, IP or region…|Ім’я, папка, IP або регіон…
new_profile|Создать профиль|Create profile|Створити профіль
from_dolphin|Из Dolphin|From Dolphin|З Dolphin
transfer|Передать профили|Transfer profiles|Передати профілі
transfers|Переносы|Transfers|Перенесення
load|Нагрузка|Performance|Навантаження
language|Язык интерфейса|Interface language|Мова інтерфейсу
theme|Сменить тему|Switch theme|Змінити тему
help|Справка|Help|Довідка
exit|Выйти|Exit|Вийти
exit_question|Закрыть все браузеры и выйти из XAnty?|Close all browsers and exit XAnty?|Закрити всі браузери та вийти з XAnty?
connected|Подключено|Connected|Підключено
connecting|Подключение…|Connecting…|Підключення…
disconnected|Нет соединения|Disconnected|Немає з’єднання
local|Локальное приложение|Local application|Локальний застосунок
offline_title|Подключаемся к XAnty|Connecting to XAnty|Підключаємося до XAnty
offline_text|Локальный сервис недоступен. Соединение восстановится автоматически.|The local service is unavailable. Reconnecting automatically.|Локальний сервіс недоступний. З’єднання відновиться автоматично.
setup_title|Добро пожаловать в XAnty|Welcome to XAnty|Ласкаво просимо до XAnty
setup_text|Выберите рабочую папку для профилей, аккаунтов и логов.|Choose a workspace folder for profiles, accounts and logs.|Виберіть робочу папку для профілів, акаунтів і журналів.
base_dir|Рабочая папка|Workspace folder|Робоча папка
create_dir|Создать папку, если её нет|Create folder if missing|Створити папку, якщо її немає
required_files|В рабочей папке должны находиться:|The workspace should contain:|У робочій папці мають бути:
continue|Продолжить|Continue|Продовжити
overview|Профили и сессии в одном месте|Your profiles and sessions in one place|Профілі та сесії в одному місці
total|Всего|Total|Усього
opened|Запущено|Running|Запущено
errors|Ошибки|Errors|Помилки
status|Статус|Status|Статус
all_statuses|Все статусы|All statuses|Усі статуси
closed|Закрыт|Closed|Закритий
open|Открыт|Open|Відкритий
signed_in|Вход выполнен|Signed in|Вхід виконано
attention|Нужна проверка|Needs attention|Потрібна перевірка
opening|Запускается…|Starting…|Запускається…
closing|Закрывается…|Closing…|Закривається…
name|Название профиля|Profile name|Назва профілю
username|Логин X|X username|Логін X
username_hint|Без @. Например, my_account.|Without @. For example, my_account.|Без @. Наприклад, my_account.
proxy|Прокси|Proxy|Проксі
no_proxy|Не указан|Not set|Не вказано
proxy_hint|HTTP-прокси: host:port:login:password или http://login:password@host:port|HTTP proxy: host:port:login:password or http://login:password@host:port|HTTP-проксі: host:port:login:password або http://login:password@host:port
check_proxy|Проверить прокси|Check proxy|Перевірити проксі
checking_proxy|Проверяем прокси…|Checking proxy…|Перевіряємо проксі…
proxy_failed|Проверка прокси не пройдена|Proxy check failed|Перевірку проксі не пройдено
search_config_failed|Не удалось настроить поиск Chrome. Попробуйте открыть профиль ещё раз.|Could not configure Chrome search. Try opening the profile again.|Не вдалося налаштувати пошук Chrome. Спробуйте відкрити профіль ще раз.
proxy_ok|Прокси работает: {ip}|Proxy works: {ip}|Проксі працює: {ip}
auto_login|Автовход в X|X auto-login|Автовхід у X
auto_hint|При открытии использовать сохранённую сессию, токен или пароль X.|Use the saved session, token or X password when opening.|Під час відкриття використовувати збережену сесію, токен або пароль X.
last_launch|Последний запуск|Last opened|Останній запуск
actions|Действия|Actions|Дії
start|Запустить|Start|Запустити
stop|Остановить|Stop|Зупинити
stop_all|Закрыть все браузеры|Close all browsers|Закрити всі браузери
show_browser|Показать окно|Show window|Показати вікно
edit|Редактировать|Edit|Редагувати
edit_profile|Редактировать профиль|Edit profile|Редагувати профіль
bulk_edit|Изменить выбранные|Edit selected|Змінити вибрані
move|В папку|Move to folder|До папки
delete|Удалить|Delete|Видалити
delete_question|Удалить выбранные профили ({n})? Браузеры будут закрыты.|Delete selected profiles ({n})? Their browsers will close.|Видалити вибрані профілі ({n})? Браузери буде закрито.
folder_delete_question|Удалить папку «{name}»? Профили останутся в разделе «Без папки».|Delete folder “{name}”? Its profiles will remain under No folder.|Видалити папку «{name}»? Профілі залишаться в розділі «Без папки».
selected|Выбрано: {n}|Selected: {n}|Вибрано: {n}
select_all|Выбрать все профили|Select every profile|Вибрати всі профілі
clear_selection|Снять выделение|Clear selection|Зняти виділення
choose_profiles|Сначала выберите профили в таблице.|Select profiles in the table first.|Спочатку виберіть профілі в таблиці.
shown|{from}–{to} из {total}|{from}–{to} of {total}|{from}–{to} з {total}
page_size|На странице|Per page|На сторінці
previous|Назад|Previous|Назад
next|Вперёд|Next|Далі
empty_title|Здесь будут ваши профили|Your profiles will appear here|Тут будуть ваші профілі
empty_text|Перенесите все профили из Dolphin по API или создайте новый профиль.|Import every Dolphin profile via API or create a new profile.|Перенесіть усі профілі з Dolphin через API або створіть новий профіль.
no_matches|По вашему запросу ничего не найдено|No matching profiles|За вашим запитом нічого не знайдено
reset_filters|Сбросить фильтры|Reset filters|Скинути фільтри
refresh|Обновить|Refresh|Оновити
save|Сохранить|Save|Зберегти
saved|Сохранено|Saved|Збережено
cancel|Отмена|Cancel|Скасувати
close|Закрыть|Close|Закрити
done|Готово|Done|Готово
password_x|Пароль аккаунта X|X account password|Пароль акаунта X
auth_token|Токен auth_token|auth_token|Токен auth_token
ct0_token|Токен ct0|ct0|Токен ct0
notes|Заметки|Notes|Нотатки
browser_settings|Настройки браузера|Browser settings|Налаштування браузера
browser_language|Язык браузера|Browser language|Мова браузера
timezone|Часовой пояс|Time zone|Часовий пояс
width|Ширина окна|Window width|Ширина вікна
height|Высота окна|Window height|Висота вікна
system_default|Как в системе|System default|Як у системі
next_open|Настройки браузера применятся при следующем запуске профиля.|Browser settings apply the next time the profile opens.|Налаштування браузера застосуються під час наступного запуску профілю.
keep|Не менять|Keep unchanged|Не змінювати
enable|Включить|Enable|Увімкнути
disable|Выключить|Disable|Вимкнути
change_folder|Изменить папку|Change folder|Змінити папку
change_proxy|Изменить прокси|Change proxy|Змінити проксі
bulk_proxy_hint|Один прокси для всех или по одному на строку в порядке выбранных профилей.|One proxy for all, or one per line in the selected profile order.|Один проксі для всіх або по одному на рядок у порядку вибраних профілів.
apply|Применить|Apply|Застосувати
reset_errors|Сбросить ошибки|Reset errors|Скинути помилки
cookies_import|Импорт cookies X|Import X cookies|Імпорт cookies X
cookies_export|Экспорт cookies X|Export X cookies|Експорт cookies X
cookies_hint|Загрузите JSON/Netscape или вставьте cookies. Профиль должен быть закрыт.|Choose a JSON/Netscape file or paste cookies. Close the profile first.|Завантажте JSON/Netscape або вставте cookies. Профіль має бути закритий.
cookies_file|Файл cookies|Cookies file|Файл cookies
paste_cookies|Вставьте cookies сюда|Paste cookies here|Вставте cookies сюди
cookies_saved|Cookies сохранены. Для входа включите автовход в X.|Cookies saved. Enable X auto-login to sign in.|Cookies збережено. Для входу увімкніть автовхід у X.
text_import|Импорт списком|Import from text|Імпорт списком
text_import_hint|Одна строка на профиль в формате:|One profile per line in this format:|Один рядок на профіль у форматі:
import|Импортировать|Import|Імпортувати
text_imported|Добавлено: {n}. Пропущено: {skipped}.|Added: {n}. Skipped: {skipped}.|Додано: {n}. Пропущено: {skipped}.
dolphin_title|Перенос всех профилей из Dolphin|Import every Dolphin profile|Перенесення всіх профілів з Dolphin
dolphin_intro|Вставьте API-токен. XAnty сам найдёт и перенесёт все доступные профили и папки, без ввода ID и ограничения количества.|Paste your API token. XAnty finds and imports every available profile and folder, without profile IDs or a profile count limit.|Вставте API-токен. XAnty сам знайде й перенесе всі доступні профілі та папки, без введення ID та обмеження кількості.
api_token|API-токен Dolphin|Dolphin API token|API-токен Dolphin
token_placeholder|Вставьте API-токен из личного кабинета Dolphin|Paste the API token from your Dolphin account|Вставте API-токен з особистого кабінету Dolphin
import_all_dolphin|Перенести все профили|Import every profile|Перенести всі профілі
advanced|Дополнительные настройки|Advanced settings|Додаткові налаштування
dolphin_password|Общий пароль защищённых профилей (если есть)|Shared password for protected profiles (if any)|Спільний пароль захищених профілів (якщо є)
dolphin_details|Переносятся имена, папки, заметки, настройки, HTTP-прокси и доступные cookies всех сайтов. Полный отпечаток, расширения и local storage Dolphin через этот API недоступны.|Transfers names, folders, notes, settings, HTTP proxies and available cookies from every site. The full Dolphin fingerprint, extensions and local storage are unavailable through this API.|Переносяться імена, папки, нотатки, налаштування, HTTP-проксі та доступні cookies всіх сайтів. Повний відбиток, розширення та local storage Dolphin через цей API недоступні.
dolphin_limits|Dolphin разрешает экспорт cookies на платном тарифе с облачной синхронизацией. Недоступные данные будут отмечены в отчёте. Токен не сохраняется.|Dolphin requires a paid plan with cloud sync to export cookies. Unavailable data is listed in the report. The token is not stored.|Dolphin дозволяє експорт cookies на платному тарифі з хмарною синхронізацією. Недоступні дані буде позначено у звіті. Токен не зберігається.
transfer_title|Передача профилей|Profile transfer|Передавання профілів
transfer_intro|Создайте файл .xanty и передайте его другому человеку. Он импортирует файл в своей программе и получит профили с настройками, прокси, cookies и данными браузера.|Create a .xanty file and give it to the recipient. They import it into their app to receive profiles with settings, proxies, cookies and browser data.|Створіть файл .xanty та передайте його іншій людині. Вона імпортує файл у своїй програмі й отримає профілі з налаштуваннями, проксі, cookies та даними браузера.
export_selected|Передать выбранные ({n})|Export selected ({n})|Передати вибрані ({n})
export_all|Передать все профили ({n})|Export every profile ({n})|Передати всі профілі ({n})
export_one|Передать профиль файлом|Export profile to a file|Передати профіль файлом
export_package|Подготовка файла профилей|Preparing profile package|Підготовка файлу профілів
import_package|Получить профили из файла|Import profiles from a file|Отримати профілі з файлу
export_hint|Перед созданием файла закройте передаваемые профили. Кэш браузера в файл не включается.|Close the profiles before exporting. Browser caches are excluded from the package.|Перед створенням файлу закрийте профілі, що передаються. Кеш браузера до файлу не включається.
package_private|Файл содержит сессии и данные доступа к прокси. Передавайте его только получателю профилей.|The package contains sessions and proxy credentials. Share it only with the intended recipient.|Файл містить сесії та дані доступу до проксі. Передавайте його лише одержувачу профілів.
package_limits|Для отдельных сайтов может понадобиться повторный вход. Сохранённые пароли Chrome и ключи расширений могут быть привязаны к исходному компьютеру.|Some sites may require signing in again. Saved Chrome passwords and extension keys may be bound to the original computer.|Для окремих сайтів може знадобитися повторний вхід. Збережені паролі Chrome та ключі розширень можуть бути прив’язані до вихідного комп’ютера.
choose_package|Выберите файл .xanty|Choose a .xanty file|Виберіть файл .xanty
duplicates|Если имя профиля уже существует|If a profile name already exists|Якщо ім’я профілю вже існує
rename_duplicates|Создать копию с новым именем|Create a copy with a new name|Створити копію з новим ім’ям
skip_duplicates|Пропустить существующий профиль|Skip the existing profile|Пропустити наявний профіль
importing_file|Импорт профилей из файла|Importing profiles from a file|Імпорт профілів з файлу
uploading|Загрузка файла: {pct}%|Uploading file: {pct}%|Завантаження файлу: {pct}%
download|Сохранить файл|Save file|Зберегти файл
report|Скачать отчёт|Download report|Завантажити звіт
show_report|Открыть отчёт|View report|Відкрити звіт
background_hint|Можно закрыть это окно. Перенос продолжится в разделе «Переносы», пока XAnty работает.|You can close this dialog. The operation continues under Transfers while XAnty is running.|Можна закрити це вікно. Перенесення продовжиться в розділі «Перенесення», доки XAnty працює.
listing|Получаем список всех профилей…|Finding every profile…|Отримуємо список усіх профілів…
importing|Импортируем профили|Importing profiles|Імпортуємо профілі
exporting|Создаём файл профилей|Creating profile package|Створюємо файл профілів
starting|Подготовка…|Preparing…|Підготовка…
completed|Завершено|Completed|Завершено
cancelled|Остановлено|Stopped|Зупинено
failed|Не удалось завершить|Could not complete|Не вдалося завершити
running|Выполняется|Running|Виконується
stopping|Останавливаем…|Stopping…|Зупиняємо…
processed|Обработано: {n} из {total}|Processed: {n} of {total}|Оброблено: {n} з {total}
result_counts|Добавлено: {added} · Пропущено: {skipped} · Ошибок: {errors}|Added: {added} · Skipped: {skipped} · Errors: {errors}|Додано: {added} · Пропущено: {skipped} · Помилок: {errors}
warnings_count|Профилей с замечаниями: {n}|Profiles with notices: {n}|Профілів із зауваженнями: {n}
no_jobs|Пока нет переносов|No transfers yet|Перенесень ще немає
no_jobs_text|Здесь отображаются импорт из Dolphin и передача профилей через файл.|Dolphin imports and profile package transfers appear here.|Тут відображаються імпорт із Dolphin і передавання профілів через файл.
monitor|Журнал событий|Activity log|Журнал подій
clear|Очистить|Clear|Очистити
copy|Копировать|Copy|Копіювати
copied|Скопировано|Copied|Скопійовано
log_search|Поиск в журнале|Search activity log|Пошук у журналі
no_logs|Новые события появятся здесь|New activity appears here|Нові події з’являться тут
performance_text|Нагрузка компьютера и запущенных браузерных профилей|Computer and browser profile resource usage|Навантаження комп’ютера та запущених профілів браузера
waiting_metrics|Ожидаем первый замер…|Waiting for the first sample…|Очікуємо перше вимірювання…
cpu|Процессор|CPU|Процесор
memory|Оперативная память|Memory|Оперативна пам’ять
browser_memory|Память Chrome|Chrome memory|Пам’ять Chrome
loop_lag|Задержка интерфейса|Event loop delay|Затримка інтерфейсу
processes|Процессы|Processes|Процеси
threads|Потоки|Threads|Потоки
cpu_history|История нагрузки|Resource history|Історія навантаження
per_profile|По профилям|Per profile|За профілями
help_text|Создавайте профили вручную или переносите их из Dolphin одним API-токеном. Для передачи другому пользователю выберите профили и нажмите «Передать профили». Получатель импортирует файл .xanty. Язык меняется внизу боковой панели. Для запуска браузеров в рабочей папке нужны Bro/chrome.exe и Drivers/chromedriver.exe.|Create profiles manually or import them from Dolphin using one API token. To share with another user, select profiles and choose Transfer profiles. The recipient imports the .xanty file. Change language at the bottom of the sidebar. Browser launches require Bro/chrome.exe and Drivers/chromedriver.exe in the workspace.|Створюйте профілі вручну або переносьте їх із Dolphin одним API-токеном. Для передавання іншому користувачу виберіть профілі та натисніть «Передати профілі». Одержувач імпортує файл .xanty. Мова змінюється внизу бічної панелі. Для запуску браузерів у робочій папці потрібні Bro/chrome.exe та Drivers/chromedriver.exe.
error|Ошибка|Error|Помилка
details|Подробности|Details|Подробиці
added|Добавлен|Added|Додано
imported|Импортирован|Imported|Імпортовано
prepared|Подготовлен|Prepared|Підготовлено
exported|Экспортирован|Exported|Експортовано
skipped|Пропущен|Skipped|Пропущено
transfer_busy|Уже выполняется другой перенос. Дождитесь завершения.|Another transfer is running. Wait for it to finish.|Уже виконується інше перенесення. Дочекайтеся завершення.
close_before_export|Сначала закройте передаваемые профили.|Close the profiles before exporting.|Спочатку закрийте профілі, що передаються.
token_required|Вставьте API-токен Dolphin.|Paste your Dolphin API token.|Вставте API-токен Dolphin.
invalid_token|API-токен Dolphin недействителен или истёк.|The Dolphin API token is invalid or expired.|API-токен Dolphin недійсний або прострочений.
api_unavailable|Не удалось подключиться к API Dolphin.|Could not connect to the Dolphin API.|Не вдалося підключитися до API Dolphin.
no_profiles_export|Нет профилей для передачи.|No profiles to export.|Немає профілів для передавання.
cookies_missing|Нет сохранённых cookies X для этого профиля.|No saved X cookies for this profile.|Немає збережених cookies X для цього профілю.
close_before_cookies|Закройте профиль перед импортом cookies.|Close the profile before importing cookies.|Закрийте профіль перед імпортом cookies.
choose_file|Сначала выберите файл.|Choose a file first.|Спочатку виберіть файл.
paid_plan|Для этой операции Dolphin требует платный тариф.|Dolphin requires a paid plan for this operation.|Для цієї операції Dolphin вимагає платний тариф.
no_dolphin_access|Нет доступа к этому профилю Dolphin.|No access to this Dolphin profile.|Немає доступу до цього профілю Dolphin.
profile_api_missing|Профиль или постраничная выдача API Dolphin недоступны.|The Dolphin profile or cursor pagination is unavailable.|Профіль або посторінкова видача API Dolphin недоступні.
cookie_export_unavailable|Cookies недоступны: {reason}|Cookies unavailable: {reason}|Cookies недоступні: {reason}
profile_details_unavailable|Настройки профиля недоступны: {reason}|Profile details unavailable: {reason}|Налаштування профілю недоступні: {reason}
empty_remote_cookies|Dolphin не вернул cookies. Проверьте сессию вручную.|Dolphin returned no cookies. Check the session manually.|Dolphin не повернув cookies. Перевірте сесію вручну.
no_x_cookies|В профиле нет cookies X/Twitter.|No X/Twitter cookies in this profile.|У профілі немає cookies X/Twitter.
unsupported_proxy|Этот тип прокси пока не поддерживается. Добавьте HTTP-прокси в XAnty.|This proxy type is not supported yet. Add an HTTP proxy in XAnty.|Цей тип проксі поки не підтримується. Додайте HTTP-проксі в XAnty.
missing_proxy|Добавьте HTTP-прокси перед запуском профиля.|Add an HTTP proxy before opening the profile.|Додайте HTTP-проксі перед запуском профілю.
incomplete_proxy|Dolphin не вернул полный адрес прокси. Укажите его в XAnty.|Dolphin did not provide the complete proxy address. Set it in XAnty.|Dolphin не повернув повну адресу проксі. Вкажіть її в XAnty.
source_os|Исходный профиль использует другую ОС. XAnty запускает Chrome для Windows.|The source profile uses a different OS. XAnty runs Windows Chrome.|Вихідний профіль використовує іншу ОС. XAnty запускає Chrome для Windows.
internal_username|Создан внутренний идентификатор. Исходное название профиля Dolphin сохранено.|An internal username was generated. The original Dolphin profile name is preserved.|Створено внутрішній ідентифікатор. Вихідну назву профілю Dolphin збережено.
already_imported|Этот профиль уже перенесён.|This profile is already imported.|Цей профіль уже перенесено.
session_decrypt|Не удалось расшифровать cookies: {n}. Откройте и закройте профиль в XAnty, затем повторите экспорт.|Could not decrypt {n} cookies. Open and close the profile in XAnty, then export again.|Не вдалося розшифрувати cookies: {n}. Відкрийте й закрийте профіль у XAnty, потім повторіть експорт.
read_session_failed|Не удалось прочитать сохранённую сессию браузера.|Could not read the saved browser session.|Не вдалося прочитати збережену сесію браузера.
invalid_package|Не удалось прочитать пакет профилей XAnty.|Could not read the XAnty profile package.|Не вдалося прочитати пакет профілів XAnty.
unsafe_package|Файл содержит недопустимые пути. Импорт отменён.|The package contains unsafe paths. Import was rejected.|Файл містить неприпустимі шляхи. Імпорт скасовано.
package_version|Эта версия файла .xanty не поддерживается.|This .xanty package version is not supported.|Ця версія файлу .xanty не підтримується.
profile_list_changed|Список профилей изменился во время импорта. Повторите попытку.|The profile list changed during import. Please retry.|Список профілів змінився під час імпорту. Повторіть спробу.
proxy_auth_failed|Ошибка авторизации прокси (407). Проверьте логин и пароль.|Proxy authentication failed (407). Check login and password.|Помилка авторизації проксі (407). Перевірте логін і пароль.
proxy_connect_failed|Не удалось подключиться через прокси. Проверьте адрес, порт и доступ.|Could not connect through the proxy. Check host, port and access.|Не вдалося підключитися через проксі. Перевірте адресу, порт і доступ.
proxy_timeout|Прокси не ответил вовремя. Проверьте адрес и сеть.|The proxy timed out. Check the address and network.|Проксі не відповів вчасно. Перевірте адресу та мережу.
chrome_start_failed|Не удалось запустить Chrome. Проверьте пути и совместимость Chrome и ChromeDriver.|Chrome could not start. Check Chrome and ChromeDriver paths and versions.|Не вдалося запустити Chrome. Перевірте шляхи та сумісність Chrome і ChromeDriver.
http_api_error|Dolphin API вернул HTTP {status}.|Dolphin API returned HTTP {status}.|Dolphin API повернув HTTP {status}.
`;
  const messages = Object.fromEntries(rows.trim().split('\n').map(line => { const [key, ...values] = line.split('|'); return [key, values]; }));
  let language = 'ru';
  function t(key, values = {}) {
    const row = messages[key];
    return (row ? row[{ru: 0, en: 1, uk: 2}[language]] : key).replace(/\{(\w+)\}/g, (all, name) => values[name] ?? all);
  }
  function localize(root = document) {
    root.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = t(el.dataset.i18nTitle); });
    root.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    root.querySelectorAll('[data-language]').forEach(el => { el.value = language; });
  }
  function set(value) {
    language = ['ru', 'en', 'uk'].includes(value) ? value : 'ru';
    document.documentElement.lang = language;
    localize();
    document.dispatchEvent(new CustomEvent('languagechange'));
  }
  const errors = {'Another transfer operation is running': 'transfer_busy', 'Profile transfer is running; wait for it to finish': 'transfer_busy', 'Close the selected profiles before exporting': 'close_before_export', 'Enter a Dolphin API token': 'token_required', 'Invalid or expired Dolphin API token': 'invalid_token', 'Cannot connect to the Dolphin API': 'api_unavailable', 'No profiles to export': 'no_profiles_export', 'No saved cookies for this profile': 'cookies_missing', 'Close this profile before importing cookies': 'close_before_cookies', 'Operation cancelled': 'cancelled'};
  Object.assign(errors, {
    'Dolphin requires a paid plan for this operation':'paid_plan',
    'Proxy location is unavailable. The proxy IP check succeeded.':'proxy_geo_failed',
    'Proxy changed during the check. Please check it again.':'proxy_changed',
    'Browser launch or sign-in timed out (240s). Check the proxy and try again.':'launch_timeout',
    'BROWSER ERROR':'launch_failed','BROWSER TIMEOUT':'launch_timeout','LOGIN TIMEOUT':'launch_timeout',
    'LOGIN FAILED':'sign_in_failed','PROXY ERROR':'proxy_connect_failed','RELOGIN FAILED':'sign_in_failed',
    'Wait for the update check to finish before downloading.':'update_wait_check',
    'Close all profiles before installing the update.':'update_busy_profiles',
    'Close all profiles and wait for current actions before installing the update.':'update_busy_actions',
    'Wait for profile operations and transfers to finish before installing the update.':'update_busy_transfer',
    'Wait for the profile transfer to finish before installing the update.':'update_busy_transfer',
    'No public GitHub release found. Publish the first release and check the repository name.':'update_no_release',
    'Cannot connect to GitHub. Check your connection and try again.':'update_network',
    'The update SHA-256 does not match. The file was discarded; download it again.':'update_hash',
    'Cannot download the update. Check your connection and free disk space.':'update_download_failed',
    'Cannot prepare the update. Check write access to the application folder.':'update_write_failed', 'No access to this Dolphin profile':'no_dolphin_access',
    'Dolphin profile or cursor pagination is unavailable':'profile_api_missing',
    'Dolphin returned no cookies; sign-in must be checked manually':'empty_remote_cookies',
    'No X/Twitter cookies in the Dolphin profile':'no_x_cookies', 'No X/Twitter cookies found':'no_x_cookies',
    'Unsupported proxy type; add an HTTP proxy in XAnty':'unsupported_proxy',
    'No proxy; add an HTTP proxy before opening':'missing_proxy',
    'Proxy is not configured. Add an HTTP proxy before opening the profile.':'missing_proxy',
    'Dolphin did not provide the full proxy address; add it in XAnty':'incomplete_proxy',
    'Dolphin proxy is incomplete or invalid; add an HTTP proxy in XAnty':'incomplete_proxy',
    'Source OS differs from the Windows Chrome used by XAnty':'source_os',
    'An internal username was generated; the original Dolphin profile name is preserved':'internal_username',
    'Already imported':'already_imported', 'This Dolphin profile is already imported':'already_imported',
    'Could not read the local browser cookie database':'read_session_failed', 'Could not read the saved portable session':'read_session_failed',
    'Could not read the XAnty profile package':'invalid_package', 'This is not a valid XAnty profile package':'invalid_package',
    'Unsafe path in profile package':'unsafe_package', 'Unexpected file in profile package':'unsafe_package',
    'Unsupported XAnty profile package version':'package_version',
    'Profile package is missing session files. Export the profiles again.':'package_missing_session',
    'Cannot save profile files. Check write access to the workspace folder.':'workspace_access',
    'Not enough disk space to import profiles. Free space in the workspace folder.':'workspace_space',
    'Profile list changed during import; please retry':'profile_list_changed',
    'Proxy authentication failed (407). Check login and password.':'proxy_auth_failed',
    'Cannot connect through the proxy. Check host, port and access.':'proxy_connect_failed',
    'Proxy timed out. Check the address and network.':'proxy_timeout',
    'Chrome could not start. Check Chrome and ChromeDriver paths/versions.':'chrome_start_failed',
    'Could not configure Chrome search. Try opening the profile again.':'search_config_failed'
  });
  function error(value) {
    const text=String(value);
    if(text.startsWith('Ошибка входа: '))return error(text.slice(14));
    if(errors[text]) return t(errors[text]);
    if(text.startsWith('Cookies unavailable: '))return t('cookie_export_unavailable',{reason:error(text.slice(21))});
    if(text.startsWith('Profile details unavailable: '))return t('profile_details_unavailable',{reason:error(text.slice(29))});
    const decrypt=text.match(/^(\d+) browser cookies could not be decrypted/);
    if(decrypt)return t('session_decrypt',{n:decrypt[1]});
    const http=text.match(/^Dolphin API returned HTTP (\d+)/);
    if(http)return t('http_api_error',{status:http[1]});
    return text;
  }
  return {t, set, localize, error, get language() { return language; }, messages};
})();
const t = I18N.t;
