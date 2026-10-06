# Amplua: аудит готовности к App Store и Google Play

Дата аудита: 2026-10-06. Строки в ссылках указаны по рабочей копии: коммит `9152ee8` плюс незакоммиченное переименование FootIQ → Amplua. Код приложения в рамках аудита не менялся.

**Как читать.** Каждый пункт: что не так, доказательство из проекта (файл:строка или команда поиска с пустым результатом), что сделать, источник правила. Требования стора собраны из официальных страниц Apple и Google 2026-10-06, полный список адресов в разделе 5. Пункты, которые нельзя проверить на Windows, помечены «проверить на Mac».

**Итог сборок** (полный вывод в Приложении):

| Проверка | Код возврата | Итог |
| --- | --- | --- |
| `flutter analyze` | 0 | `No issues found! (ran in 3.8s)` |
| `flutter build appbundle --release` | 0 | `√ Built build\app\outputs\bundle\release\app-release.aab (52.9MB)`, но бандл подписан debug-ключом (блокер 7) |
| targetSdk / minSdk в итоговом манифесте | | 36 / 24: требование Google «API 36 с 31.08.2026» выполнено |
| 16 KB page size, arm64 `.so` | | `libapp.so` и `libflutter.so` выровнены на 0x10000, `libdartjni.so` и `libdatastore_shared_counter.so` на 0x4000: требование выполнено |
| iOS-сборка | | невозможна на Windows, проверить на Mac |

**Главный вывод.** В сторы сейчас уходит демо: покупка PRO замокана, сервера нет, и без `API_URL` релиз работает на локальном бэкенде с фейковым входом. Юридические страницы не существуют, иконка стандартная от Flutter, Android подписан debug-ключом. Сверх этого не хватает механизмов, которые сторы требуют для пользовательского контента и ИИ: фильтра, жалоб, блокировки и согласия на передачу текста во внешнюю LLM. Клиентская часть удаления аккаунта, ссылки на условия, восстановление покупок и текст об автопродлении уже есть.

---

## 1. Блокеры

С ними отклонят на ревью или не дадут загрузить сборку. Порядок от самого тяжёлого.

- [ ] **Блокер · Apple 2.1(b), 3.1.1 · Google Payments** Покупка PRO замокана. `purchasePro()` ждёт 900 мс и пишет флаг `pro_owned` в SharedPreferences (`lib/data/repository.dart:296-302`). `restorePurchases()` тоже ничего не спрашивает у стора (`lib/data/repository.dart:304-309`). Ревьюер Apple должен купить подписку в sandbox, а Google требует оплату цифровой подписки через Play Billing. → сделать: подключить RevenueCat `purchases_flutter` (или `in_app_purchase`), завести продукты «Месяц» и «Год» в App Store Connect и Play Console, восстановление через `Purchases.restorePurchases()`. В Android-версии RevenueCat проверить, что внутри Play Billing Library 8 или новее: с 31.08.2026 это обязательно для новых приложений. · источник: https://developer.apple.com/app-store/review/guidelines/#in-app-purchase, https://support.google.com/googleplay/android-developer/answer/10281818, https://developer.android.com/google/play/billing/deprecation-faq

- [ ] **Блокер · Apple 2.2, 2.1(a)** В релизной сборке есть тестовая кнопка «Завершить подписку (тест)» (`lib/screens/paywall.dart:252-259`), она вызывает `expirePro()` (`lib/data/repository.dart:311-315`). Тестовые и демо-функции в сторе запрещены. → сделать: убрать кнопку вместе с `expirePro()`, когда появятся настоящие покупки. До этого прятать её за `kDebugMode`. · источник: https://developer.apple.com/app-store/review/guidelines/#beta-testing

- [ ] **Блокер · Apple 3.1.2, 2.3.1(a), Schedule 2 §3.8(b) · Google Subscriptions** Цены на пейволе захардкожены в рублях: «2 990 ₽ / год», «249 ₽ в месяц», «−50%», «499 ₽ / месяц» (`lib/screens/paywall.dart:261-279`). Apple требует полную цену продления, локализованную в валюте витрины, и эта цена должна быть самым заметным ценовым элементом. Показ цены, которая расходится со стором, подпадает под «false price». Google требует раскрыть стоимость и период списания. → сделать: брать `priceString` и период из offerings RevenueCat (`Product.displayPrice` в StoreKit, `formattedPrice` в Play), «−50%» и «249 ₽ в месяц» считать из реальных цен и показывать мельче полной цены. Если появится пробный период, добавить длительность и цену после него. Текст об автопродлении уже есть (`lib/screens/paywall.dart:288-292`), его оставить. · источник: https://developer.apple.com/app-store/subscriptions/, https://developer.apple.com/support/downloads/terms/schedules/Schedule-2-and-3-English.pdf, https://support.google.com/googleplay/android-developer/answer/9900533

- [ ] **Блокер · Apple 5.1.1(i), 3.1.2 · Google User Data, Data safety** Ссылки на условия и политику ведут на несуществующий домен: `https://amplua.app/terms` и `https://amplua.app/privacy` (`lib/widgets/common.dart:540-542`). Проверка: `curl https://amplua.app/terms` завершается с exit 6 (could not resolve host), `nslookup amplua.app 8.8.8.8` не возвращает адреса, при этом `curl https://www.google.com` отвечает 200. Без политики не заполнить Data safety, а Apple требует ссылку и в метаданных, и в приложении. Google отдельно требует «active, publicly accessible and non-geofenced URL (no PDFs)». → сделать: купить домен (или взять другой), опубликовать обе страницы в HTML и поправить константы, если адрес изменится. Что должно быть в текстах, см. раздел 2.4. · источник: https://developer.apple.com/app-store/review/guidelines/#data-collection-and-storage, https://support.google.com/googleplay/android-developer/answer/10144311, https://support.google.com/googleplay/android-developer/answer/10787469

