'use strict';
const I18N = (() => {
  const rows = `
profiles_retry|Повторить|Try again|Повторити
profiles_sort|Сортировка профилей|Profile order|Сортування профілів
profiles_sort_favorites|Избранные сверху|Favorites first|Обрані зверху
profiles_sort_number|По номеру|By number|За номером
profiles_sort_name|По названию|By name|За назвою
profiles_sort_recent|Недавно запускались|Recently launched|Нещодавно запущені
profiles_result_count|{n} из {total} профилей|{n} of {total} profiles|{n} із {total} профілів
profiles_page|Страница|Page|Сторінка
profiles_page_jump|Перейти на страницу|Go to page|Перейти на сторінку
profiles_loading|Обновляем список профилей…|Refreshing profiles…|Оновлюємо список профілів…
profiles_load_error|Не удалось обновить список. Показаны последние данные.|Could not refresh. Showing the last available data.|Не вдалося оновити список. Показано останні дані.
profiles_no_matches_hint|Попробуйте другое имя, тег или сбросьте фильтры.|Try another name, tag, or reset the filters.|Спробуйте іншу назву, тег або скиньте фільтри.
profiles_folder_empty|В этой папке пока нет профилей|This folder has no profiles yet|У цій папці поки немає профілів
profiles_folder_empty_hint|Добавьте профиль или переместите существующие через массовые действия.|Add a profile or move existing profiles using bulk actions.|Додайте профіль або перемістіть наявні через масові дії.
profiles_menu_manage|Управление|Manage|Керування
profiles_menu_session|Прокси и сессия|Proxy and session|Проксі та сесія
profiles_menu_profile|Файлы профиля|Profile files|Файли профілю
rotation_invalid|Введите корректную ссылку ротации с http:// или https://.|Enter a valid http:// or https:// rotation link.|Введіть коректне посилання ротації з http:// або https://.
rotation_missing|Добавьте ссылку ротации в настройках профиля.|Add a rotation link in the profile settings.|Додайте посилання ротації в налаштуваннях профілю.
rotation_busy|Ротация по этой ссылке уже выполняется. Дождитесь её завершения.|This link is already being used for rotation. Wait until it finishes.|Ротація за цим посиланням уже виконується. Дочекайтеся завершення.
rotation_wait_profile|Дождитесь завершения текущих операций с профилем перед сменой IP.|Wait for the current profile operations before rotating the IP.|Дочекайтеся завершення поточних операцій із профілем перед зміною IP.
rotation_settings_changed|Настройки прокси изменились во время ротации. Проверьте текущий IP.|Proxy settings changed during rotation. Check the current IP.|Налаштування проксі змінилися під час ротації. Перевірте поточний IP.
rotation_rate_limited|Слишком частая смена IP. Подождите и повторите попытку.|IP rotation is rate limited. Wait and try again.|Занадто часта зміна IP. Зачекайте та повторіть спробу.
rotation_rejected|Провайдер отклонил ротацию. Проверьте ссылку и ограничения смены IP.|The provider rejected rotation. Check the link and rotation limits.|Провайдер відхилив ротацію. Перевірте посилання та обмеження зміни IP.
rotation_timeout|Время ожидания ротации истекло. Запрос мог дойти до провайдера; проверьте IP перед повторной ротацией.|Rotation timed out. The request may have reached the provider; check the IP before trying again.|Час очікування ротації минув. Запит міг дійти до провайдера; перевірте IP перед повторною ротацією.
rotation_unreachable|Не удалось отправить запрос на ротацию. Проверьте ссылку и подключение.|Cannot send the rotation request. Check the link and connection.|Не вдалося надіслати запит на ротацію. Перевірте посилання та з’єднання.
rotation_http|Провайдер ротации вернул HTTP {code}. Проверьте ссылку и ограничения смены IP.|Rotation provider returned HTTP {code}. Check the link and limits.|Провайдер ротації повернув HTTP {code}. Перевірте посилання та обмеження зміни IP.
proxy_rotation_url|Ссылка ротации прокси|Proxy rotation URL|Посилання ротації проксі
proxy_rotation_hint|Вставьте ссылку смены IP от провайдера прокси. Для ротации нажмите «Сменить IP» рядом с прокси.|Paste your provider's IP rotation link. Use Rotate IP next to the proxy to send the request.|Вставте посилання зміни IP від провайдера проксі. Для ротації натисніть «Змінити IP» біля проксі.
proxy_rotate|Сменить IP|Rotate IP|Змінити IP
proxy_rotating|Меняем IP…|Rotating IP…|Змінюємо IP…
proxy_rotation_changed|IP прокси изменён: {ip}|Proxy IP changed: {ip}|IP проксі змінено: {ip}
proxy_rotation_checked|Запрос на ротацию отправлен. Текущий IP: {ip}|Rotation requested. Current IP: {ip}|Запит на ротацію надіслано. Поточний IP: {ip}
proxy_rotation_unchanged|Запрос принят, но IP пока прежний: {ip}. Проверьте его немного позже.|Request accepted, but IP is still {ip}. Check it again shortly.|Запит прийнято, але IP поки попередній: {ip}. Перевірте його трохи пізніше.
proxy_rotation_pending|Запрос на ротацию отправлен, но проверить IP пока не удалось. Повторите проверку прокси немного позже.|Rotation requested, but the IP could not be checked yet. Check the proxy again shortly.|Запит на ротацію надіслано, але перевірити IP поки не вдалося. Перевірте проксі трохи пізніше.
whats_new|Что нового|What's new|Що нового
release_notes_title|Что нового в XAnty|What's new in XAnty|Що нового в XAnty
release_notes_intro|Посмотрите, что изменилось в этой версии. Список можно прокручивать.|See what changed in this version. Scroll to read more.|Перегляньте зміни в цій версії. Список можна прокручувати.
release_notes_continue|Продолжить работу|Continue to workspace|Продовжити роботу
release_notes_hint|Вернуться к этому списку можно в разделе «Обновления».|You can reopen these notes from Updates.|Повернутися до цього списку можна в розділі «Оновлення».
release_notes_saved|Описание установленной версии доступно и без интернета.|Installed release notes are available offline.|Опис установленої версії доступний і без інтернету.
profile_icon_text|Текст значка|Icon text|Текст піктограми
profile_icon_auto|Из названия профиля|From profile name|Із назви профілю
profile_icon_hint|До 8 символов на самой иконке. Короткий текст крупнее и легче читается. Применяется при следующем запуске профиля.|Up to 8 characters on the icon itself. Short text is larger and easier to read. Applied on next profile launch.|До 8 символів на самій піктограмі. Короткий текст більший і легше читається. Застосовується під час наступного запуску профілю.
desktop_hide_failed|Не удалось создать значок в области уведомлений. Окно оставлено открытым.|The notification icon is unavailable. The window has been kept open.|Не вдалося створити піктограму в області сповіщень. Вікно залишено відкритим.
browser_tools_settings|Настройки браузеров|Browser preferences|Налаштування браузерів
restore_tabs|Восстанавливать открытые вкладки|Restore open tabs|Відновлювати відкриті вкладки
extension_set|Набор расширений|Extension set|Набір розширень
extension_sets|Наборы расширений|Extension sets|Набори розширень
extensions_none|Без набора|No set|Без набору
extensions_portable|Сохранённый набор профиля|Saved profile set|Збережений набір профілю
extensions_hint|Создайте набор из папок распакованных расширений Chrome Manifest V3. Выберите его при создании профиля. Файлы копируются в профиль и переносятся вместе с ним.|Create a set from unpacked Chrome Manifest V3 extension folders. Select it when creating a profile. Files are copied into the profile and travel with it.|Створіть набір із папок розпакованих розширень Chrome Manifest V3. Виберіть його під час створення профілю. Файли копіюються до профілю та переносяться разом із ним.
extension_directories|Папки расширений|Extension folders|Папки розширень
extension_directories_hint|Полный путь к каждой папке с manifest.json, по одному в строке. Скачивание из магазина не выполняется.|One full path per line to a folder containing manifest.json. No store downloads are performed.|Повний шлях до кожної папки з manifest.json, по одному в рядку. Завантаження з магазину не виконується.
set_name|Название набора|Set name|Назва набору
save_set|Сохранить набор|Save set|Зберегти набір
no_extension_sets|Наборов пока нет|No extension sets yet|Наборів поки немає
delete_set_question|Удалить набор из списка? Копии расширений в существующих профилях сохранятся.|Delete this set from the list? Existing profile copies will remain.|Видалити набір зі списку? Копії розширень у наявних профілях збережуться.
session_autosave|Автоматически сохранять сессию|Save sessions automatically|Автоматично зберігати сесію
autosave_seconds|Интервал сохранения, секунд|Save interval, seconds|Інтервал збереження, секунд
autosave_hint|30–3600 секунд. Сохраняются cookies всех сайтов и адреса вкладок. Chrome сохраняет локальное хранилище самостоятельно. Несохранённые формы и состояние JavaScript не копируются.|30–3600 seconds. Saves cookies for all sites and tab URLs. Chrome maintains local storage itself. Unsaved forms and JavaScript state are not copied.|30–3600 секунд. Зберігаються cookies всіх сайтів та адреси вкладок. Chrome самостійно зберігає локальне сховище. Незбережені форми та стан JavaScript не копіюються.
save_session|Сохранить сессию сейчас|Save session now|Зберегти сесію зараз
session_saved|Сессия сохранена|Session saved|Сесію збережено
cookies_all|Cookies: просмотр и вставка|Cookies: view and paste|Cookies: перегляд і вставка
cookies_all_hint|Все сайты, включая HttpOnly cookies. Данные содержат сессии авторизации; храните их как пароли.|All sites, including HttpOnly cookies. This data includes signed-in sessions; treat it like passwords.|Усі сайти, включно з HttpOnly cookies. Дані містять сесії авторизації; зберігайте їх як паролі.
cookies_live|Открытый браузер|Live browser|Відкритий браузер
cookies_snapshot|Сохранённая сессия|Saved session|Збережена сесія
existing_cookies|Имеющиеся cookies|Existing cookies|Наявні cookies
paste_cookie_data|Вставить или загрузить cookies|Paste or load cookies|Вставити або завантажити cookies
cookies_close_first|Закройте профиль перед загрузкой cookies.|Close the profile before loading cookies.|Закрийте профіль перед завантаженням cookies.
cookies_merge_hint|JSON или Netscape. Новые cookies добавляются к существующим, совпадающие заменяются. Применяются при следующем запуске, даже без автовхода в X.|JSON or Netscape. New cookies are merged; matching cookies are replaced. Applied on next launch, including with X auto-login off.|JSON або Netscape. Нові cookies додаються до наявних, однакові замінюються. Застосовуються під час наступного запуску навіть без автовходу в X.
cookies_imported_all|Загружено cookies: {n}. Применятся при следующем запуске.|Loaded {n} cookies. Applied on next launch.|Завантажено cookies: {n}. Застосуються під час наступного запуску.
cookie_file_limit|Файл cookies должен быть не больше 16 МБ.|Cookie file must be 16 MB or smaller.|Файл cookies має бути не більшим за 16 МБ.
open_profile_folder|Открыть папку профиля|Open profile folder|Відкрити папку профілю
clear_cache|Очистить только кэш|Clear cache only|Очистити лише кеш
clear_cache_question|Очистить кэш закрытого профиля? Cookies, авторизация, вкладки, расширения и локальное хранилище сохранятся.|Clear this closed profile's cache? Cookies, sign-in, tabs, extensions and local storage will remain.|Очистити кеш закритого профілю? Cookies, авторизація, вкладки, розширення та локальне сховище збережуться.
cache_cleared|Кэш очищен: {n} файлов, {mb} МБ.|Cache cleared: {n} files, {mb} MB.|Кеш очищено: {n} файлів, {mb} МБ.
network_diagnostics|Проверка WebRTC / DNS|WebRTC / DNS check|Перевірка WebRTC / DNS
diagnostics_hint|Проверка выполняется в выбранном браузере через ipify, Google STUN и dnsleak.dev. Сервисы видят тестовые сетевые запросы. Пользовательские вкладки сохраняются.|Runs in the selected browser using ipify, Google STUN and dnsleak.dev. These services receive the test network requests. Your tabs are preserved.|Перевірка виконується у вибраному браузері через ipify, Google STUN та dnsleak.dev. Сервіси отримують тестові мережеві запити. Вкладки користувача зберігаються.
diagnostics_running|Проверяем сеть профиля…|Checking the profile network…|Перевіряємо мережу профілю…
diagnostics_unavailable|Не удалось завершить проверку. Результат не подтверждён.|Could not complete the check. Result is unverified.|Не вдалося завершити перевірку. Результат не підтверджено.
browser_ip|Внешний IP браузера|Browser public IP|Зовнішній IP браузера
browser_ip_changed|IP отличается от адреса при запуске. Проверьте маршрут и ротацию прокси.|IP differs from launch-time IP. Check routing and proxy rotation.|IP відрізняється від адреси під час запуску. Перевірте маршрут і ротацію проксі.
diagnostic_matched|Совпадает с IP браузера|Matches browser IP|Збігається з IP браузера
diagnostic_warning|Нужна проверка|Needs review|Потрібна перевірка
diagnostic_observed|Резолверы измерены|Resolvers observed|Резолвери виміряно
diagnostic_inconclusive|Не подтверждено|Inconclusive|Не підтверджено
rtc_mismatch|Другие публичные IP в WebRTC|Other public WebRTC IPs|Інші публічні IP у WebRTC
rtc_hint|Отличающийся публичный IP может указывать на обход прокси. Отсутствие кандидатов не доказывает отсутствие утечек.|A different public IP may indicate proxy bypass. No candidates does not prove that there are no leaks.|Інша публічна IP-адреса може свідчити про обхід проксі. Відсутність кандидатів не доводить відсутності витоків.
dns_lookups|Получено DNS-запросов: {n} из {total}|DNS lookups observed: {n} of {total}|Отримано DNS-запитів: {n} із {total}
dns_hint|Сравните операторов с ожидаемыми DNS прокси/VPN. Другая страна или публичный DNS сами по себе не доказывают утечку; неполный тест не считается успешным.|Compare operators with your expected proxy/VPN DNS. Another country or a public resolver alone does not prove a leak; incomplete tests are not passes.|Порівняйте операторів з очікуваними DNS проксі/VPN. Інша країна або публічний DNS самі по собі не доводять витоку; неповний тест не вважається успішним.
package_integrity_hint|Новые пакеты проверяются по SHA-256 перед импортом. Старые пакеты без контрольных сумм показывают предупреждение.|New packages are verified with SHA-256 before import. Legacy packages without checksums show a warning.|Нові пакети перевіряються за SHA-256 перед імпортом. Старі пакети без контрольних сум показують попередження.
integrity_verified|Целостность: SHA-256 проверен|Integrity: SHA-256 verified|Цілісність: SHA-256 перевірено
integrity_unavailable|Контрольных сумм нет — целостность не подтверждена|No checksums — integrity unverified|Контрольних сум немає — цілісність не підтверджена
profile_already_open|Профиль уже открыт в другом сеансе. Закройте его перед продолжением.|Profile is already open in another session. Close it before continuing.|Профіль уже відкритий в іншому сеансі. Закрийте його перед продовженням.
profile_number|Номер|Number|Номер
yes|Да|Yes|Так
no|Нет|No|Ні
favorites|Избранное|Favorites|Обране
profile_status|Статус профиля|Profile status|Статус профілю
browser_state|Браузер|Browser|Браузер
all_profile_statuses|Все статусы профиля|All profile statuses|Усі статуси профілю
work_active|Активен|Active|Активний
work_new|Новый|New|Новий
work_review|На проверке|Under review|На перевірці
work_unused|Не используется|Not used|Не використовується
favorite|В избранное|Add to favorites|До обраного
unfavorite|Убрать из избранного|Remove from favorites|Прибрати з обраного
runtime|Время работы|Runtime|Час роботи
hours_short|ч|h|год
columns|Колонки|Columns|Колонки
columns_hint|Выберите поля и расположите их стрелками. Название профиля остаётся видимым.|Choose fields and reorder them using the arrows. Profile name stays visible.|Виберіть поля та змініть порядок стрілками. Назва профілю залишається видимою.
reset_columns|Сбросить колонки|Reset columns|Скинути колонки
move_up|Выше|Move up|Вище
move_down|Ниже|Move down|Нижче
quick_rename|Переименовать: двойной клик или F2|Rename: double click or F2|Перейменувати: подвійний клік або F2
tags|Теги|Tags|Теги
tags_hint|Теги через запятую|Comma-separated tags|Теги через кому
change_tags|Изменить теги|Change tags|Змінити теги
trash|Корзина|Trash|Кошик
move_to_trash|В корзину|Move to trash|До кошика
trash_question|Переместить профили ({n}) в корзину? Настройки и файлы сохранятся до окончательного удаления. Браузеры должны быть закрыты.|Move {n} profiles to trash? Settings and files remain until permanent deletion. Close their browsers first.|Перемістити профілі ({n}) до кошика? Налаштування й файли зберігатимуться до остаточного видалення. Браузери мають бути закриті.
trashed|Профили перемещены в корзину|Profiles moved to trash|Профілі переміщено до кошика
trash_hint|Восстановите профиль или измените срок хранения. Срок считается со дня перемещения в корзину. Автоочистка работает при запущенном XAnty и при следующем запуске.|Restore a profile or change retention. Retention starts when it is trashed. Automatic cleanup runs while XAnty is open and at the next startup.|Відновіть профіль або змініть термін зберігання. Термін рахується від дня переміщення до кошика. Автоочищення працює у відкритому XAnty та під час наступного запуску.
trash_empty|Корзина пуста|Trash is empty|Кошик порожній
retention_days|Хранить, дней|Retention, days|Зберігати, днів
retention_hint|0 — хранить бессрочно; от 1 до 3650 — удалить автоматически через указанное число дней.|0 keeps profiles forever; 1 to 3650 deletes them automatically after that many days.|0 — зберігати безстроково; від 1 до 3650 — видалити автоматично через указану кількість днів.
deleted_at|Удалён|Trashed at|Видалено
delete_after|Удалить окончательно|Delete permanently after|Видалити остаточно
never_delete|Бессрочно|Keep forever|Безстроково
restore|Восстановить|Restore|Відновити
delete_forever|Удалить навсегда|Delete forever|Видалити назавжди
purge_question|Удалить профиль, cookies и файлы Chrome навсегда? Восстановление станет невозможным.|Permanently delete the profile, cookies and Chrome files? This cannot be undone.|Видалити профіль, cookies та файли Chrome назавжди? Відновлення стане неможливим.
change_history|История изменений|Change history|Історія змін
history_hint|Записываются изменения с момента обновления. Автор — пользователь Windows; пароли и токены скрыты.|Changes are recorded from this update onward. Author is the Windows user; passwords and tokens are hidden.|Зміни записуються з моменту оновлення. Автор — користувач Windows; паролі й токени приховані.
search_history|Поиск в истории|Search history|Пошук в історії
history_empty|Изменений пока нет|No changes yet|Змін поки немає
audit_created|Создан|Created|Створено
audit_updated|Настройки изменены|Settings changed|Налаштування змінено
audit_trashed|В корзине|Moved to trash|У кошику
audit_restored|Восстановлен|Restored|Відновлено
audit_retention_changed|Изменён срок хранения|Retention changed|Змінено термін зберігання
audit_purged|Удалён навсегда|Deleted forever|Видалено назавжди
password|Пароль|Password|Пароль
headless|Без окна|Headless|Без вікна
close_before_trash|Закройте выбранные профили и дождитесь завершения операций перед удалением в корзину.|Close selected profiles and wait for operations to finish before moving them to trash.|Закрийте вибрані профілі та дочекайтеся завершення операцій перед переміщенням до кошика.
reserved_in_trash|Профиль с этим именем находится в корзине. Сначала восстановите или удалите его окончательно.|A profile with this name is in trash. Restore it or delete it permanently first.|Профіль із цим ім’ям у кошику. Спочатку відновіть або видаліть його остаточно.
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
search|Имя, №, заметки, теги, прокси…|Name, #, notes, tags, proxy…|Ім’я, №, нотатки, теги, проксі…
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
no_notes|Нет заметок|No notes|Немає нотаток
notes_edit_hint|Двойной щелчок — редактировать заметку|Double-click to edit the note|Подвійне клацання — редагувати нотатку
notes_save_hint|Ctrl+Enter — сохранить · Esc — отменить|Ctrl+Enter to save · Esc to cancel|Ctrl+Enter — зберегти · Esc — скасувати
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
    root.querySelectorAll('[data-i18n-aria-label]').forEach(el => { el.setAttribute('aria-label', t(el.dataset.i18nAriaLabel)); });
    root.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    root.querySelectorAll('[data-language]').forEach(el => { el.value = language; });
  }
  function set(value) {
    language = ['ru', 'en', 'uk'].includes(value) ? value : 'ru';
    document.documentElement.lang = language;
    localize();
    document.dispatchEvent(new CustomEvent('languagechange'));
  }
  const errors = {'Profile is already open in another session. Close it before continuing.':'profile_already_open','Закройте выбранные профили и дождитесь завершения операций перед удалением в корзину.':'close_before_trash','Профиль с этим именем находится в корзине. Сначала восстановите или удалите его окончательно.':'reserved_in_trash','Another transfer operation is running': 'transfer_busy', 'Profile transfer is running; wait for it to finish': 'transfer_busy', 'Close the selected profiles before exporting': 'close_before_export', 'Enter a Dolphin API token': 'token_required', 'Invalid or expired Dolphin API token': 'invalid_token', 'Cannot connect to the Dolphin API': 'api_unavailable', 'No profiles to export': 'no_profiles_export', 'No saved cookies for this profile': 'cookies_missing', 'Close this profile before importing cookies': 'close_before_cookies', 'Operation cancelled': 'cancelled'};
  Object.assign(errors, {
    'Enter an HTTP or HTTPS proxy rotation link.':'rotation_invalid',
    'Add a proxy rotation link in the profile settings first.':'rotation_missing',
    'This proxy rotation link is already in use. Wait for the current rotation to finish.':'rotation_busy',
    'Wait for current profile operations before rotating the proxy.':'rotation_wait_profile',
    'Proxy settings changed during rotation. Check the current IP.':'rotation_settings_changed',
    'Proxy rotation is rate limited. Wait and try again.':'rotation_rate_limited',
    'The proxy provider rejected the rotation request. Check the link and provider limits.':'rotation_rejected',
    'Proxy rotation timed out. The provider may have received the request; check the IP before trying again.':'rotation_timeout',
    'Cannot reach the proxy rotation endpoint. Check the link and connection.':'rotation_unreachable',
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
    'The selected Chrome / ChromeDriver pair is missing. Install a compatible pair in Chromium versions.':'ops_missing_pair',
    'The selected Chromium pair is unavailable or invalid; using the bundled browser.':'ops_cft_fallback',
    'The saved Chromium selection is invalid; using the bundled browser.':'ops_cft_fallback',
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
    const rotationHttp=text.match(/^Proxy rotation returned HTTP (\d+)\./);
    if(rotationHttp)return t('rotation_http',{code:rotationHttp[1]});
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

// Workspace operations keep the same RU / EN / UK message format as the app.
{
 const rows=`
workspace_operations|Инструменты|Tools|Інструменти
profile_size|Размер профиля|Profile size|Розмір профілю
reminder|Напоминание|Reminder|Нагадування
ops_intro|Браузеры, место на диске, копии и наборы окон — в одной рабочей области.|Browsers, disk space, backups and window sets for this workspace.|Браузери, місце на диску, копії та набори вікон цієї робочої області.
ops_loading|Загрузка инструментов…|Loading tools…|Завантаження інструментів…
ops_storage|Место на диске|Disk space|Місце на диску
ops_profiles_size|Размер измеренных профилей|Measured profile storage|Розмір виміряних профілів
ops_sizes_known|Профилей измерено|Profiles measured|Профілів виміряно
ops_scan_sizes|Измерить профили|Measure profiles|Виміряти профілі
ops_sizes_updated|Размеры профилей обновлены.|Profile sizes updated.|Розміри профілів оновлено.
ops_cache_selected|Кэш выбранных ({n})|Selected cache ({n})|Кеш вибраних ({n})
ops_cache_hint|Очистка кэша доступна для закрытых профилей. Cookies и сессии сохраняются.|Close selected profiles before clearing cache. Cookies and sessions are kept.|Закрийте вибрані профілі перед очищенням кешу. Cookies і сесії зберігаються.
ops_cache_question|Очистить только кэш выбранных профилей ({n})?|Clear only the cache of {n} selected profiles?|Очистити лише кеш вибраних профілів ({n})?
ops_preview_obsolete|Найти устаревшие файлы|Find obsolete files|Знайти застарілі файли
ops_obsolete_found|Найдено: {n} файлов, {size}. Проверьте список перед очисткой.|Found {n} files, {size}. Review the list before cleaning.|Знайдено: {n} файлів, {size}. Перевірте список перед очищенням.
ops_clean_obsolete|Удалить найденные файлы|Clean listed files|Видалити знайдені файли
ops_cleanup_question|Удалить найденные устаревшие файлы ({n})?|Remove the {n} listed obsolete files?|Видалити знайдені застарілі файли ({n})?
ops_reclaimed|Удалено файлов: {n}. Освобождено: {size}.|Removed {n} files. Reclaimed {size}.|Видалено файлів: {n}. Звільнено: {size}.
ops_chromium|Версии Chromium|Chromium versions|Версії Chromium
ops_cft_hint|Chrome for Testing устанавливается вместе с ChromeDriver той же версии. Профили используют отдельные папки данных.|Chrome for Testing is installed with the same ChromeDriver version. Each profile keeps its own data folder.|Chrome for Testing встановлюється разом із ChromeDriver тієї самої версії. Профілі мають окремі папки даних.
ops_cft_fallback|Выбранная пара недоступна или повреждена. Используется встроенный браузер. Проверьте версию:|The selected pair is missing or invalid. Using the bundled browser. Check version:|Вибрана пара недоступна або пошкоджена. Використовується вбудований браузер. Перевірте версію:
ops_bundled|Встроенная версия (Bro / Drivers)|Bundled version (Bro / Drivers)|Вбудована версія (Bro / Drivers)
ops_selected|Используется|Selected|Використовується
ops_installed|Установлена|Installed|Встановлена
ops_unavailable|Недоступна|Unavailable|Недоступна
ops_select|Использовать|Select|Використовувати
ops_cft_close|Перед сменой или удалением версии закройте все профили.|Close all profiles before selecting or deleting a version.|Перед зміною або видаленням версії закрийте всі профілі.
ops_cft_version|Канал или полная версия|Channel or full version|Канал або повна версія
ops_check_versions|Проверить версии|Check versions|Перевірити версії
ops_install_pair|Установить пару|Install pair|Встановити пару
ops_cft_verification|Только официальные серверы Google через HTTPS. Проверяются целостность ZIP и совпадение версий. Google не публикует подписанные хэши в этом каталоге.|Official Google HTTPS servers only. ZIP integrity and executable versions are checked. This catalog does not provide signed vendor hashes.|Лише офіційні сервери Google через HTTPS. Перевіряються цілісність ZIP і збіг версій. Google не публікує підписані хеші в цьому каталозі.
ops_delete_version|Удалить установленную пару {version}?|Delete the installed {version} pair?|Видалити встановлену пару {version}?
ops_cft_job|Установка Chromium|Chromium installation|Встановлення Chromium
ops_backups|Локальные резервные копии|Local backups|Локальні резервні копії
ops_backup_job|Резервная копия|Workspace backup|Резервна копія
ops_backup_hint|Копии включают данные профилей и сессий. Автоматическое копирование работает, пока XAnty запущен; при открытых профилях оно откладывается.|Backups include profile and session data. Automatic backups run while XAnty is open and wait for profiles to close.|Копії містять дані профілів і сесій. Автоматичне копіювання працює, поки XAnty запущено; за відкритих профілів воно відкладається.
ops_backup_auto|Автоматические копии|Automatic backups|Автоматичні копії
ops_backup_directory|Папка на локальном диске|Local backup folder|Папка на локальному диску
ops_backup_directory_hint|Укажите полный путь. Копии этого рабочего пространства хранятся в отдельной подпапке.|Enter a full local path. This workspace uses a dedicated subfolder.|Укажіть повний локальний шлях. Копії цієї робочої області зберігаються в окремій підпапці.
ops_backup_interval|Интервал, часов|Interval, hours|Інтервал, годин
ops_backup_keep|Хранить последних копий|Keep latest copies|Зберігати останніх копій
ops_backup_run|Сохранить и создать копию|Save and back up now|Зберегти й створити копію
ops_backup_last|Последняя успешная копия|Last successful backup|Остання успішна копія
ops_backup_next|Следующая копия|Next backup|Наступна копія
ops_choose_directory|Укажите папку резервных копий.|Choose a backup folder.|Укажіть папку резервних копій.
ops_backup_status_never|Копий пока нет|No backup yet|Копій поки немає
ops_backup_status_running|Создание копии…|Backing up…|Створення копії…
ops_backup_status_completed|Копия сохранена и проверена|Backup saved and verified|Копію збережено й перевірено
ops_backup_status_failed|Не удалось создать копию|Backup failed|Не вдалося створити копію
ops_backup_status_postponed|Ожидает закрытия профилей|Waiting for profiles to close|Очікує закриття профілів
ops_backup_status_cancelled|Копирование отменено|Backup cancelled|Копіювання скасовано
ops_window_sets|Наборы окон|Window sets|Набори вікон
ops_window_sets_hint|Сохраните состав открытых или выбранных профилей. Открытие набора закроет окна профилей, которых в нём нет.|Save open or selected profiles as a set. Opening a set closes profile windows outside that set.|Збережіть відкриті або вибрані профілі як набір. Відкриття набору закриває вікна профілів поза ним.
ops_save_open_set|Сохранить открытые|Save open profiles|Зберегти відкриті
ops_save_selected_set|Сохранить выбранные|Save selected profiles|Зберегти вибрані
ops_set_count|Профилей: {n}|Profiles: {n}|Профілів: {n}
ops_set_missing|Недоступных профилей: {n}. Измените состав набора.|Missing profiles: {n}. Edit the set first.|Недоступних профілів: {n}. Змініть склад набору.
ops_choose_set_profiles|Выберите профили, которые должны входить в набор.|Choose the profiles to include in this set.|Виберіть профілі для цього набору.
ops_no_window_sets|Наборов пока нет.|No window sets yet.|Наборів поки немає.
ops_set_not_found|Набор не найден. Обновите список.|Set not found. Refresh the list.|Набір не знайдено. Оновіть список.
ops_open_exact|Открыть набор|Open exact set|Відкрити набір
ops_exact_question|Окна вне набора ({n}) будут закрыты с сохранением сессий. Открыть этот набор?|Close {n} profile windows outside this set, saving sessions, then open this exact set?|Вікна поза набором ({n}) буде закрито зі збереженням сесій. Відкрити цей набір?
ops_delete_set|Удалить набор из списка?|Delete this window set?|Видалити цей набір зі списку?
ops_reminders|Напоминания|Reminders|Нагадування
ops_add_reminder|Добавить|Add reminder|Додати
ops_reminder_note|Текст напоминания|Reminder note|Текст нагадування
ops_local_time|Местное время компьютера. Напоминания показываются, пока XAnty запущен.|Computer local time. Reminders appear while XAnty is open.|Місцевий час комп’ютера. Нагадування відображаються, поки XAnty запущено.
ops_due|Пора выполнить|Due now|Час виконати
ops_no_reminders|Напоминаний пока нет. Их можно задать и в редакторе профиля.|No reminders. You can also add one in the profile editor.|Нагадувань поки немає. Їх також можна додати в редакторі профілю.
ops_open_reminders|К напоминаниям|Open reminders|До нагадувань
ops_invalid_date|Укажите корректную дату и время.|Enter a valid date and time.|Укажіть правильні дату й час.
ops_important|Важный профиль|Important profile|Важливий профіль
ops_protected_hint|Важные и избранные профили защищены: для удаления нужно ввести DELETE.|Important and favorite profiles require typing DELETE before deletion.|Важливі та обрані профілі захищено: для видалення потрібно ввести DELETE.
ops_type_delete|Введите DELETE для подтверждения|Type DELETE to confirm|Уведіть DELETE для підтвердження
ops_block_images|Не загружать изображения|Block images|Не завантажувати зображення
ops_block_media|Не загружать аудио и видео|Block audio and video|Не завантажувати аудіо й відео
ops_block_fonts|Не загружать веб-шрифты|Block web fonts|Не завантажувати вебшрифти
ops_phishing_protection|Предупреждать о подозрительных адресах|Warn about suspicious addresses|Попереджати про підозрілі адреси
ops_phishing_hint|Защита Safe Browsing Chrome остаётся включённой. Дополнительная проверка использует ограниченные правила для адресов.|Chrome Safe Browsing remains enabled. Additional address checks use a limited set of URL heuristics.|Захист Safe Browsing Chrome залишається ввімкненим. Додаткова перевірка використовує обмежені правила для адрес.
ops_export_choice|Выберите состав переносимого профиля.|Choose what to include in the profile package.|Виберіть склад переносного профілю.
ops_safe_export|Без секретов (только настройки)|Without secrets (settings only)|Без секретів (лише налаштування)
ops_safe_export_hint|Пароли, токены, cookies, учётные данные прокси и файлы браузера исключаются. Для полного переноса сессий снимите флажок.|Excludes passwords, tokens, cookies, proxy credentials and browser files. Uncheck to transfer complete sessions.|Паролі, токени, cookies, облікові дані проксі й файли браузера виключаються. Зніміть прапорець для повного перенесення сесій.
ops_missing_pair|Выбранная пара Chrome / ChromeDriver не найдена. Установите совместную пару в разделе версий Chromium.|The selected Chrome / ChromeDriver pair is missing. Install a compatible pair in Chromium versions.|Вибрану пару Chrome / ChromeDriver не знайдено. Установіть спільну пару в розділі версій Chromium.
ops_no_errors|Проблем запуска не обнаружено.|No launch problems found.|Проблем запуску не виявлено.
ops_error_missing_browser|Не найден браузер|Browser missing|Браузер не знайдено
ops_fix_missing_browser|Проверьте выбранную пару Chrome и ChromeDriver или установите её в разделе версий.|Check the selected Chrome and ChromeDriver pair or install one in Chromium versions.|Перевірте вибрану пару Chrome і ChromeDriver або встановіть її в розділі версій.
ops_error_proxy|Ошибка прокси|Proxy problem|Помилка проксі
ops_fix_proxy|Проверьте адрес, порт, логин и пароль прокси в профиле, затем повторите проверку прокси.|Check the profile proxy host, port and credentials, then run the proxy check.|Перевірте адресу, порт, логін і пароль проксі в профілі, потім повторіть перевірку проксі.
ops_error_profile_busy|Профиль занят|Profile in use|Профіль зайнятий
ops_fix_profile_busy|Закройте окно этого профиля в другом экземпляре XAnty и повторите запуск.|Close this profile in the other XAnty instance, then try again.|Закрийте цей профіль в іншому екземплярі XAnty й повторіть запуск.
ops_error_version|Несовместимые версии|Version mismatch|Несумісні версії
ops_fix_version|Выберите совместную установку Chrome и ChromeDriver одной версии.|Select Chrome and ChromeDriver installed as an exact-version pair.|Виберіть спільну інсталяцію Chrome і ChromeDriver однієї версії.
ops_error_timeout|Время ожидания истекло|Launch timeout|Час очікування минув
ops_fix_timeout|Проверьте доступность прокси и сеть. Закройте профиль и повторите запуск.|Check the proxy and network. Close the profile and retry.|Перевірте доступність проксі й мережу. Закрийте профіль і повторіть запуск.
ops_error_configuration|Настройки профиля|Profile settings|Налаштування профілю
ops_fix_configuration|Откройте редактор и проверьте параметры браузера и прокси.|Open the profile editor and check browser and proxy settings.|Відкрийте редактор і перевірте параметри браузера та проксі.
ops_error_unknown|Ошибка запуска|Launch problem|Помилка запуску
ops_fix_unknown|Проверьте описание ошибки и параметры профиля. Подробности доступны в журнале.|Review the error and profile settings. More details are available in the monitor.|Перевірте опис помилки й параметри профілю. Подробиці доступні в журналі.
ops_job_done|{name}: завершено.|{name}: completed.|{name}: завершено.
ops_job_cancelled|{name}: отменено.|{name}: cancelled.|{name}: скасовано.
ops_phase_starting|Подготовка|Preparing|Підготовка
ops_phase_resolve|Проверка версии|Resolving version|Перевірка версії
ops_phase_download|Загрузка|Downloading|Завантаження
ops_phase_extract|Распаковка и проверка|Extracting and checking|Розпакування й перевірка
ops_phase_complete|Готово|Complete|Готово
ops_phase_finished|Завершено|Finished|Завершено
ops_phase_exporting|Сохранение профилей|Saving profiles|Збереження профілів
ops_phase_verifying|Проверка копии|Verifying backup|Перевірка копії
`;
 for(const line of rows.trim().split('\n')){const [key,...values]=line.split('|');I18N.messages[key]=values;}
}

{
 const rows=`
ui_identity|Основное|Identity|Основне
ui_organization|Организация и заметки|Organization and notes|Організація та нотатки
ui_network|Прокси и сеть|Proxy and network|Проксі та мережа
ui_session|Вход и сессия|Login and session|Вхід і сесія
ui_browser_behavior|Поведение браузера|Browser behavior|Поведінка браузера
`;
 for(const line of rows.trim().split('\n')){const [key,...values]=line.split('|');I18N.messages[key]=values;}
}

{
 const rows=`
quality_navigation|Папки и язык|Folders and language|Папки та мова
quality_proxy_error|Ошибка прокси|Proxy error|Помилка проксі
`;
 for(const line of rows.trim().split('\n')){const [key,...values]=line.split('|');I18N.messages[key]=values;}
}

{
 const rows=`
quality_file_choose|Выбрать файл|Choose file|Вибрати файл
quality_file_empty|Файл не выбран|No file selected|Файл не вибрано
`;
 for(const line of rows.trim().split('\n')){const [key,...values]=line.split('|');I18N.messages[key]=values;}
}

{
 const rows=`
ops_safe_export|Только шаблон без данных профиля|Template only, without profile data|Лише шаблон без даних профілю
ops_safe_export_hint|Оставьте выключенным для передачи названий, прокси, всех настроек и cookies. Шаблон исключает названия, папки, заметки, прокси, пароли, cookies и файлы браузера.|Leave off to transfer names, proxies, all settings and cookies. Template mode omits names, folders, notes, proxies, passwords, cookies and browser files.|Залиште вимкненим для передачі назв, проксі, усіх налаштувань і cookies. Шаблон виключає назви, папки, нотатки, проксі, паролі, cookies та файли браузера.
ops_export_choice|Полный перенос включает названия, прокси, настройки, cookies, вкладки и данные каждого профиля.|A full transfer includes each profile's name, proxy, settings, cookies, tabs and browser data.|Повне перенесення містить назви, проксі, налаштування, cookies, вкладки та дані кожного профілю.
browser_tools_settings|Настройки XAnty|XAnty settings|Налаштування XAnty
release_history|История обновлений|Update history|Історія оновлень
release_history_intro|Выберите версию, чтобы посмотреть изменения. История доступна без интернета.|Choose a version to read its changes. History is available offline.|Виберіть версію, щоб переглянути зміни. Історія доступна без інтернету.
release_history_current|Установленная версия|Installed version|Встановлена версія
release_notes_hint|Все предыдущие обновления доступны в «Настройки XAnty» → «История обновлений».|Find earlier updates in XAnty settings → Update history.|Попередні оновлення доступні в «Налаштування XAnty» → «Історія оновлень».
`;
 for(const line of rows.trim().split('\n')){const [key,...values]=line.split('|');I18N.messages[key]=values;}
}
