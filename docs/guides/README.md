# أدلة المستخدمين

> **English summary:** End-user guides, Arabic first with a short English summary at the top of each. One guide per role (the 12 roles of the system), a shared basics guide, and a simple guide for patients using the portal. Screen names, routes and button labels are quoted from the Arabic UI (`frontend/src/i18n/locales/ar/*.json`) and the routes in `frontend/src/features/*/routes.tsx`. Server-level tasks (install, backup, restore, update, failures) are in [the runbooks](../runbooks/).

ابدأ بدليل [الأساسيات](basics.md): تسجيل الدخول، تغيير كلمة المرور، قفل الحساب، اللغة والمظهر، الإشعارات، البحث السريع، الاختصارات، وكيف تظهر رسائل الخطأ.

## أدلة الأدوار

| الدور في النظام | رمز الدور | الدليل |
|---|---|---|
| موظف استقبال | `receptionist` | [reception.md](reception.md) |
| طبيب | `doctor` | [doctor.md](doctor.md) |
| كاشير | `cashier` | [cashier.md](cashier.md) |
| مشرف الكاشير | `cashier_supervisor` | [cashier-supervisor.md](cashier-supervisor.md) |
| صيدلي | `pharmacist` | [pharmacist.md](pharmacist.md) |
| فني معمل | `lab_tech` | [lab-technician.md](lab-technician.md) |
| مشرف المعمل | `lab_supervisor` | [lab-supervisor.md](lab-supervisor.md) |
| ممرض | `nurse` | [nurse.md](nurse.md) |
| محاسب | `accountant` | [accountant.md](accountant.md) |
| مدير | `manager` | [manager.md](manager.md) |
| مدير النظام | `admin` | [system-admin.md](system-admin.md) |
| شاشة الانتظار | `display` | [waiting-room-display.md](waiting-room-display.md) |

قد يحمل المستخدم أكثر من دور، فيقرأ كل دليل يخصه. ما تراه في القائمة يتبع صلاحياتك، ويستطيع مدير النظام تعديل مصفوفة الصلاحيات، لذلك قد يختلف ما تراه قليلاً عن الدليل.

## دليل المرضى

- [بوابة المريض](patient-portal.md): الدخول برقم الملف والهاتف ورمز الإيصال، المواعيد والحجز، النتائج، الوصفات، الفواتير، والتحقق من الإيصال.

## قواعد يجب أن يعرفها الجميع

1. لا تُقدَّم خدمة قبل فوترتها ودفعها، إلا بتصريح «التنفيذ قبل الدفع» موثق من المشرف.
2. الفاتورة المعتمدة لا تتغير أبداً، والتصحيح يكون بإشعار دائن مرتبط بها.
3. الوردية المغلقة لا تتغير، وأي أثر لاحق يُسجَّل في الوردية المفتوحة الحالية.
4. كل إلغاء أو خصم أو استرداد أو تأكيد تحويل أو تجاوز يسجل السبب ومن اعتمده والوقت.
5. ينقص المخزون عند الصرف فقط، ولا يصبح سالباً أبداً.
6. سعر السطر يتجمد عند اعتماد الفاتورة من قائمة الأسعار السارية ذلك اليوم.
7. حصة جهة التأمين دين على الجهة، وليست نقداً، حتى تُسجَّل دفعة الجهة.

ملاحظة: بعض الشاشات الموصوفة (دور «شاشة الانتظار»، إصدار رموز البوابة من ملف المريض، إلغاء التنويم الخاطئ، مرتجعات الصرف، الاسم العلمي بالعربية، والمعتمِد الثاني لإعادة التحميل والشطب في المطالبات) تأتي مع تحديثات المرحلة 8، وبعضها معلَّم «(قادم)».