- [ ] **Блокер · Apple 2.1(a) · Google App access** Сервера нет. Без `--dart-define=API_URL` релиз собирается на `LocalBackend` (`lib/data/repository.dart:15-16, 29`), а вход в нём фейковый: окна Google и Apple не открываются, подставляется `player@gmail.com` (`lib/data/repository.dart:127-132`). Рейтинги заполнены выдуманными игроками (`lib/data/mock_players.dart:5`, `lib/data/local_backend.dart:326-354`). Сборка из этого аудита (`flutter build appbundle --release` без defines) как раз такая. Apple требует «turn on your back-end service». Фейковые игроки в рейтинге выдают демо за настоящий продукт. → сделать: бэкенд по `docs/API.md` поднять в проде (раздел 3, задача 1). Релиз собирать только с `API_URL`, `GOOGLE_SERVER_CLIENT_ID` и `GOOGLE_IOS_CLIENT_ID`. Защита от ошибки: в release при пустом `API_URL` падать на старте (`assert` не сработает, нужна проверка `kReleaseMode`). · источник: https://developer.apple.com/app-store/review/guidelines/#app-completeness, https://support.google.com/googleplay/android-developer/answer/9859455

- [ ] **Блокер · Apple 2.1(a) · Google App access** Тестового входа для ревьюера нет. Без входа в приложение не попасть (`lib/screens/welcome.dart:24-33`), а войти можно только через Google или Apple (`lib/screens/welcome.dart:190-210`). Обе стороны требуют данные для входа: Apple в App Review Information, Google в разделе App access. → сделать: выбрать способ (раздел 4, вопрос 3), завести аккаунт с прогрессом и вписать инструкции в обе консоли. · источник: https://developer.apple.com/app-store/review/guidelines/#app-completeness, https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/, https://support.google.com/googleplay/android-developer/answer/9859455

- [ ] **Блокер · Google Play App Signing** Релиз подписан debug-ключом: `signingConfig = signingConfigs.getByName("debug")` (`android/app/build.gradle.kts:28-33`). `keytool -printcert -jarfile build/app/outputs/bundle/release/app-release.aab` показывает `Owner: C=US, O=Android, CN=Android Debug`. Play Console не принимает бандлы, подписанные в debug-режиме. → сделать: создать upload-ключ (`keytool -genkey ... -keystore upload-keystore.jks`), положить пароли в `android/key.properties` вне git, завести `signingConfigs.create("release")`, включить Play App Signing. SHA-1 upload-ключа и ключа подписи Google внести в Android OAuth-клиент Google Cloud, иначе вход через Google в релизе не заработает (`docs/API.md:310`). · источник: https://support.google.com/googleplay/android-developer/answer/9844279

- [ ] **Блокер · Apple 4.1(c), 2.3.7 · Google Metadata** На обеих платформах стоит иконка Flutter. Android: md5 `android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png` = `57838d52…` совпадает с шаблоном `C:/flutter/packages/flutter_tools/templates/app/android.tmpl/.../ic_launcher.png`. iOS: `ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-1024x1024@1x.png` это логотип Flutter (проверено просмотром). Apple с 13.11.2025 прямо запрещает чужую иконку или бренд в иконке приложения. → сделать: иконка Amplua во всех размерах mipmap, adaptive icon (foreground и background) для Android, все размеры AppIcon плюс 1024×1024 без альфа-канала для iOS, отдельно 512×512 для листинга Play. Заодно заменить белые стартовые экраны: `ios/Runner/Base.lproj/LaunchScreen.storyboard:22`, `android/app/src/main/res/values/styles.xml` (`Theme.Light`). · источник: https://developer.apple.com/app-store/review/guidelines/#copycats, https://support.google.com/googleplay/android-developer/answer/9898842

- [ ] **Блокер · Apple 1.2 · Google UGC** Пользовательский контент виден чужим людям, а фильтра, жалоб и блокировки нет. Что видно:
  - имена игроков в глобальном и региональном рейтинге (`lib/screens/rating.dart:420`);
  - названия лиг до 32 символов (`lib/screens/rating.dart:559, 727`);
  - имя создателя лиги (`lib/screens/rating.dart:931`).

  В меню лиги есть только переименовать, передать, удалить и покинуть (`lib/screens/rating.dart:941-999`), исключить участника нельзя. Опубликованного контакта в приложении нет. Поиск: `rg -i "report|жалоб|пожал|block|модер|flag" lib` находит только посторонние совпадения (`flag_fill`, `regionFlags`), `rg "mailto|support@" lib` ничего не находит. Apple требует фильтр, жалобу, блокировку и опубликованный контакт. Google требует «robust, effective, and ongoing UGC moderation» и «in-app system for reporting and blocking objectionable UGC and users». → сделать (клиент):
  - «Пожаловаться» на строке игрока в рейтинге и в меню лиги;
  - «Заблокировать игрока»: он пропадает из моих таблиц и лиг;
  - создателю лиги «Исключить участника»;
  - в Профиле строка «Связаться с нами» (email);
  - сервер отклоняет имя или название фильтром, клиент показывает его `message` (уже работает через `validation_error`).

  Серверная часть описана в разделе 3, задача 6. · источник: https://developer.apple.com/app-store/review/guidelines/#user-generated-content, https://support.google.com/googleplay/android-developer/answer/9876937

- [ ] **Блокер · Google DPP «AI-Generated Content» · Apple 1.2 / 4.7 (не подтверждено)** На ответ ИИ-тренера нельзя пожаловаться. Реплика тренера выводится в `VerdictCard` (`lib/screens/locker_room.dart:639-748`, текст на строке 737), карточка открывается и из истории (`lib/screens/profile.dart:566`). Кнопки жалобы нет (поиск тот же, что в пункте про UGC). Текст DPP, действующий с 30.09.2026: «Apps that generate content using AI must contain in-app user reporting or flagging features… without needing to exit the app». Для Apple 4.7 (чатботы) применимость к нашему тренеру не подтверждена, но кнопка закрывает и этот риск. → сделать: в `VerdictCard` пункт «Пожаловаться на ответ» (bottom sheet с причинами), отправка `POST /v1/reports` с id попытки (раздел 3, задача 7). · источник: https://support.google.com/googleplay/android-developer/answer/17190352, https://support.google.com/googleplay/android-developer/answer/14094294

