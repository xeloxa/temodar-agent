<div align="center">
  <img src="assets/banner.png" alt="WP-Hunter Banner" width="600"/>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License MIT">
  <img src="https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey" alt="Platform">
</p>

<p align="center">
  <a href="https://www.producthunt.com/products/wp-hunter?embed=true&utm_source=badge-featured&utm_medium=badge&utm_campaign=badge-wp-hunter" target="_blank" rel="noopener noreferrer"><img alt="WP-Hunter - WP plugin recon & SAST tool for security researchers. | Product Hunt" width="220" height="48" src="https://api.producthunt.com/widgets/embed-image/v1/featured.svg?post_id=1084875&theme=light&t=1771939449742"></a>
</p>

<p align="center">
  <b>🌐 اللغات:</b><br>
  <a href="README.md"><img src="https://img.shields.io/badge/🇬🇧-English-blue" alt="English"></a>
  <a href="README.tr.md"><img src="https://img.shields.io/badge/🇹🇷-Türkçe-red" alt="Türkçe"></a>
  <a href="README.zh.md"><img src="https://img.shields.io/badge/🇨🇳-简体中文-yellow" alt="简体中文"></a>
  <a href="README.ar.md"><img src="https://img.shields.io/badge/🇸🇦-العربية-green" alt="العربية"></a>
  <a href="README.de.md"><img src="https://img.shields.io/badge/🇩🇪-Deutsch-orange" alt="Deutsch"></a>
</p>

WP-Hunter هي **أداة لاستطلاع إضافات/قوالب ووردبريس والتحليل الثابت (SAST)**. تم تصميمها لـ **باحثي الأمن** لتقييم **احتمالية وجود ثغرات** في الإضافات من خلال تحليل البيانات الوصفية، وأنماط التثبيت، وسجلات التحديث، وإجراء **تحليل عميق للكود المصدري مدعوم بـ Semgrep**.

## 🚀 الميزات الرئيسية

*   **لوحة تحكم ويب في الوقت الفعلي**: واجهة حديثة مدعومة بـ FastAPI للمسح والتحليل المرئي.
*   **تكامل عميق مع SAST**: مسح **Semgrep** مدمج مع دعم للقواعد المخصصة.
*   **الاستطلاع دون اتصال**: مزامنة كتالوج إضافات ووردبريس بالكامل مع قاعدة بيانات SQLite محلية للاستعلام الفوري.
*   **تسجيل المخاطر (VPS)**: تسجيل قائم على الاستدلال لتحديد "الأهداف السهلة" في نظام ووردبريس البيئي.
*   **تحليل القوالب**: دعم مسح مستودع قوالب ووردبريس.
*   **مؤمنة أمنيًا**: حماية مدمجة من SSRF وأنماط تنفيذ آمنة.

---

## 🖥️ لوحة تحكم ويب حديثة

تتميز WP-Hunter الآن بلوحة تحكم محلية قوية للباحثين المرئيين.

### معرض لوحة التحكم

<table>
  <tr>
    <td width="50%">
      <b>الواجهة الرئيسية</b><br>
      تكوين معلمات المسح باستخدام عناصر تحكم بديهية
    </td>
    <td width="50%">
      <b>سجل المسح</b><br>
      تتبع وإدارة جميع عمليات المسح السابقة
    </td>
  </tr>
  <tr>
    <td>
      <img src="assets/screenshots/dashboard-main.png" alt="Main Dashboard" width="100%"/>
    </td>
    <td>
      <img src="assets/screenshots/scan-history.png" alt="Scan History" width="100%"/>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <b>تفاصيل المسح مع Semgrep</b><br>
      تحليل SAST عميق مع تتبع المشكلات
    </td>
    <td width="50%">
      <b>مجموعات القواعد الأمنية</b><br>
      إدارة قواعد OWASP وقواعد Semgrep المخصصة
    </td>
  </tr>
  <tr>
    <td>
      <img src="assets/screenshots/scan-details.png" alt="Scan Details" width="100%"/>
    </td>
    <td>
      <img src="assets/screenshots/security-rulesets.png" alt="Security Rulesets" width="100%"/>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <b>مخرجات سطر الأوامر (CLI)</b><br>
      واجهة طرفية غنية بمعلومات الثغرات الأمنية
    </td>
  </tr>
  <tr>
    <td colspan="2">
      <img src="assets/screenshots/cli-output.png" alt="CLI Output" width="100%"/>
    </td>
  </tr>
</table>

### إمكانيات لوحة التحكم:
*   **تسلسل التنفيذ في الوقت الفعلي**: شاهد نتائج المسح تتدفق عبر WebSockets.
*   **Semgrep المدمج**: قم بتشغيل تحليل ثابت عميق على إضافات محددة بنقرة واحدة.
*   **سجل المسح**: حفظ ومقارنة جلسات المسح السابقة.
*   **نظام المفضلة**: تتبع الأهداف "المثيرة للاهتمام" لمزيد من المراجعة اليدوية.
*   **قواعد مخصصة**: أضف وأدر قواعد أمان Semgrep الخاصة بك مباشرة من واجهة المستخدم.