- [ ] **Блокер · Apple 5.1.2(i) · Google User Data (анонс 15.07.2026)** Текст ответа игрока уходит во внешнюю LLM без явного согласия. Отправка: `app.submitVideo(...)` (`lib/screens/locker_room.dart:198`). По ТЗ сервер передаёт этот текст в GPT-4o-mini или Claude Haiku (ТЗ, ч. II, п. 2.1). Единственное упоминание согласия в коде пассивное: «Продолжая, ты принимаешь условия и политику конфиденциальности» (`lib/screens/welcome.dart:216`), других совпадений `rg -i "соглас|consent" lib` не находит. Apple требует «clearly disclose where personal data will be shared with third parties, including with third-party AI, and obtain explicit permission». Google с июля 2026 распространил требования User Data на сторонние AI-интеграции (limited use, disclosure, consent). → сделать: перед первым ответом в Раздевалке показать bottom sheet: что отправляется (текст ответа, амплуа), кому (провайдер LLM) и зачем, кнопки «Согласен» и «Не сейчас». Факт согласия хранить на сервере (раздел 3, задача 7). Без согласия режим видео-разбора закрыт. · источник: https://developer.apple.com/app-store/review/guidelines/#data-use-and-sharing, https://support.google.com/googleplay/android-developer/answer/17134731

- [ ] **Блокер · Google «Account deletion» (веб-ресурс) · Apple 5.1.1(v)** Удаление аккаунта в приложении сделано: строка «Удалить аккаунт» (`lib/screens/profile.dart:337`), подтверждение (`lib/screens/profile.dart:284-292`), `deleteAccount()` (`lib/data/repository.dart:145-149`), `DELETE /me` (`lib/data/remote_backend.dart:112-115`). Двух вещей не хватает:
  - сервера, который реально удаляет (`docs/API.md:52-56` пока только описание);
  - веб-ресурса для запроса удаления, ссылку на который Google требует указать в Data safety. Поиск: `rg -i "delete-account|удалени.*сайт|account-deletion" lib docs/API.md docs/LOGIC_AUDIT.md` ничего не находит.

  → сделать: страница удаления на домене из блокера 4 (раздел 3, задача 3) и её URL в форме Data safety. · источник: https://support.google.com/googleplay/android-developer/answer/13327111, https://developer.apple.com/support/offering-account-deletion-in-your-app/

- [ ] **Блокер · Apple 2.1(a) (падение при входе) · проверить на Mac** iOS-проект не настроен под оба способа входа:
  - **Sign in with Apple.** Capability нет: `find ios -name "*.entitlements"` пусто, в `ios/Runner.xcodeproj/project.pbxproj` нет `CODE_SIGN_ENTITLEMENTS` и `com.apple.developer.applesignin` (`grep -c` = 0). Без entitlement `getAppleIDCredential` возвращает ошибку, и кнопка «Продолжить с Apple» не работает.
  - **Google Sign-In.** В `ios/Runner/Info.plist` нет `CFBundleURLTypes` с reversed client ID (весь файл: строки 1-70). GoogleSignIn SDK без URL scheme падает при вызове входа (поведение SDK, подтвердить на устройстве).

  Свои же инструкции это уже описывают (`docs/API.md:311-315`). → сделать: в Xcode включить capability «Sign in with Apple» (появится `Runner.entitlements`), включить её у App ID, добавить URL scheme `com.googleusercontent.apps.<id>` в `Info.plist`, пройти оба входа на реальном iPhone с релизными defines. · источник: https://developer.apple.com/app-store/review/guidelines/#app-completeness

## 2. Мне: клиентский код и аккаунты сторов

### 2.1 Клиентский код

- [ ] **Apple, Export compliance** В `ios/Runner/Info.plist` нет `ITSAppUsesNonExemptEncryption` (поиск `grep -n "ITSAppUsesNonExemptEncryption" ios/Runner/Info.plist` пуст). Без ключа App Store Connect задаёт вопрос про шифрование при каждой сборке. HTTPS через системный стек освобождён от экспортной документации. → сделать: `<key>ITSAppUsesNonExemptEncryption</key><false/>`. · источник: https://developer.apple.com/documentation/security/complying-with-encryption-export-regulations

- [ ] **Apple, Privacy manifest · проверить на Mac** У приложения нет своего `PrivacyInfo.xcprivacy` (`find ios -name "*.xcprivacy"` пусто). По плагинам из `pubspec.lock` (проверено в pub cache):

  | Плагин | Версия | Манифест |
  | --- | --- | --- |
  | `shared_preferences_foundation` | 2.5.7 | есть (UserDefaults) |
  | `video_player_avfoundation` | 2.12.0 | есть |
  | `url_launcher_ios` | 6.4.2 | есть |
  | `flutter_secure_storage_darwin` | 0.3.2 | есть |
  | `share_plus` | 11.1.0 | есть |
  | `google_sign_in_ios` | 6.3.5 | есть (GoogleSignIn ~> 9.0 со своим манифестом) |
  | `sign_in_with_apple` | 8.2.0 | **нет**, но API из списка required reason в его коде нет (`grep -rlE "UserDefaults\|systemUptime\|mach_absolute_time\|creationDate\|modificationDate\|volumeAvailableCapacity\|activeInputModes"` пусто). В списке SDK Apple его нет |
  | `path_provider_foundation` | 2.6.0 | нет, но в пакете нет нативного кода (только `lib/`, работает через FFI `objective_c`) |

  → сделать: на Mac собрать Archive и открыть Privacy Report (Xcode: Organizer → Generate Privacy Report). Добавить в Runner `PrivacyInfo.xcprivacy` с `NSPrivacyTracking = false` и собираемыми типами данных, если отчёт покажет непокрытые категории. После письма ITMS-91053 от App Store Connect дописать нужные причины. · источник: https://developer.apple.com/documentation/bundleresources/describing-use-of-required-reason-api, https://developer.apple.com/support/third-party-SDK-requirements/

- [ ] **Apple, минимальные Xcode и SDK · проверить на Mac** С 28.04.2026 загрузка принимается только из Xcode 26 и новее с SDK iOS 26. Deployment target 13.0 (`ios/Runner.xcodeproj/project.pbxproj:363`) укладывается в требование «iOS 13 or later». → сделать: собрать на Mac с Xcode 26.x, Flutter 3.44.0 (из `flutter --version`). · источник: https://developer.apple.com/news/upcoming-requirements/

- [ ] **Apple 2.1 / скриншоты iPad · проверить на Mac** Приложение объявлено для iPhone и iPad (`TARGETED_DEVICE_FAMILY = "1,2"`, `ios/Runner.xcodeproj/project.pbxproj:367`) и разрешает альбомную ориентацию на iPhone (`ios/Runner/Info.plist:56-61`) и на iPad (`ios/Runner/Info.plist:62-68`). Тогда нужны скриншоты iPad 13", и вёрстка должна работать на iPad в альбомной ориентации. Ревьюеры часто проверяют именно на iPad. → сделать: либо `TARGETED_DEVICE_FAMILY = 1` и только портрет, либо прогнать все экраны на iPad-симуляторе (решение в разделе 4). · источник: https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/

- [ ] **Apple, удаление аккаунта и подписка** Подтверждение удаления пишет «Подписку отменяют в настройках магазина» (`lib/screens/profile.dart:288`), но ссылки нет. Apple просит предупредить, что списания через Apple продолжатся, и дать путь к управлению подпиской. Google требует простой онлайн-способ отмены. → сделать: в шит удаления и в строку «Подписка» добавить «Управлять подпиской»: на iOS `https://apps.apple.com/account/subscriptions` (или StoreKit `showManageSubscriptions`), на Android `https://play.google.com/store/account/subscriptions`. · источник: https://developer.apple.com/support/offering-account-deletion-in-your-app/, https://support.google.com/googleplay/android-developer/answer/9900533

- [ ] **Google UGC: принятие условий до создания контента** Условия принимаются пассивной строкой на экране входа (`lib/screens/welcome.dart:216-217`). Google требует, чтобы пользователь принял условия до создания UGC. Пассивного варианта на входе, скорее всего, хватает, но в условиях должен быть раздел о недопустимом контенте в именах и названиях лиг. → сделать: проверить формулировку вместе с юридическими текстами (2.4). · источник: https://support.google.com/googleplay/android-developer/answer/9876937

- [ ] **Название Amplua** Проверено: `android:label="Amplua"` (`android/app/src/main/AndroidManifest.xml:4`), `CFBundleDisplayName = Amplua` (`ios/Runner/Info.plist:9-10`), `MaterialApp.title` (`lib/main.dart:33`), applicationId и bundle id `com.amplua.amplua` (`android/app/build.gradle.kts:19`, `ios/Runner.xcodeproj/project.pbxproj:385`). Поиск `rg -i "foot ?iq"` по проекту (без build, pdf и docx) ничего не находит. Остатки старого бренда вынесены в пожелания. → сделать: ничего, кроме иконки (блокер 8).

### 2.2 App Store Connect

- [ ] **App Privacy (nutrition labels)** Заполнить по реальным потокам данных:
  - Contact Info: Email (из Google/Apple), Name;
  - Identifiers: User ID;
  - User Content: ответы в Раздевалке, названия лиг;
  - Usage Data: Product Interaction (попытки, ELO);
  - Purchases: Purchase History (RevenueCat).

  Всё связано с личностью, трекинга нет. Данные SDK включаются в декларацию. · источник: https://developer.apple.com/app-store/app-privacy-details/

- [ ] **Возрастной рейтинг (новая анкета, 13+/16+/18+)** С 31.01.2026 без ответов на новую анкету отправка заблокирована. Отметить User-Generated Content (имена и лиги), Contests («trivia quizzes, or sport… contests»: викторина с рейтингом). В вопросах Social Media, вероятно, «нет»: ленты нет. · источник: https://developer.apple.com/help/app-store-connect/reference/app-information/age-ratings-values-and-definitions, https://developer.apple.com/news/upcoming-requirements/, https://developer.apple.com/news/?id=tlur8uvi

- [ ] **Privacy Policy URL, Support URL, Copyright, контакт для ревью** Privacy Policy URL обязателен. Support URL должен вести на страницу с реальными контактами. · источник: https://developer.apple.com/help/app-store-connect/reference/app-information/app-information/, https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/

- [ ] **Ссылка на Terms of Use (EULA) в метаданных** Для подписок ссылки на Terms и Privacy нужны и в приложении (есть: `lib/screens/paywall.dart:294`), и в метаданных: в описании или в поле License Agreement. · источник: https://developer.apple.com/app-store/subscriptions/

- [ ] **Notes for Review** Вписать данные тестового входа, где в приложении покупка, жалобы и удаление аккаунта, почему вход обязателен (раздел 4, вопрос 4) и какая LLM оценивает ответы (до 4000 байт). · источник: https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/

- [ ] **DSA, статус трейдера (ЕС)** Статус указывается для всех приложений. С платной подпиской мы трейдер, и адрес, телефон и email будут видны на странице приложения в ЕС. Если ЕС не нужен, исключить его витрины. · источник: https://developer.apple.com/help/app-store-connect/manage-compliance-information/manage-european-union-digital-services-act-trader-requirements/

- [ ] **Подписки в App Store Connect** Группа «Amplua PRO», продукты «Месяц» и «Год» (минимум 7 дней, 3.1.2(a)), локализация названий, скриншот пейвола для ревью, подписка отправляется на ревью вместе с первой версией. · источник: https://developer.apple.com/app-store/review/guidelines/#subscriptions

- [ ] **Скриншоты** Комплект iPhone 6.9" (6.5" не нужен, если есть 6.9"), iPad 13", если остаётся iPad. Показывать приложение в работе, не экран входа (2.3.3). Название не длиннее 30 символов, без цен и чужих брендов (2.3.7). · источник: https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/, https://developer.apple.com/app-store/review/guidelines/#accurate-metadata

### 2.3 Google Play Console

- [ ] **Закрытое тестирование: 12 тестеров, 14 дней подряд** Касается, если аккаунт разработчика личный и создан после 13.11.2023 (раздел 4, вопрос 2). До доступа к продакшену нужен closed test с 12 тестерами, которые участвуют непрерывно 14 дней. Планировать минимум 2 недели до релиза. · источник: https://support.google.com/googleplay/android-developer/answer/14151465

- [ ] **Проверка реального устройства и данные разработчика** Для нового личного аккаунта нужен физический Android 10+ без root и приложение Play Console. Юридическое имя, адрес, телефон, для организации D-U-N-S. · источник: https://support.google.com/googleplay/android-developer/answer/14316361, https://support.google.com/googleplay/android-developer/answer/10788890

- [ ] **Регистрация пакета (Android developer verification)** С 30.09.2026 все пакеты в Play должны быть зарегистрированы. `com.amplua.amplua` зарегистрировать при создании приложения и проверить статус в консоли. · источник: https://support.google.com/googleplay/android-developer/answer/16984799

- [ ] **Data safety** Заполнить:
  - собираются Email, Name, User ID, App interactions (попытки), User-generated content (ответы, лиги), Purchase history;
  - передача третьим лицам: LLM-провайдер (если он не обработчик по договору), RevenueCat;
  - encryption in transit: да;
  - удаление: в приложении и URL веб-формы (блокер 12).

  Политика конфиденциальности обязательна. · источник: https://support.google.com/googleplay/android-developer/answer/10787469, https://support.google.com/googleplay/android-developer/answer/13327111