---

## 📦 التثبيت

### المتطلبات الأساسية
- Python 3.8 أو أعلى
- pip (مثبت حزم بايثون)
- [Semgrep](https://semgrep.dev/docs/getting-started/) (اختياري، للتحليل العميق)

### الإعداد
1. استنساخ المستودع:
```bash
git clone https://github.com/xeloxa/WP-Hunter.git
cd WP-Hunter
```
2. إنشاء وتفعيل بيئة افتراضية:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```
3. تثبيت الاعتماديات:
```bash
pip install -r requirements.txt
```

---

## 🛠️ الاستخدام

### 1. تشغيل لوحة تحكم الويب (موصى به)
```bash
python3 wp-hunter.py --gui
```
الوصول إلى الواجهة عبر `http://localhost:8080`.

### 2. مزامنة قاعدة البيانات (للاستطلاع دون اتصال)
ملء قاعدة البيانات المحلية ببيانات الإضافات الوصفية للتصفية الفورية:
```bash
# مزامنة أول 100 صفحة من الإضافات
python3 wp-hunter.py --sync-db --sync-pages 100

# مزامنة كتالوج ووردبريس بالكامل (~60 ألف إضافة)
python3 wp-hunter.py --sync-all
```

### 3. الاستعلام من قاعدة البيانات المحلية
الاستعلام من قاعدة البيانات المحلية دون الاتصال بـ WordPress API:
```bash
# العثور على إضافات بها 10 آلاف تثبيت ولم يتم تحديثها منذ عامين
python3 wp-hunter.py --query-db --min 10000 --abandoned

# البحث عن إضافات "form" ذات تقييم منخفض
python3 wp-hunter.py --query-db --search "form" --sort-by rating --sort-order asc
```

### 4. المسح عبر سطر الأوامر (الوضع الكلاسيكي)
```bash
# مسح 10 صفحات من الإضافات المحدثة مع تفعيل تحليل Semgrep
python3 wp-hunter.py --pages 10 --semgrep-scan --limit 20
```

---

## 🎯 استراتيجيات الصياد

### 1. صيد "الزومبي" (معدل نجاح مرتفع)
استهداف الإضافات المستخدمة على نطاق واسع ولكنها مهجورة.
*   **المنطق:** غالبًا ما يفتقر الكود القديم إلى معايير الأمان الحديثة (نقص nonces، ضعف التعقيم).
*   **الأمر:** `python3 wp-hunter.py --abandoned --min 1000 --sort popular`

### 2. الوضع "العدواني"
للاستطلاع عالي السرعة والتزامن العالي عبر نطاقات كبيرة.
*   **الأمر:** `python3 wp-hunter.py --aggressive --pages 200`

### 3. فخ "التعقيد"
استهداف الوظائف المعقدة (رفع الملفات، المدفوعات) في الإضافات متوسطة المدى.
*   **الأمر:** `python3 wp-hunter.py --smart --min 500 --max 10000`

---

## 📊 منطق VPS (درجة احتمالية الثغرات الأمنية)

تعكس الدرجة (0-100) احتمالية وجود ثغرات **غير مصححة** أو **غير معروفة**:

| المقياس | الشرط | التأثير | السبب |
|--------|-----------|--------|-----------|
| **تقادم الكود** | > سنتين | **+40 نقطة** | الكود المهجور خطر بالغ. |
| **سطح الهجوم** | وسوم خطرة | **+30 نقطة** | الدفع، الرفع، SQL، النماذج ذات تعقيد عالٍ. |
| **الإهمال** | الدعم < 20% | **+15 نقطة** | المطورون الذين يتجاهلون المستخدمين من المحتمل أن يتجاهلوا التقارير الأمنية. |
| **تحليل الكود** | دوال خطرة | **+5-25 نقطة** | وجود `eval()`، `exec()` أو AJAX غير محمي. |
| **الديون التقنية** | WP قديم | **+15 نقطة** | لم يتم اختباره مع أحدث إصدار من ووردبريس. |
| **الصيانة** | تحديث < 14 يوم | **-5 نقاط** | المطورون النشطون إشارة إيجابية. |

---

## ⚖️ إخلاء مسؤولية قانوني

هذه الأداة مصممة لأغراض **البحوث الأمنية والاستطلاع المصرح به** فقط. وتهدف إلى مساعدة متخصصي الأمن والمطورين في تقييم أسطح الهجوم وتقييم صحة الإضافات. المؤلفون غير مسؤولين عن أي سوء استخدام. تأكد دائمًا من حصولك على التفويض المناسب قبل إجراء أي أنشطة متعلقة بالأمان.

## 📄 ملاحظات الترخيص

- ‏WP-Hunter مرخّص بموجب رخصة MIT (`LICENSE`).
- يُستخدم Semgrep كأداة فحص من طرف ثالث، ويظل خاضعًا لرخصته الخاصة `LGPL-2.1`.
- راجع `THIRD_PARTY_LICENSES.md` للتفاصيل.