- [ ] **Target audience and content** Возраст 13+ или 16+, детские группы не выбирать: иначе включается Families policy. · источник: https://support.google.com/googleplay/android-developer/answer/9859655

- [ ] **Контент-рейтинг (IARC)** Без рейтинга приложение удаляют (уточнение 15.07.2026). В анкете отметить взаимодействие пользователей (имена и лиги) и контент от ИИ. · источник: https://support.google.com/googleplay/android-developer/answer/9898843

- [ ] **App access** Инструкции и учётные данные тестового входа, до 5 наборов. · источник: https://support.google.com/googleplay/android-developer/answer/9859455

- [ ] **Листинг** Название не длиннее 30 символов, без эмодзи и капса, без «#1» и «Best». Если скриншоты, видео или иконка сделаны генеративным ИИ, отметить это в чекбоксе. · источник: https://support.google.com/googleplay/android-developer/answer/9898842, https://support.google.com/googleplay/android-developer/answer/17262077

- [ ] **Подписки в Play Console** Продукт PRO с base plans «месяц» и «год», привязка к RevenueCat (service account), лицензионные тестеры для покупок без списаний. Покупку нужно подтвердить в течение 3 дней (RevenueCat делает это сам). · источник: https://developer.android.com/google/play/billing/integrate

- [x] **Target API 36** В итоговом манифесте `android:targetSdkVersion="36"` (`build/app/intermediates/merged_manifest/release/.../AndroidManifest.xml`), это значение по умолчанию Flutter 3.44 (`FlutterExtension.kt:34`). Требование с 31.08.2026 выполнено. · источник: https://developer.android.com/google/play/requirements/target-sdk

- [x] **16 KB page size** `llvm-readelf -lW` по arm64 `.so` из бандла: выравнивание LOAD-сегментов 0x10000 и 0x4000. NDK 28.2 (`FlutterExtension.kt:42`). · источник: https://developer.android.com/guide/practices/page-sizes

- [x] **Credential Manager для Google Sign-In** `google_sign_in_android` 7.2.17 подключает `androidx.credentials:credentials:1.6.0` и `googleid:1.2.0` (build.gradle плагина, строки 71-73), старый GSI не используется. · источник: https://developer.android.com/identity/sign-in/legacy-gsi-migration

### 2.4 Юридические тексты

- [ ] **Политика конфиденциальности** Что обязательно указать (Apple 5.1.1(i), 5.1.2(i), Google User Data):
  - какие данные собираются (см. 2.2 и 2.3) и зачем;
  - третьи стороны поимённо: Google и Apple (вход), RevenueCat, LLM-провайдер, хостинг;
  - сроки хранения;
  - как удалить аккаунт (в приложении и веб-форма) и что остаётся по закону;
  - контакт;
  - раздел о подростках.

  HTML на публичном адресе без геоблокировки. · источник: https://developer.apple.com/app-store/review/guidelines/#data-collection-and-storage, https://support.google.com/googleplay/android-developer/answer/10144311

- [ ] **Условия использования** Подписка (цена, период, автопродление, отмена), правила UGC с нулевой терпимостью к оскорблениям в именах и названиях лиг, санкции (сброс имени, бан), ИИ-оценка носит справочный характер. Для Apple можно сослаться на стандартный EULA. · источник: https://developer.apple.com/app-store/subscriptions/, https://support.google.com/googleplay/android-developer/answer/9876937

## 3. Бэкендеру

Каждая задача меняет указанный раздел `docs/API.md`. Где раздела нет, его нужно добавить.

- [ ] **1. Прод-сервер по контракту** Сервер по `docs/API.md` с валидным TLS-сертификатом, отдельные стенд и прод. Прод работает всё время ревью (Apple 2.1(a)). Клиент собирается с `API_URL` (блокер 5). Меры безопасности для профиля и токенов (Apple 1.6). → раздел API.md: «Общие правила», «Как подключить клиент к серверу». · источник: https://developer.apple.com/app-store/review/guidelines/#app-completeness

- [ ] **2. `DELETE /v1/me` целиком** Сейчас описано: профиль, попытки, серия, лиги, revoke у Apple (`docs/API.md:52-56`). Добавить:
  - (а) при входе через Apple обменивать `authorizationCode` на refresh-токен (`/auth/token`) и хранить его, иначе отзывать нечем;
  - (б) `POST https://appleid.apple.com/auth/revoke` с `client_secret` в виде JWT на ключе SIWA;
  - (в) удалять ответы в Раздевалке, логи запросов к LLM, записи семантического кэша, жалобы и блокировки, созданные пользователем;
  - (г) удалять или анонимизировать подписчика в RevenueCat (подписка остаётся в сторе, restore после нового входа должен работать, `docs/API.md:56`);
  - (д) что хранится по закону и сколько, совпадает с политикой конфиденциальности.

  → раздел API.md: «Вход и аккаунт». · источник: https://developer.apple.com/documentation/sign_in_with_apple/revoke_tokens, https://developer.apple.com/support/offering-account-deletion-in-your-app/, https://support.google.com/googleplay/android-developer/answer/13327111

- [ ] **3. Веб-страница удаления аккаунта** Публичный URL (например, `https://<домен>/delete-account`) для Data safety. Вход через Google или Apple на вебе и кнопка удаления, либо форма запроса с подтверждением по email. Срок исполнения и что удаляется, описано на самой странице. → раздел API.md: «Вход и аккаунт» (новый подраздел «Удаление через веб»). · источник: https://support.google.com/googleplay/android-developer/answer/13327111

- [ ] **4. Вход для ревьюеров** Реализовать выбранный в разделе 4 вариант. Либо `POST /v1/auth/review {code}`, который работает только для одного служебного аккаунта и включается флагом (для Apple это demo mode, нужно согласовать в Notes), либо заранее подготовленный аккаунт под тестовую Google-учётку. В обоих случаях у аккаунта есть прогресс, лиги с участниками и доступна sandbox-покупка. → раздел API.md: «Вход и аккаунт». · источник: https://developer.apple.com/app-store/review/guidelines/#app-completeness, https://support.google.com/googleplay/android-developer/answer/9859455

- [ ] **5. Подписка: вебхуки и проверка статуса** `POST /v1/webhooks/revenuecat` (`docs/API.md:258`):
  - проверка секрета в заголовке `Authorization`;
  - идемпотентность по event id;
  - события INITIAL_PURCHASE, RENEWAL, CANCELLATION, EXPIRATION, BILLING_ISSUE, PRODUCT_CHANGE, а также REFUND и revoke, чтобы снимать PRO;
  - `sync-subscription` спрашивает REST API RevenueCat.

  Если от RevenueCat откажемся: App Store Server Notifications V2 (V1 устарели) с отдельными URL для sandbox и prod, плюс Google RTDN, на каждое уведомление сверка через Play Developer API. → раздел API.md: «Подписка PRO». · источник: https://developer.apple.com/documentation/appstoreservernotifications, https://developer.android.com/google/play/billing/getting-ready

- [ ] **6. Модерация UGC, жалобы и блокировки** Новые и изменённые эндпоинты:
  - фильтр мата и оскорблений для `PATCH /v1/me {name}`, `POST /v1/leagues` и `PATCH /v1/leagues/{id}`, ответ 400 `validation_error` с человеческим `message`;
  - `POST /v1/reports {targetType: user|league|review, targetId, reason, comment?}` → 204;
  - `POST /v1/blocks {userId}` и `DELETE /v1/blocks/{userId}`, `GET /v1/blocks`: заблокированные не видны мне в рейтингах и лигах;
  - `DELETE /v1/leagues/{id}/members/{userId}`, только создатель;
  - очередь жалоб в CMS: скрыть или сбросить имя, переименовать или удалить лигу, забанить. Реакция в течение 24 часов (Apple с 08.06.2026 требует удалять нарушающий контент).

  → раздел API.md: «Профиль и прогресс» (правила `PATCH /v1/me`), «Рейтинги и лиги», новый раздел «Жалобы и блокировки». · источник: https://developer.apple.com/app-store/review/guidelines/#user-generated-content, https://support.google.com/googleplay/android-developer/answer/9876937

- [ ] **7. ИИ-тренер: жалобы, согласие, данные** Что нужно:
  - (а) у `Attempt` типа video есть `id`, жалоба шлётся через `POST /v1/reports {targetType: review}`;
  - (б) в `Me` поле `aiConsentAt: ISO | null` и `PATCH /v1/me {aiConsent: true}`. `POST /v1/attempts/video` без согласия отвечает 403 `ai_consent_required`, это новый код ошибки, клиент по нему ветвится;
  - (в) в LLM уходят только текст ответа, амплуа и задача, без email, имени и id;
  - (г) договор с провайдером: без обучения на данных, срок хранения;
  - (д) фильтр выдачи LLM на оскорбительное и опасное плюс правила безопасности в системном промпте;
  - (е) семантический кэш (ТЗ, ч. II, п. 2.1) не должен возвращать чужой текст. Сейчас `Review.answer` это «текст игрока» (`docs/API.md:195`): из кэша брать только `checklist` и `reply`, `answer` подставлять текущий.

  → раздел API.md: «Видео-разбор и AI-тренер», «Общие правила» (коды ошибок), «Профиль и прогресс» (поле `Me`). · источник: https://support.google.com/googleplay/android-developer/answer/17190352, https://developer.apple.com/app-store/review/guidelines/#data-use-and-sharing, https://support.google.com/googleplay/android-developer/answer/17134731

- [ ] **8. Relay-адреса Apple** Принимать email на `private.icloud.com`, а не только на `privaterelay.appleid.com` (новость от 24.08.2026). Не валидировать домен email из Apple-токена по белому списку. → раздел API.md: «Вход и аккаунт». · источник: https://developer.apple.com/news/?id=1ptvdtcm

- [ ] **9. Открытые вопросы** Добавить в «Открытые вопросы к бэкенду»: провайдер LLM и договор о данных (вопрос уже есть), где хостится прод и в какой юрисдикции, оплата PRO в России (раздел 4, вопрос 1). → раздел API.md: «Открытые вопросы к бэкенду».

## 4. Неизвестно или нужно моё решение

1. **Монетизация в России и СНГ.** Регионы в клиенте: Россия, Казахстан, Беларусь, Узбекистан, Армения, Грузия (`lib/data/mock_players.dart:5`), цены в рублях.
   - Google: оплата подписок через Play в России приостановлена с 2022 года, свежего сообщения о снятии паузы нет. Для оплат из России требование Payments policy об обязательном Play Billing сейчас не применяется, так что российским пользователям Android можно продавать PRO своим способом. По Беларуси покупки тоже блокируются, но явного исключения из Payments policy нет (не подтверждено). Источник: https://support.google.com/googleplay/android-developer/answer/11950272
   - Google: если счёт выплат разработчика российский, все платные транзакции через Play проваливаются у пользователей всех стран, а подписки отменились после 25.12.2024. Источник: https://support.google.com/googleplay/android-developer/answer/15685001
   - Google: альтернативный биллинг и User Choice Billing для наших стран недоступны. В KZ, UZ, AM, GE только Play Billing. Источник: https://support.google.com/googleplay/android-developer/answer/13821247
   - Apple: витрины всех шести стран доступны (https://support.apple.com/en-us/118205). В России с 01.04.2026 оплата через операторов связи прекращена, покупки возможны только с баланса Apple Account (https://support.apple.com/en-us/126891). External Purchase для России официально не задокументирован (не подтверждено), а обход IAP запрещён правилом 3.1.1.
   - **Решить:** юрлицо и банк для выплат, где продаём PRO, нужна ли своя оплата для RU на Android (это отдельная задача клиенту и бэкенду), и учитывать ли, что на iOS в RU почти никто не сможет оплатить.
2. **Тип аккаунта разработчика Google и Apple: личный или организация.** От этого зависят closed test 12×14 (только личный), D-U-N-S и публичный адрес трейдера в ЕС (DSA).
3. **Как входит ревьюер.** Варианты: (а) отдельный Google-аккаунт без двухфакторной защиты с подготовленным прогрессом: подходит обоим сторам, кода не нужно; (б) скрытый вход по коду через `POST /v1/auth/review`: для Apple это demo mode, нужно согласие Apple. Рекомендую (а).
4. **Обязательный вход.** Apple 5.1.1(v): «If your app doesn't include significant account-based features, let people use it without a login». У нас рейтинг, лиги и синхронизация прогресса, этого, вероятно, достаточно, но полигон работает и без аккаунта. Решить: оставляем вход обязательным с обоснованием в Notes или делаем гостевой полигон. Источник: https://developer.apple.com/app-store/review/guidelines/#data-collection-and-storage
5. **iPad и альбомная ориентация** (раздел 2.1): оставить или выключить.
6. **Видео реальных матчей.** ТЗ описывает «разбор видеоэпизодов реальных матчей» (ТЗ, ч. I, п. 3). Сейчас в `assets/videos/*.mp4` клипы, отрендеренные из своих 2D-сцен (`tool/render_clips_test.dart:2-3`), прав на них не нужно. Для реальных трансляций нужны лицензии (Apple 5.2.1-5.2.3), и названия клубов и лиг нельзя ставить в иконку и название (4.1(c)). Источник: https://developer.apple.com/app-store/review/guidelines/#intellectual-property
7. **Возраст и страны распространения.** 13+ или 16+. Если выходим в США: Texas SB 2420 (Declared Age Range API у Apple, Play Age Signals у Google). Если в Австралию: правило о соцсетях до 16 лет, применимость к нам неизвестна. Источники: https://developer.apple.com/news/?id=sg176nne, https://developer.android.com/google/play/age-signals/overview, https://developer.apple.com/news/?id=y1bckxf8
8. **ИИ-тренер как «чатбот» по Apple 4.7.** Применимость не подтверждена. Жалоба на ответ (блокер 10) закрывает основной риск.
9. **Пробный период.** Если будет триал, на пейвол добавить его длительность и цену после него (Apple, Google Subscriptions).
10. **LLM-провайдер** (вопрос уже есть в `docs/API.md:322`): от него зависят тексты согласия и политики.

## 5. Источники

Дата обращения ко всем страницам: 2026-10-06. Ни один домен не был заблокирован для WebFetch. Страницы `developer.apple.com/documentation/*` читались через JSON-зеркало `developer.apple.com/tutorials/data/...`.

**Apple**

| Документ | URL | Версия или дата на странице |
| --- | --- | --- |
| App Review Guidelines | https://developer.apple.com/app-store/review/guidelines/ | без даты; правки 13.11.2025, 06.02.2026, 08.06.2026 |
| Правки Guidelines от 08.06.2026 | https://developer.apple.com/news/?id=a233fmpw | 08.06.2026 |
| Случайные чаты под 1.2 | https://developer.apple.com/news/?id=d75yllv4 | 06.02.2026 |
| Upcoming requirements (Xcode 26, iOS 13+, возрастная анкета) | https://developer.apple.com/news/upcoming-requirements/ | 28.04.2026, 09.09.2026, 31.01.2026 |
| Значения возрастного рейтинга | https://developer.apple.com/help/app-store-connect/reference/app-information/age-ratings-values-and-definitions | без даты |
| Social Media в анкете | https://developer.apple.com/news/?id=tlur8uvi | 09.07.2026 |
| Texas SB 2420 | https://developer.apple.com/news/?id=sg176nne | 03.06.2026 |
| Австралия, соцсети до 16 | https://developer.apple.com/news/?id=y1bckxf8 | 08.12.2025 |
| App Privacy details | https://developer.apple.com/app-store/app-privacy-details/ | без даты |
| Export compliance | https://developer.apple.com/documentation/security/complying-with-encryption-export-regulations | без даты |
| App information (Privacy Policy URL) | https://developer.apple.com/help/app-store-connect/reference/app-information/app-information/ | без даты |
| Platform version information (Review info, Support URL) | https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/ | без даты |
| Скриншоты | https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/ | без даты |
| DSA trader | https://developer.apple.com/help/app-store-connect/manage-compliance-information/manage-european-union-digital-services-act-trader-requirements/ | без даты |
| Required reason API | https://developer.apple.com/documentation/bundleresources/describing-use-of-required-reason-api | с 01.05.2024 |
| Коды причин | https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacyaccessedapitypes/nsprivacyaccessedapitypereasons | без даты |
| SDK, которым нужны манифест и подпись | https://developer.apple.com/support/third-party-SDK-requirements/ | без даты |
| Sign in with Apple: revoke tokens | https://developer.apple.com/documentation/sign_in_with_apple/revoke_tokens | без даты |
| Relay-домен private.icloud.com | https://developer.apple.com/news/?id=1ptvdtcm | 24.08.2026 |
| Удаление аккаунта | https://developer.apple.com/support/offering-account-deletion-in-your-app/ | без даты |
| Автопродляемые подписки | https://developer.apple.com/app-store/subscriptions/ | без даты |
| Schedule 2 (§3.8) | https://developer.apple.com/support/downloads/terms/schedules/Schedule-2-and-3-English.pdf | v126, 17.12.2025 |
| App Store Server Notifications | https://developer.apple.com/documentation/appstoreservernotifications | без даты |
| Доступность сервисов Apple по странам | https://support.apple.com/en-us/118205 | 30.09.2026 |
| Оплата в России | https://support.apple.com/en-us/126891 | 29.05.2026 |

**Google**

| Документ | URL | Версия или дата на странице |
| --- | --- | --- |
| Developer Program Policy | https://support.google.com/googleplay/android-developer/answer/17190352 (то же: /answer/18258653) | действует с 30.09.2026 |
| Индекс политик | https://play.google/developer-content-policy/ | без даты |
| Анонс политик 15.07.2026 | https://support.google.com/googleplay/android-developer/answer/17134731 | 15.07.2026 |
| Анонс политик 30.10.2025 | https://support.google.com/googleplay/android-developer/answer/16550159 | 30.10.2025 |
| Сроки по политикам | https://support.google.com/googleplay/android-developer/table/12921780 | без даты |
| Data safety | https://support.google.com/googleplay/android-developer/answer/10787469 | без даты |
| User Data | https://support.google.com/googleplay/android-developer/answer/10144311 | без даты |
| Target API | https://developer.android.com/google/play/requirements/target-sdk | обновлено 01.10.2026 |
| Target API (Play Console Help) | https://support.google.com/googleplay/android-developer/answer/11926878 | без даты |
| Удаление аккаунта | https://support.google.com/googleplay/android-developer/answer/13327111 | сроки 07.12.2023 и 31.05.2024 |
| Billing Library: сроки | https://developer.android.com/google/play/billing/deprecation-faq | обновлено 09.09.2026 |
| Billing: интеграция | https://developer.android.com/google/play/billing/integrate | обновлено 22.09.2026 |
| Billing: серверная часть, RTDN | https://developer.android.com/google/play/billing/getting-ready | обновлено 09.09.2026 |
| Subscriptions policy | https://support.google.com/googleplay/android-developer/answer/9900533 | без даты |
| Payments policy | https://support.google.com/googleplay/android-developer/answer/10281818 | без даты |
| AI-Generated Content | https://support.google.com/googleplay/android-developer/answer/14094294 | без даты |
| Маркировка AI-ассетов в листинге | https://support.google.com/googleplay/android-developer/answer/17262077 | без даты |
| User Generated Content | https://support.google.com/googleplay/android-developer/answer/9876937 | без даты |
| Закрытое тестирование для новых личных аккаунтов | https://support.google.com/googleplay/android-developer/answer/14151465 | без даты |
| Проверка устройства | https://support.google.com/googleplay/android-developer/answer/14316361 | с начала 2024 |
| Данные аккаунта разработчика | https://support.google.com/googleplay/android-developer/answer/10788890 | без даты |
| Регистрация пакетов | https://support.google.com/googleplay/android-developer/answer/16984799 | с 30.09.2026 |
| 16 KB page size | https://developer.android.com/guide/practices/page-sizes | обновлено 16.09.2026 |
| Технические требования к качеству | https://support.google.com/googleplay/android-developer/answer/17492799 | без даты |
| Target audience and content | https://support.google.com/googleplay/android-developer/answer/9859655 | без даты |
| Контент-рейтинг | https://support.google.com/googleplay/android-developer/answer/9898843 | без даты, уточнение 15.07.2026 |
| Play Age Signals | https://developer.android.com/google/play/age-signals/overview | обновлено 20.07.2026 |
| AAB и Play App Signing | https://support.google.com/googleplay/android-developer/answer/9844279 | с августа 2021 |
| App access | https://support.google.com/googleplay/android-developer/answer/9859455 | без даты |
| Миграция с legacy GSI | https://developer.android.com/identity/sign-in/legacy-gsi-migration | обновлено 06.03.2026 |
| Метаданные листинга | https://support.google.com/googleplay/android-developer/answer/9898842 | без даты |
| Россия: приостановка биллинга | https://support.google.com/googleplay/android-developer/answer/11950272 | 10.03.2022 и 02.08.2022 |
| Разработчики с российским счётом | https://support.google.com/googleplay/android-developer/answer/15685001 | с 26.12.2024 |
| Альтернативный биллинг: страны | https://support.google.com/googleplay/android-developer/answer/13821247 | без даты |

**Не подтверждено первоисточником:**
- «Цена на пейволе обязана совпадать с локализованной ценой StoreKit» дословно не найдено. Вывод сделан из страницы subscriptions («localized in available currencies») и правила 2.3.1(a).
- Недоступность IAP и External Purchase на российской витрине Apple: только форумы.
- Порог «SDK iOS 27 с апреля 2027»: только лента новостей, на странице upcoming-requirements его нет.
- Санкционная страница Google /answer/11958934: найдена в выдаче поиска, не открывалась.
- Падение GoogleSignIn iOS без URL scheme: поведение SDK, проверить на устройстве.

## 6. Пожелания (на ревью не влияют)

- На экране входа плитка с текстом «IQ», остаток FootIQ (`lib/screens/welcome.dart:85`). В `pubspec.yaml:2` описание «A new Flutter project.», в `README.md:1-3` шаблонный текст.
- Шаринг лиги ведёт на `https://amplua.app/l/<code>`, а этого адреса нет (`lib/screens/rating.dart:789-791`). Починится вместе с доменом и deep links.
- `share_plus` 11.1.0 применяет Kotlin Gradle Plugin: сборка предупреждает, что будущие версии Flutter на этом упадут (см. вывод сборки). Обновить плагин.
- R8 не настроен (`grep minify android/app/build.gradle.kts` пуст). С февраля 2027 Google вводит требование к сокращению кода для DEX больше 10 MB (https://support.google.com/googleplay/android-developer/answer/17492799).
- С апреля 2027 Google потребует восстанавливать вход на новом устройстве без действий пользователя (Zero-Tap Sign-In, Block Store), источник тот же.
- `flutter_secure_storage` добавляет в манифест `USE_BIOMETRIC` и `USE_FINGERPRINT`, хотя биометрия не используется. Можно убрать через `tools:node="remove"`.
- Apple: вступить в Small Business Program (комиссия 15%), offer codes вместо упразднённых promo codes, Accessibility Nutrition Labels (пока добровольно).

---

## Приложение: вывод проверок

`flutter analyze` (код возврата 0):

```
Analyzing footiq...
No issues found! (ran in 3.8s)
EXIT=0
```

`flutter build appbundle --release` (код возврата 0), последние строки:

```
Running Gradle task 'bundleRelease'...
WARNING: Your app uses the following plugins that apply Kotlin Gradle Plugin (KGP): share_plus
Future versions of Flutter will fail to build if your app uses plugins that apply KGP.
Font asset "CupertinoIcons.ttf" was tree-shaken, reducing it from 257628 to 10432 bytes (96.0% reduction).
Font asset "MaterialIcons-Regular.otf" was tree-shaken, reducing it from 1645184 to 1096 bytes (99.9% reduction).
Running Gradle task 'bundleRelease'...                            202,3s
√ Built build\app\outputs\bundle\release\app-release.aab (52.9MB)
EXIT=0
```

Подпись бандла (`keytool -printcert -jarfile build/app/outputs/bundle/release/app-release.aab`):

```
Owner: C=US, O=Android, CN=Android Debug
Issuer: C=US, O=Android, CN=Android Debug
SHA1: 13:05:D9:44:B7:1E:E5:65:64:9C:20:32:7E:60:D5:F2:C9:04:69:08
```

Итоговый манифест release: `minSdkVersion="24"`, `targetSdkVersion="36"`. Разрешения: `INTERNET`, `ACCESS_NETWORK_STATE`, `WAKE_LOCK`, `USE_BIOMETRIC`, `USE_FINGERPRINT`, `DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`.

Выравнивание LOAD-сегментов arm64 (`llvm-readelf -lW`, NDK 28.0): `libapp.so 0x10000`, `libflutter.so 0x10000`, `libdartjni.so 0x4000`, `libdatastore_shared_counter.so 0x4000`.

Окружение: Flutter 3.44.0 stable, Dart 3.12.0, Windows 11. iOS-сборка не выполнялась.
