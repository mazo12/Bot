
import os
import json
import asyncio
import re
import datetime
import time
import threading

from telethon import events
from telethon import TelegramClient, Button
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.sessions import StringSession

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice

API_ID = 6534780281
API_HASH = 'ecad214ecff6a5cd90fc141d4e32f597'
BOT_TOKEN = "7139071341:AAFi_CmL_byjRX8qQmhLSb1I--PP1w8eG6w"
REG_ID = 6534780281
REG_HASH = '00b2d8f59c12c1b9a4bc63b70b461b2f'
PAY_TOKEN = "7139071341:AAFi_CmL_byjRX8qQmhLSb1I--PP1w8eG6w"

ACC_FILE = 'registered_accounts.json'
NUM_FILE = 'numbers_for_sale.json'
USER_FILE = 'user_data.json'
CONF_FILE = 'bot_settings.json'

client = TelegramClient('BotSession', API_ID, API_HASH)
bot = telebot.TeleBot(BOT_TOKEN)
pay_token = PAY_TOKEN

u_clients = {}
code_reqs = {}
res_timers = {}
u_sessions = {}
avail_nums = {}
syyad_users = {}

syyad_conf = {
    'admin_ids': [],
    'dailyGiftPoints': 0,
    'referralPoints': 0,
    'chargeRates': [],
    'reservationTimeoutMinutes': 60,
    'publish_channel_id': None
}

def load(fpath, d_val):
    if os.path.exists(fpath):
        with open(fpath, 'r', encoding='utf-8') as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                return d_val
    return d_val

def save(fpath, data):
    with open(fpath, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

def load_all():
    global u_sessions, avail_nums, syyad_users, syyad_conf
    u_sessions = load(ACC_FILE, {})
    avail_nums = load(NUM_FILE, {})
    syyad_users = load(USER_FILE, {})
    loaded_settings = load(CONF_FILE, {})

    syyad_conf.update(loaded_settings)
    if '5893307435' not in syyad_conf['admin_ids']:
        syyad_conf['admin_ids'].append('5893307435')

def save_all():
    save(ACC_FILE, u_sessions)
    save(NUM_FILE, avail_nums)
    save(CONF_FILE, syyad_conf)
    save(USER_FILE, syyad_users)

def get_syyad_bal(uid):
    uid_str = str(uid)
    if uid_str not in syyad_users:
        syyad_users[uid_str] = {}

    syyad_users[uid_str].setdefault('points', 0)
    syyad_users[uid_str].setdefault('stars', 0)
    syyad_users[uid_str].setdefault('lastDailyGiftClaim', None)

    save(USER_FILE, syyad_users)
    return syyad_users[uid_str]

def is_adm(uid):
    return str(uid) in syyad_conf['admin_ids']

def run_poll():
    bot.polling(none_stop=True)

async def run_timer(phone, uid, expiry):
    global avail_nums, res_timers

    rem_time = expiry - time.time()
    if rem_time <= 0:
        await end_resv(phone, notify=False)
        return

    task = asyncio.create_task(asyncio.sleep(rem_time))
    res_timers[phone] = task

    try:
        await task
        await end_resv(phone)
    except asyncio.CancelledError:
        pass
    finally:
        if phone in res_timers:
            del res_timers[phone]

async def end_resv(phone, notify=True):
    global avail_nums
    if phone in avail_nums and avail_nums[phone]['status'] == 'booked':
        booked_by = avail_nums[phone]['booked_by']
        avail_nums[phone].update({
            'status': 'available',
            'booked_by': None,
            'booking_time': None,
            'expiry_time': None,
            'deposit_paid_stars': None
        })
        save_all()

        if notify and booked_by:
            await client.send_message(
                int(booked_by),
                f"🚨 **انتهى حجز الرقم `{phone}`.**\n\n"
                f"لم يتم إتمام عملية الشراء في الوقت المحدد. الرقم متاح الآن للبيع مرة أخرى.",
                parse_mode='markdown'
            )

        await client.send_message(
            int(syyad_conf['admin_ids'][0]),
            f"🚨 **انتهى حجز الرقم `{phone}`.**\n"
            f"كان محجوزاً بواسطة `{booked_by}` ولم يتم إتمام الشراء.",
            parse_mode='markdown'
        )

    if phone in res_timers:
        res_timers[phone].cancel()
        del res_timers[phone]

async def init_resv():
    for phone, details in list(avail_nums.items()):
        if details.get('status') == 'booked' and details.get('expiry_time'):
            expiry = details['expiry_time']
            if expiry > time.time():
                asyncio.create_task(run_timer(phone, details['booked_by'], expiry))
            else:
                await end_resv(phone, notify=False)

async def init_acc(phone, api_id, api_hash, sess_str):
    if phone in u_clients and u_clients[phone].is_connected():
        return

    u_client = TelegramClient(StringSession(sess_str), api_id, api_hash)

    @u_client.on(events.NewMessage(incoming=True, chats=777000))
    async def proc_code_msg(event):
        global code_reqs
        code_match = re.search(r'Login code: (\d+)', event.message.text)
        if not code_match:
            code_match = re.search(r'\b(\d{5,})\b', event.message.text)

        if code_match:
            code = code_match.group(1)
            buyer_id = code_reqs.get(phone)

            if buyer_id:
                await client.send_message(
                    int(buyer_id),
                    f"**تم استلام الكود بنجاح**\n\n"
                    f"الرقم: `{phone}`\n"
                    f"الكود: `{code}`"
                )
                acc_details = u_sessions.get(phone, {})
                two_fa_pass = acc_details.get('two_factor_password', 'لا يوجد')
                if two_fa_pass and two_fa_pass != "لا يوجد":
                    await client.send_message(
                        int(buyer_id),
                        f"كلمة مرور التحقق بخطوتين: `{two_fa_pass}`"
                    )

                if phone in code_reqs:
                    del code_reqs[phone]
            raise events.StopPropagation

    try:
        await u_client.connect()
        if not await u_client.is_user_authorized():
            if phone in u_clients:
                del u_clients[phone]
            return
        u_clients[phone] = u_client
    except Exception:
        if phone in u_clients:
            del u_clients[phone]

async def run_accs():
    for phone, details in u_sessions.items():
        api_id = details.get('api_id')
        api_hash = details.get('api_hash')
        sess_str = details.get('session_str')
        if api_id and api_hash and sess_str:
            asyncio.create_task(init_acc(phone, api_id, api_hash, sess_str))

async def edit_post(phone):
    if syyad_conf.get('publish_channel_id') and phone in avail_nums:
        num_details = avail_nums[phone]
        msg_id = num_details.get('publish_message_id')
        if msg_id:
            try:
                orig_msg = await client.get_messages(syyad_conf['publish_channel_id'], ids=msg_id)
                if orig_msg:
                    new_text = f"#تم_البيع\n\n{orig_msg.text}"
                    await client.edit_message(syyad_conf['publish_channel_id'], msg_id, new_text)
            except Exception:
                pass

async def add_num(event):
    async with client.conversation(event.sender_id, timeout=600) as conv:
        await conv.send_message("أرسل الرقم الذي تريد إضافته (مع رمز الدولة +):", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
        phone_resp = await conv.get_response()

        if phone_resp.text == 'إلغاء':
             await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]])
             return None, None

        phone = phone_resp.text.strip()

        if not phone.startswith('+') or not phone[1:].isdigit():
            await conv.send_message("رقم الهاتف غير صالح.", buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]])
            return None, None

        if phone in u_sessions:
            await conv.send_message("هذا الرقم مسجل بالفعل.", buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]])
            return None, None

        new_client = None
        try:
            new_client = TelegramClient(StringSession(), REG_ID, REG_HASH)
            await new_client.connect()

            two_fa_pass = "لا يوجد"
            code_req_info = await new_client.send_code_request(phone)
            await conv.send_message("تم إرسال الكود إلى الرقم، يرجى إرسال الكود المستلم:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])

            code_resp = await conv.get_response()
            if code_resp.text == 'إلغاء':
                await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]])
                return None, None

            ver_code = code_resp.text.strip()

            try:
                await new_client.sign_in(
                    phone=phone,
                    code=ver_code,
                    phone_code_hash=code_req_info.phone_code_hash
                )
            except SessionPasswordNeededError:
                await conv.send_message("الحساب محمي بكلمة مرور. يرجى إرسال كلمة المرور (التحقق بخطوتين):", buttons=[[Button.inline("إلغاء", data='cancel_op')]])

                pass_resp = await conv.get_response()
                if pass_resp.text == 'إلغاء':
                    await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]])
                    return None, None

                two_fa_pass = pass_resp.text.strip()
                await new_client.sign_in(password=two_fa_pass)

            sess_str = new_client.session.save()
            new_acc_details = {
                'api_id': REG_ID,
                'api_hash': REG_HASH,
                'session_str': sess_str,
                'two_factor_password': two_fa_pass
            }

            await conv.send_message("تم تسجيل الحساب بنجاح. الآن، أدخل تفاصيل البيع.")

            await conv.send_message("أرسل سعر الرقم بالنقاط (0 إذا لم يكن بالنقاط):", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
            pts_price_resp = await conv.get_response()
            if pts_price_resp.text == 'إلغاء':
                await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]])
                return None, None
            try:
                pts_price = int(pts_price_resp.text.strip())
            except ValueError:
                await conv.send_message("السعر بالنقاط غير صالح.", buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]])
                return None, None

            await conv.send_message("أرسل سعر الرقم بالنجوم (0 إذا لم يكن بالنجوم):", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
            star_price_resp = await conv.get_response()
            if star_price_resp.text == 'إلغاء':
                await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]])
                return None, None
            try:
                star_price = int(star_price_resp.text.strip())
            except ValueError:
                await conv.send_message("السعر بالنجوم غير صالح.", buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]])
                return None, None

            await conv.send_message("أرسل اسم الدولة:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
            ctry_resp = await conv.get_response()
            if ctry_resp.text == 'إلغاء':
                await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]])
                return None, None
            ctry_name = ctry_resp.text.strip()

            sale_info = {
                "price_points": pts_price,
                "price_stars": star_price,
                "country": ctry_name,
                "status": "available",
                "added_by": str(event.sender_id),
                "buyer_id": None,
                "booked_by": None,
                "booking_time": None,
                "expiry_time": None,
                "deposit_paid_stars": None,
                "publish_message_id": None
            }
            
            if syyad_conf.get('publish_channel_id'):
                pub_text = (
                    f"**رقم جديد متاح للبيع**\n\n"
                    f"📞 **الرقم:** `{phone}`\n"
                    f"🌍 **الدولة:** {ctry_name}\n"
                )
                if pts_price > 0:
                    pub_text += f"💰 **السعر بالنقاط:** {pts_price}\n"
                if star_price > 0:
                    pub_text += f"🌟 **السعر بالنجوم:** {star_price}\n"

                try:
                    sent_msg = await client.send_message(
                        syyad_conf['publish_channel_id'],
                        pub_text,
                        parse_mode='markdown'
                    )
                    sale_info["publish_message_id"] = sent_msg.id
                except Exception as e:
                     await conv.send_message(f"لم يتمكن من النشر في القناة: {e}")


            await conv.send_message(
                f"تمت إضافة الرقم `{phone}` بنجاح وعرضه للبيع.",
                parse_mode='markdown',
                buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]]
            )

            return {phone: new_acc_details}, {phone: sale_info}

        except FloodWaitError as e:
            await conv.send_message(f"حدث خطأ فيضان. يرجى الانتظار {e.seconds} ثانية.", buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]])
            return None, None
        except Exception as e:
            await conv.send_message(f"حدث خطأ: {str(e)}", buttons=[[Button.inline("العودة للقائمة الرئيسية", data='main_admin_menu')]])
            return None, None
        finally:
            if new_client and new_client.is_connected():
                await new_client.disconnect()

async def show_a_nums(event):
    if not avail_nums:
        await event.edit("لا توجد أرقام مضافة حالياً.", buttons=[[Button.inline("العودة لقسم الأرقام", data="admin_numbers_section")]])
        return

    lines = []
    buttons = []

    for phone, details in avail_nums.items():
        status = details.get('status', 'N/A')
        emoji = ""
        txt = ""

        if status == 'available':
            emoji = "🟢"
            txt = "متاح"
        elif status == 'booked':
            emoji = "🟡"
            booked_by = details.get('booked_by', 'N/A')
            expiry = details.get('expiry_time')
            if expiry:
                rem_sec = max(0, int(expiry - time.time()))
                mins = rem_sec // 60
                secs = rem_sec % 60
                txt = f"محجوز لـ `{booked_by}` ({mins:02d}:{secs:02d} متبقي)"
            else:
                txt = f"محجوز لـ `{booked_by}`"
        elif status == 'sold':
            emoji = "🔴"
            txt = f"مباع للمستخدم `{details.get('buyer_id', 'غير معروف')}`"

        lines.append(
            f"📞 الرقم: `{phone}`\n"
            f"🌍 الدولة: {details.get('country', 'N/A')}\n"
            f"💰 السعر (نقاط): {details.get('price_points', 0)}\n"
            f"🌟 السعر (نجوم): {details.get('price_stars', 0)}\n"
            f"{emoji} الحالة: {txt}\n"
            f"--------------------"
        )
        buttons.append([Button.inline(f"{phone} ({txt})", data=f"view_specific_number:{phone}")])

    msg = "**قائمة الأرقام المضافة:**\n\n" + "\n".join(lines)

    buttons.append([Button.inline("العودة لقسم الأرقام", data="admin_numbers_section")])
    await event.edit(msg, buttons=buttons, parse_mode='markdown')

async def show_a_del(event):
    if not avail_nums:
        await event.edit("لا توجد أرقام لحذفها حالياً.", buttons=[[Button.inline("العودة لقسم الأرقام", data="admin_numbers_section")]])
        return

    buttons = []
    for phone in avail_nums:
        buttons.append([Button.inline(f"❌ حذف الرقم {phone}", data=f"delete_number_confirm:{phone}")])

    buttons.append([Button.inline("العودة لقسم الأرقام", data="admin_numbers_section")])
    await event.edit("اختر الرقم الذي تريد حذفه:", buttons=buttons)

async def show_a_list(event):
    adm_list = "\n".join([f"- `{adm_id}`" for adm_id in syyad_conf['admin_ids']]) if syyad_conf['admin_ids'] else "لا يوجد أدمنية حالياً."
    await event.edit(
        f"**قائمة الأدمنية:**\n{adm_list}",
        buttons=[[Button.inline("العودة لقسم الأدمنية", data="admin_admins_section")]],
        parse_mode='markdown'
    )

async def show_a_rates(event):
    lines = []
    buttons = []
    if syyad_conf['chargeRates']:
        for idx, rate in enumerate(syyad_conf['chargeRates']):
            lines.append(f"- {rate['points']} نقاط مقابل {rate['stars']} نجوم")
            buttons.append([Button.inline(f"🗑️ حذف {rate['points']} نقاط بـ {rate['stars']} نجوم", data=f"delete_charge_rate:{idx}")])
    else:
        lines.append("لا توجد تسعيرات شحن معرفة حالياً.")

    msg = "**تسعيرات شحن النجوم إلى نقاط:**\n\n" + "\n".join(lines)
    buttons.insert(0, [Button.inline("➕ إضافة تسعيرة شحن", data="add_charge_rate")])
    buttons.append([Button.inline("العودة لقسم الإعدادات", data="admin_settings_section")])
    await event.edit(msg, buttons=buttons, parse_mode='markdown')

async def show_u_main(event):
    send_func = event.respond if isinstance(event, events.NewMessage.Event) else event.edit
    await send_func(
        '**أهلاً بك في بوت شراء الأرقام**', parse_mode='markdown',
        buttons=[
            [
                Button.inline('🛒 شراء رقم', 'user_buy_number_menu'),
                Button.inline('💰 شحن نقاط', 'user_charge_points_menu')
            ],
            [
                Button.inline('🎁 الهدية اليومية', 'user_daily_gift')
            ]
        ]
    )

async def show_u_ctry(event):
    countries = sorted(list(set(
        details['country'] for details in avail_nums.values() 
        if details.get('status') in ['available', 'booked']
    )))
    
    if not countries:
        await event.edit("لا توجد أرقام متاحة للبيع حالياً.", buttons=[[Button.inline("العودة للقائمة الرئيسية", data="user_main_menu")]])
        return
        
    buttons = []
    row = []
    for ctry in countries:
        row.append(Button.inline(ctry, data=f"show_country_numbers:{ctry}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([Button.inline("العودة للقائمة الرئيسية", data="user_main_menu")])
    await event.edit("اختر الدولة التي تريد شراء رقم منها:", buttons=buttons)

async def show_u_nums(event, ctry):
    nums_in_ctry = {
        phone: details for phone, details in avail_nums.items()
        if details.get('country') == ctry and details.get('status') in ['available', 'booked']
    }
    user_id = str(event.sender_id)

    avail_list = [num for num, details in nums_in_ctry.items() if details.get('status') == 'available']
    user_booked = [num for num, details in nums_in_ctry.items() if details.get('status') == 'booked' and str(details.get('booked_by')) == user_id]
    
    buttons = []

    if user_booked:
        for phone in user_booked:
            details = nums_in_ctry[phone]
            expiry = details.get('expiry_time')
            rem_sec = max(0, int(expiry - time.time()))
            mins, secs = divmod(rem_sec, 60)
            btn_txt = f"🔔 محجوز: {phone} ({mins:02d}:{secs:02d} متبقي)"
            buttons.append([Button.inline(btn_txt, data=f"view_number_details:{phone}")])
    
    if avail_list:
        for phone in avail_list:
            buttons.append([Button.inline(f"📞 {phone}", data=f"view_number_details:{phone}")])

    if not buttons:
        await event.edit(f"لا توجد أرقام متاحة حالياً في {ctry}.", buttons=[[Button.inline("العودة لاختيار الدولة", data="user_buy_number_menu")]])
        return

    buttons.append([Button.inline("العودة لاختيار الدولة", data="user_buy_number_menu")])
    await event.edit(f"الأرقام المتاحة في {ctry}:", buttons=buttons)

async def show_u_chrg(event):
    uid_str = str(event.sender_id)
    user_bal = get_syyad_bal(uid_str)

    message = (
        f"**💰 رصيدك الحالي:**\n"
        f"  - نقاط: `{user_bal['points']}`\n\n"
        f"اختر طريقة شحن النقاط:"
    )

    buttons = [
        [
            Button.inline('🔗 شحن بالنقاط (عبر رابط الإحالة)', 'user_get_referral_link'),
            Button.inline("🌟 شحن بالنجوم", 'user_charge_by_stars_menu')
        ],
        [Button.inline("العودة للقائمة الرئيسية", data="user_main_menu")]
    ]
    await event.edit(message, parse_mode='markdown', buttons=buttons)

async def show_u_star(event):
    buttons = []
    if syyad_conf['chargeRates']:
        for idx, rate in enumerate(syyad_conf['chargeRates']):
            buttons.append([Button.inline(f"شحن {rate['points']} نقطة مقابل {rate['stars']} نجوم", data=f"charge_by_stars:{idx}")])
    else:
        await event.edit("لا توجد عروض شحن بالنجوم متاحة حالياً.", buttons=[[Button.inline("العودة", data="user_charge_points_menu")]])
        return

    buttons.append([Button.inline("العودة", data="user_charge_points_menu")])
    await event.edit("اختر باقة الشحن المناسبة:", buttons=buttons)

async def hndl_a_main(event):
    send_func = event.respond if isinstance(event, events.NewMessage.Event) else event.edit
    await send_func(
        '**أهلاً بك في لوحة تحكم الأدمن**', parse_mode='markdown',
        buttons=[
            [
                Button.inline('قسم الأرقام', 'admin_numbers_section'),
                Button.inline('قسم الأدمنية', 'admin_admins_section')
            ],
            [
                Button.inline('قسم البيع والشراء', 'admin_sales_section'),
                Button.inline('قسم الرصيد', 'admin_balance_section')
            ],
            [
                Button.inline('الإعدادات', 'admin_settings_section')
            ]
        ]
    )

async def hndl_a_nums(event):
    await event.edit(
        '**إدارة الأرقام**', parse_mode='markdown',
        buttons=[
            [
                Button.inline('➕ إضافة رقم جديد للبيع', 'add_new_number'),
                Button.inline('📋 عرض الأرقام المضافة', 'view_added_numbers')
            ],
            [
                Button.inline('🗑️ حذف الأرقام المعروضة', 'delete_displayed_numbers')
            ],
            [
                Button.inline('العودة', 'main_admin_menu')
            ]
        ]
    )

async def hndl_a_add(event):
    await event.edit('جارٍ بدء عملية إضافة الرقم...')
    new_acc, sale_details = await add_num(event)
    if new_acc and sale_details:
        u_sessions.update(new_acc)
        avail_nums.update(sale_details)
        save_all()
        for phone, info in new_acc.items():
            asyncio.create_task(init_acc(phone, info['api_id'], info['api_hash'], info['session_str']))
    else:
        await event.edit('تم إلغاء عملية إضافة الرقم أو فشلت.', buttons=[[Button.inline("العودة", data='admin_numbers_section')]])

async def hndl_a_view_num(event, phone):
    if phone in avail_nums:
        details = avail_nums[phone]
        status = details.get('status', 'N/A')
        emoji = ""
        txt = ""

        if status == 'available':
            emoji = "🟢"
            txt = "متاح"
        elif status == 'booked':
            emoji = "🟡"
            booked_by = details.get('booked_by', 'N/A')
            expiry = details.get('expiry_time')
            if expiry:
                rem_sec = max(0, int(expiry - time.time()))
                mins = rem_sec // 60
                secs = rem_sec % 60
                txt = f"محجوز لـ `{booked_by}` ({mins:02d}:{secs:02d} متبقي)"
            else:
                txt = f"محجوز لـ `{booked_by}`"
        elif status == 'sold':
            emoji = "🔴"
            txt = f"مباع للمستخدم `{details.get('buyer_id', 'غير معروف')}`"

        message = (
            f"**تفاصيل الرقم:**\n"
            f"📞 الرقم: `{phone}`\n"
            f"🌍 الدولة: {details.get('country', 'N/A')}\n"
            f"💰 السعر (نقاط): {details.get('price_points', 0)}\n"
            f"🌟 السعر (نجوم): {details.get('price_stars', 0)}\n"
            f"{emoji} الحالة: {txt}\n"
            f"بواسطة: `{details.get('added_by', 'غير معروف')}`\n"
        )
        buttons = []
        if status == 'booked':
            buttons.append([Button.inline("إلغاء الحجز", data=f"admin_cancel_booking:{phone}")])
        buttons.append([Button.inline("العودة لقائمة الأرقام", data="view_added_numbers")])

        await event.edit(message, parse_mode='markdown', buttons=buttons)

async def hndl_a_end_book(event, phone):
    if phone in avail_nums and avail_nums[phone]['status'] == 'booked':
        await end_resv(phone)
        await event.answer("تم إلغاء الحجز بنجاح.", alert=True)
        await show_a_nums(event)
    else:
        await event.answer("الحجز غير موجود أو انتهى بالفعل.", alert=True)
        await show_a_nums(event)

async def hndl_a_del_conf(event, phone):
    if phone in avail_nums:
        buttons = [
            [
                Button.inline("تأكيد الحذف", data=f"delete_number_execute:{phone}"),
                Button.inline("إلغاء", data="delete_displayed_numbers")
            ]
        ]
        await event.edit(f"هل أنت متأكد من حذف الرقم `{phone}`؟ سيتم حذف جميع بياناته.", buttons=buttons, parse_mode='markdown')
    else:
        await event.answer("الرقم غير موجود.", alert=True)
        await show_a_del(event)

async def hndl_a_del_exec(event, phone):
    if phone in avail_nums:
        if phone in u_clients:
            await u_clients[phone].disconnect()
            del u_clients[phone]
        if phone in res_timers:
            res_timers[phone].cancel()
            del res_timers[phone]

        del avail_nums[phone]
        if phone in u_sessions:
            del u_sessions[phone]
        save_all()
        await event.answer(f"تم حذف الرقم `{phone}` بنجاح.", alert=True)
        await show_a_del(event)
    else:
        await event.answer("الرقم غير موجود.", alert=True)
        await show_a_del(event)

async def hndl_a_adm_sec(event):
    await event.edit(
        '**إدارة الأدمنية**', parse_mode='markdown',
        buttons=[
            [
                Button.inline('➕ رفع أدمن', 'admin_promote_admin'),
                Button.inline('➖ تنزيل أدمن', 'admin_demote_admin')
            ],
            [
                Button.inline('📋 عرض الأدمنية', 'admin_view_admins')
            ],
            [
                Button.inline('العودة', 'main_admin_menu')
            ]
        ]
    )

async def hndl_a_promo(event):
    async with client.conversation(event.sender_id, timeout=120) as conv:
        await conv.send_message("أرسل آي دي المستخدم لترفعه كأدمن:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
        user_resp = await conv.get_response()
        if user_resp.text == 'إلغاء':
            await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة لقسم الأدمنية", data='admin_admins_section')]])
            return
        user_to_promo = user_resp.text.strip()
        if not user_to_promo.isdigit():
            await conv.send_message("آي دي غير صالح.", buttons=[[Button.inline("العودة لقسم الأدمنية", data='admin_admins_section')]])
            return
        if user_to_promo in syyad_conf['admin_ids']:
            await conv.send_message("المستخدم هو أدمن بالفعل.", buttons=[[Button.inline("العودة لقسم الأدمنية", data='admin_admins_section')]])
        else:
            syyad_conf['admin_ids'].append(user_to_promo)
            save_all()
            await conv.send_message(f"تمت ترقية المستخدم `{user_to_promo}` كأدمن.", buttons=[[Button.inline("العودة لقسم الأدمنية", data='admin_admins_section')]])

async def hndl_a_demote(event):
    async with client.conversation(event.sender_id, timeout=120) as conv:
        await conv.send_message("أرسل آي دي المستخدم لتنزيله من الأدمنية:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
        user_resp = await conv.get_response()
        if user_resp.text == 'إلغاء':
            await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة لقسم الأدمنية", data='admin_admins_section')]])
            return
        user_to_demote = user_resp.text.strip()
        if not user_to_demote.isdigit():
            await conv.send_message("آي دي غير صالح.", buttons=[[Button.inline("العودة لقسم الأدمنية", data='admin_admins_section')]])
            return
        if user_to_demote not in syyad_conf['admin_ids']:
            await conv.send_message("المستخدم ليس أدمن.", buttons=[[Button.inline("العودة لقسم الأدمنية", data='admin_admins_section')]])
        elif user_to_demote == str(event.sender_id):
            await conv.send_message("لا يمكنك تنزيل نفسك من الأدمنية.", buttons=[[Button.inline("العودة لقسم الأدمنية", data='admin_admins_section')]])
        else:
            syyad_conf['admin_ids'].remove(user_to_demote)
            save_all()
            await conv.send_message(f"تم تنزيل المستخدم `{user_to_demote}` من الأدمنية.", buttons=[[Button.inline("العودة لقسم الأدمنية", data='admin_admins_section')]])

async def hndl_a_sale_sec(event):
    await event.edit(
        '**إدارة البيع والشراء**', parse_mode='markdown',
        buttons=[
            [
                Button.inline('📋 عرض الأرقام المباعة', 'admin_view_sold_numbers'),
                Button.inline('📋 عرض الأرقام المتاحة', 'admin_view_available_numbers')
            ],
            [
                Button.inline('العودة', 'main_admin_menu')
            ]
        ]
    )

async def hndl_a_sold(event):
    sold_nums = [num for num, details in avail_nums.items() if details.get('status') == 'sold']
    if not sold_nums:
        await event.edit("لا توجد أرقام مباعة حالياً.", buttons=[[Button.inline("العودة لقسم البيع والشراء", data="admin_sales_section")]])
        return

    lines = []
    for phone in sold_nums:
        details = avail_nums[phone]
        lines.append(
            f"📞 الرقم: `{phone}`\n"
            f"💰 السعر (نقاط): {details.get('price_points', 0)}\n"
            f"🌟 السعر (نجوم): {details.get('price_stars', 0)}\n"
            f"المشتري: `{details.get('buyer_id', 'غير معروف')}`\n"
            f"--------------------"
        )
    await event.edit(
        "**قائمة الأرقام المباعة:**\n\n" + "\n".join(lines),
        buttons=[[Button.inline("العودة لقسم البيع والشراء", data="admin_sales_section")]],
        parse_mode='markdown'
    )

async def hndl_a_avail(event):
    avail_filter = [num for num, details in avail_nums.items() if details.get('status') == 'available']
    if not avail_filter:
        await event.edit("لا توجد أرقام متاحة للبيع حالياً.", buttons=[[Button.inline("العودة لقسم البيع والشراء", data="admin_sales_section")]])
        return

    lines = []
    for phone in avail_filter:
        details = avail_nums[phone]
        lines.append(
            f"📞 الرقم: `{phone}`\n"
            f"🌍 الدولة: {details.get('country', 'N/A')}\n"
            f"💰 السعر (نقاط): {details.get('price_points', 0)}\n"
            f"🌟 السعر (نجوم): {details.get('price_stars', 0)}\n"
            f"--------------------"
        )
    await event.edit(
        "**قائمة الأرقام المتاحة للبيع:**\n\n" + "\n".join(lines),
        buttons=[[Button.inline("العودة لقسم البيع والشراء", data="admin_sales_section")]],
        parse_mode='markdown'
    )

async def hndl_a_bal_sec(event):
    await event.edit(
        '**إدارة أرصدة المستخدمين**', parse_mode='markdown',
        buttons=[
            [
                Button.inline('➕ إضافة نقاط لمستخدم', 'admin_add_points'),
                Button.inline('➕ إضافة نجوم لمستخدم', 'admin_add_stars')
            ],
            [
                Button.inline('العودة', 'main_admin_menu')
            ]
        ]
    )

async def hndl_a_add_pts(event):
    async with client.conversation(event.sender_id, timeout=120) as conv:
        await conv.send_message("أرسل آي دي المستخدم لإضافة النقاط له:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
        uid_resp = await conv.get_response()
        if uid_resp.text == 'إلغاء':
            await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة لقسم الرصيد", data='admin_balance_section')]])
            return
        target_uid = uid_resp.text.strip()
        if not target_uid.isdigit():
            await conv.send_message("آي دي غير صالح.", buttons=[[Button.inline("العودة لقسم الرصيد", data='admin_balance_section')]])
            return

        await conv.send_message("أرسل عدد النقاط لإضافتها:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
        pts_resp = await conv.get_response()
        if pts_resp.text == 'إلغاء':
            await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة لقسم الرصيد", data='admin_balance_section')]])
            return
        try:
            pts_amount = int(pts_resp.text.strip())
            if pts_amount <= 0: raise ValueError
        except ValueError:
            await conv.send_message("عدد نقاط غير صالح.", buttons=[[Button.inline("العودة لقسم الرصيد", data='admin_balance_section')]])
            return

        user_bal = get_syyad_bal(target_uid)
        user_bal['points'] += pts_amount
        save_all()
        await conv.send_message(f"تم إضافة `{pts_amount}` نقطة للمستخدم `{target_uid}`. رصيده الحالي: `{user_bal['points']}` نقطة.", buttons=[[Button.inline("العودة لقسم الرصيد", data='admin_balance_section')]])

async def hndl_a_add_star(event):
    async with client.conversation(event.sender_id, timeout=120) as conv:
        await conv.send_message("أرسل آي دي المستخدم لإضافة النجوم له:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
        uid_resp = await conv.get_response()
        if uid_resp.text == 'إلغاء':
            await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة لقسم الرصيد", data='admin_balance_section')]])
            return
        target_uid = uid_resp.text.strip()
        if not target_uid.isdigit():
            await conv.send_message("آي دي غير صالح.", buttons=[[Button.inline("العودة لقسم الرصيد", data='admin_balance_section')]])
            return

        await conv.send_message("أرسل عدد النجوم لإضافتها:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
        star_resp = await conv.get_response()
        if star_resp.text == 'إلغاء':
            await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة لقسم الرصيد", data='admin_balance_section')]])
            return
        try:
            star_amount = int(star_resp.text.strip())
            if star_amount <= 0: raise ValueError
        except ValueError:
            await conv.send_message("عدد نجوم غير صالح.", buttons=[[Button.inline("العودة لقسم الرصيد", data='admin_balance_section')]])
            return

        user_bal = get_syyad_bal(target_uid)
        user_bal['stars'] += star_amount
        save_all()
        await conv.send_message(f"تم إضافة `{star_amount}` نجمة للمستخدم `{target_uid}`. رصيده الحالي: `{user_bal['stars']}` نجمة.", buttons=[[Button.inline("العودة لقسم الرصيد", data='admin_balance_section')]])

async def hndl_a_set_sec(event):
    await event.edit(
        '**إعدادات البوت**', parse_mode='markdown',
        buttons=[
            [
                Button.inline('تحديد نقاط رابط الدعوة', 'admin_set_referral_points'),
                Button.inline('تحديد تسعيرات شحن النجوم', 'admin_set_charge_rates')
            ],
            [
                Button.inline('تحديد نقاط الهدية اليومية', 'admin_set_daily_gift_points'),
                Button.inline('تحديد وقت الحجز', 'admin_set_reservation_time')
            ],
            [
                Button.inline('تحديد قناة النشر', 'admin_set_publish_channel')
            ],
            [
                Button.inline('العودة', 'main_admin_menu')
            ]
        ]
    )

async def hndl_a_set_chan(event):
    async with client.conversation(event.sender_id, timeout=120) as conv:
        curr_chan = syyad_conf.get('publish_channel_id', 'لم يتم التعيين')
        await conv.send_message(
            f"القناة الحالية للنشر: `{curr_chan}`\n"
            "أرسل الآن معرف القناة الجديد (مثال: `@username` أو `-100123456789`). "
            "أرسل 'حذف' لإلغاء النشر التلقائي.",
            buttons=[[Button.inline("إلغاء", data='cancel_op')]]
        )
        resp = await conv.get_response()
        if resp.text == 'إلغاء':
            await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة لقسم الإعدادات", data='admin_settings_section')]])
            return
        
        new_chan_id = resp.text.strip()
        if new_chan_id.lower() == 'حذف':
            syyad_conf['publish_channel_id'] = None
            msg = "تم إلغاء قناة النشر."
        else:
            syyad_conf['publish_channel_id'] = new_chan_id
            msg = f"تم تحديث قناة النشر إلى `{new_chan_id}`."
        
        save_all()
        await conv.send_message(msg, buttons=[[Button.inline("العودة لقسم الإعدادات", data='admin_settings_section')]])

async def hndl_a_set_ref(event):
    async with client.conversation(event.sender_id, timeout=120) as conv:
        curr_pts = syyad_conf.get('referralPoints', 0)
        await conv.send_message(f"النقاط الحالية لرابط الدعوة: `{curr_pts}`\nأرسل عدد النقاط الجديدة لرابط الدعوة:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
        user_resp = await conv.get_response()
        if user_resp.text == 'إلغاء':
            await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة لقسم الإعدادات", data='admin_settings_section')]])
            return
        try:
            new_pts = int(user_resp.text.strip())
            if new_pts < 0: raise ValueError
            syyad_conf['referralPoints'] = new_pts
            save_all()
            await conv.send_message(f"تم تحديث نقاط رابط الدعوة إلى `{new_pts}`.", buttons=[[Button.inline("العودة لقسم الإعدادات", data='admin_settings_section')]])
        except ValueError:
            await conv.send_message("عدد نقاط غير صالح.", buttons=[[Button.inline("العودة لقسم الإعدادات", data='admin_settings_section')]])

async def hndl_a_add_rate(event):
    async with client.conversation(event.sender_id, timeout=120) as conv:
        await conv.send_message("أرسل عدد النقاط التي سيتم الحصول عليها:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
        pts_resp = await conv.get_response()
        if pts_resp.text == 'إلغاء':
            await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة لتسعيرات الشحن", data='admin_set_charge_rates')]])
            return
        try:
            pts_amount = int(pts_resp.text.strip())
            if pts_amount <= 0: raise ValueError
        except ValueError:
            await conv.send_message("عدد نقاط غير صالح.", buttons=[[Button.inline("العودة لتسعيرات الشحن", data='admin_set_charge_rates')]])
            return

        await conv.send_message("أرسل عدد النجوم التي يجب دفعها:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
        star_resp = await conv.get_response()
        if star_resp.text == 'إلغاء':
            await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة لتسعيرات الشحن", data='admin_set_charge_rates')]])
            return
        try:
            star_amount = int(star_resp.text.strip())
            if star_amount <= 0: raise ValueError
        except ValueError:
            await conv.send_message("عدد نجوم غير صالح.", buttons=[[Button.inline("العودة لتسعيرات الشحن", data='admin_set_charge_rates')]])
            return

        syyad_conf['chargeRates'].append({'points': pts_amount, 'stars': star_amount})
        save_all()
        await conv.send_message(f"تم إضافة تسعيرة شحن: {pts_amount} نقطة مقابل {star_amount} نجوم.", buttons=[[Button.inline("العودة لتسعيرات الشحن", data='admin_set_charge_rates')]])

async def hndl_a_del_rate(event, idx):
    if 0 <= idx < len(syyad_conf['chargeRates']):
        del_rate = syyad_conf['chargeRates'].pop(idx)
        save_all()
        await event.answer(f"تم حذف تسعيرة شحن: {del_rate['points']} نقطة مقابل {del_rate['stars']} نجوم.", alert=True)
    else:
        await event.answer("تسعيرة الشحن غير موجودة.", alert=True)
    await show_a_rates(event)

async def hndl_a_set_gift(event):
    async with client.conversation(event.sender_id, timeout=120) as conv:
        curr_pts = syyad_conf.get('dailyGiftPoints', 0)
        await conv.send_message(f"النقاط الحالية للهدية اليومية: `{curr_pts}`\nأرسل عدد النقاط الجديدة للهدية اليومية:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
        user_resp = await conv.get_response()
        if user_resp.text == 'إلغاء':
            await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة لقسم الإعدادات", data='admin_settings_section')]])
            return
        try:
            new_pts = int(user_resp.text.strip())
            if new_pts < 0: raise ValueError
            syyad_conf['dailyGiftPoints'] = new_pts
            save_all()
            await conv.send_message(f"تم تحديث نقاط الهدية اليومية إلى `{new_pts}`.", buttons=[[Button.inline("العودة لقسم الإعدادات", data='admin_settings_section')]])
        except ValueError:
            await conv.send_message("عدد نقاط غير صالح.", buttons=[[Button.inline("العودة لقسم الإعدادات", data='admin_settings_section')]])

async def hndl_a_set_time(event):
    async with client.conversation(event.sender_id, timeout=120) as conv:
        curr_mins = syyad_conf.get('reservationTimeoutMinutes', 60)
        await conv.send_message(f"الوقت الحالي لحجز الرقم: `{curr_mins}` دقيقة\nأرسل وقت الحجز الجديد بالدقائق:", buttons=[[Button.inline("إلغاء", data='cancel_op')]])
        user_resp = await conv.get_response()
        if user_resp.text == 'إلغاء':
            await conv.send_message("تم الإلغاء.", buttons=[[Button.inline("العودة لقسم الإعدادات", data='admin_settings_section')]])
            return
        try:
            new_mins = int(user_resp.text.strip())
            if new_mins <= 0: raise ValueError
            syyad_conf['reservationTimeoutMinutes'] = new_mins
            save_all()
            await conv.send_message(f"تم تحديث وقت حجز الرقم إلى `{new_mins}` دقيقة.", buttons=[[Button.inline("العودة لقسم الإعدادات", data='admin_settings_section')]])
        except ValueError:
            await conv.send_message("وقت غير صالح.", buttons=[[Button.inline("العودة لقسم الإعدادات", data='admin_settings_section')]])

async def hndl_u_view(event, phone, uid):
    if phone in avail_nums:
        details = avail_nums[phone]
        status = details.get('status')
        pts_price = details.get('price_points', 0)
        star_price = details.get('price_stars', 0)

        message = (
            f"**تفاصيل الرقم `{phone}`:**\n\n"
            f"🌍 الدولة: {details['country']}\n"
        )
        if pts_price > 0:
            message += f"💰 السعر بالنقاط: `{pts_price}`\n"
        if star_price > 0:
            message += f"🌟 السعر بالنجوم: `{star_price}`\n"

        buttons = []
        action_btns = []
        if status == 'available':
            if star_price > 0 and syyad_conf.get('reservationTimeoutMinutes', 0) > 0:
                action_btns.append(Button.inline(f"حجز الرقم ({star_price // 2:.0f} نجوم)", data=f"book_number:{phone}"))
            if pts_price > 0 or star_price > 0:
                action_btns.append(Button.inline("شراء الآن", data=f"choose_payment_method:{phone}:full"))
            if action_btns:
                buttons.append(action_btns)
        elif status == 'booked' and str(details.get('booked_by')) == uid:
            rem_star_amount = star_price - details.get('deposit_paid_stars', 0)
            message += (
                f"**حالة الحجز:** محجوز لك!\n"
                f"مبلغ الحجز المدفوع: `{details.get('deposit_paid_stars', 0)}` نجوم\n"
            )
            if details.get('expiry_time'):
                rem_sec = max(0, int(details['expiry_time'] - time.time()))
                mins = rem_sec // 60
                secs = rem_sec % 60
                message += f"الوقت المتبقي: `{mins:02d}:{secs:02d}` دقيقة\n\n"

            if rem_star_amount > 0:
                action_btns.append(Button.inline(f"إتمام الشراء ({rem_star_amount:.0f} نجوم)", data=f"choose_payment_method:{phone}:remaining"))
            if pts_price > 0:
                 action_btns.append(Button.inline(f"إتمام الشراء ({pts_price} نقاط)", data=f"choose_payment_method:{phone}:points_only"))
            
            if action_btns:
                buttons.append(action_btns)
            
            buttons.append([Button.inline("إلغاء الحجز", data=f"user_cancel_booking:{phone}")])
        elif status == 'booked' and str(details.get('booked_by')) != uid:
             await event.answer("هذا الرقم محجوز لمستخدم آخر حالياً.", alert=True)
             await show_u_ctry(event)
             return
        elif status == 'sold':
            await event.answer("هذا الرقم مباع بالفعل.", alert=True)
            await show_u_ctry(event)
            return

        buttons.append([Button.inline("العودة لقائمة الدول", data="user_buy_number_menu")])
        await event.edit(message, parse_mode='markdown', buttons=buttons)
    else:
        await event.answer("الرقم لم يعد متاحاً.", alert=True)
        await show_u_ctry(event)

async def hndl_u_book(event, phone):
    if phone not in avail_nums or avail_nums[phone]['status'] != 'available':
        await event.answer("الرقم غير متاح للحجز.", alert=True)
        await show_u_ctry(event)
        return

    details = avail_nums[phone]
    full_price = details.get('price_stars', 0)
    if full_price == 0:
        await event.answer("لا يمكن حجز هذا الرقم بالنجوم (لا يوجد سعر بالنجوم).", alert=True)
        await show_u_ctry(event)
        return

    dep_amount = max(1, full_price // 2)
    prices = [LabeledPrice(label=f"حجز الرقم {phone} (نصف السعر)", amount=dep_amount)]
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: bot.send_invoice(
            chat_id=event.sender_id,
            title=f"حجز الرقم {phone}",
            description=f"دفع نصف سعر الرقم ({dep_amount} نجوم) لحجزه لمدة {syyad_conf.get('reservationTimeoutMinutes', 60)} دقيقة.",
            provider_token=pay_token,
            currency="XTR",
            prices=prices,
            start_parameter=f"book_number_{phone.replace('+', '')}",
            invoice_payload=f"book_number:{phone}:{dep_amount}"
        )
    )
    await event.answer("جارٍ إعداد عملية الدفع للحجز...", alert=True)

async def hndl_u_endb_conf(event, phone, uid):
    if phone in avail_nums and avail_nums[phone]['status'] == 'booked' and str(avail_nums[phone]['booked_by']) == uid:
        buttons = [
            [
                Button.inline("نعم، إلغاء الحجز", data=f"execute_user_cancel_booking:{phone}"),
                Button.inline("لا، العودة", data=f"view_number_details:{phone}")
            ]
        ]
        await event.edit("هل أنت متأكد من إلغاء حجز الرقم؟ لن يتم استرداد مبلغ الحجز.", buttons=buttons)
    else:
        await event.answer("هذا الرقم ليس محجوزاً لك.", alert=True)
        await show_u_ctry(event)

async def hndl_u_endb_exec(event, phone, uid):
    if phone in avail_nums and avail_nums[phone]['status'] == 'booked' and str(avail_nums[phone]['booked_by']) == uid:
        await end_resv(phone)
        await event.answer("تم إلغاء الحجز بنجاح.", alert=True)
        await show_u_ctry(event)
    else:
        await event.answer("هذا الرقم ليس محجوزاً لك أو الحجز انتهى.", alert=True)
        await show_u_ctry(event)

async def hndl_u_pay_meth(event, phone, pay_type, uid):
    if phone not in avail_nums:
        await event.answer("الرقم لم يعد متاحاً.", alert=True)
        await show_u_ctry(event)
        return

    details = avail_nums[phone]
    user_bal = get_syyad_bal(uid)

    pts_price = details.get('price_points', 0)
    star_price = details.get('price_stars', 0)
    star_to_pay = 0
    pts_to_pay = 0

    if pay_type == 'remaining':
        if not (details.get('status') == 'booked' and str(details.get('booked_by')) == uid):
            await event.answer("هذا الرقم ليس محجوزاً لك لإتمام الشراء.", alert=True)
            await show_u_ctry(event)
            return
        dep_paid = details.get('deposit_paid_stars', 0)
        star_to_pay = star_price - dep_paid
        pts_to_pay = pts_price
    elif pay_type == 'full':
        if details.get('status') != 'available':
            await event.answer("هذا الرقم غير متاح للشراء المباشر.", alert=True)
            await show_u_ctry(event)
            return
        star_to_pay = star_price
        pts_to_pay = pts_price
    elif pay_type == 'points_only':
        if not (details.get('status') == 'booked' and str(details.get('booked_by')) == uid):
            await event.answer("هذا الرقم ليس محجوزاً لك لإتمام الشراء.", alert=True)
            await show_u_ctry(event)
            return
        star_to_pay = 0
        pts_to_pay = pts_price

    message = f"اختر طريقة الدفع للرقم `{phone}`:\n"
    buttons = []
    pay_row = []

    if pts_to_pay > 0:
        message += f"**السعر بالنقاط:** `{pts_to_pay}` (رصيدك: `{user_bal['points']}`)\n"
        pay_row.append(Button.inline(f"دفع {pts_to_pay} نقطة", data=f"pay_with_points:{phone}:{pay_type}"))
    if star_to_pay > 0:
        message += f"**السعر بالنجوم:** `{star_to_pay}`\n"
        pay_row.append(Button.inline(f"دفع {star_to_pay} نجمة", data=f"pay_with_stars:{phone}:{star_to_pay}"))

    if not pay_row:
        await event.answer("لا يوجد مبلغ متبقي للدفع.", alert=True)
        await hndl_u_view(event, phone, uid)
        return

    buttons.append(pay_row)
    buttons.append([Button.inline("إلغاء", data=f"view_number_details:{phone}")])
    await event.edit(message, parse_mode='markdown', buttons=buttons)

async def hndl_u_pay_pts(event, phone, pay_type, uid):
    if phone not in avail_nums:
        await event.answer("الرقم لم يعد متاحاً.", alert=True)
        await show_u_ctry(event)
        return

    details = avail_nums[phone]
    user_bal = get_syyad_bal(uid)
    
    pts_to_pay = 0
    if pay_type in ['remaining', 'points_only', 'full']:
        pts_to_pay = details.get('price_points', 0)

    if pts_to_pay > 0 and user_bal['points'] >= pts_to_pay:
        user_bal['points'] -= pts_to_pay

        is_booked = (pay_type in ['remaining', 'points_only']) and details.get('status') == 'booked'
        is_full = pay_type == 'full' and details.get('status') == 'available'

        if is_booked or is_full:
            avail_nums[phone]['status'] = 'sold'
            avail_nums[phone]['buyer_id'] = uid
            code_reqs[phone] = event.sender_id

            if is_booked:
                await end_resv(phone, notify=False)
            
            save_all()
            await edit_post(phone)

            await event.edit(
                f"تمت عملية الشراء بنجاح للرقم `{phone}`.\n\n"
                "يرجى الآن محاولة تسجيل الدخول بالرقم. سيصلك كود الدخول وكلمة المرور هنا فوراً.",
                parse_mode='markdown'
            )
            pay_method = "بالنقاط + حجز النجوم" if is_booked else "بالنقاط"
            await client.send_message(
                int(syyad_conf['admin_ids'][0]),
                f"تم شراء الرقم `{phone}` بواسطة `{uid}` ({pay_method}).",
                parse_mode='markdown'
            )
    else:
        await event.answer("نقاطك غير كافية لإتمام عملية الشراء.", alert=True)
        await event.edit("نقاطك غير كافية.", buttons=[
            [Button.inline("شحن نقاط", data='user_charge_points_menu')], 
            [Button.inline("العودة", data=f"view_number_details:{phone}")]
        ])

async def hndl_u_pay_star(event, phone, amount):
    if phone not in avail_nums:
        await event.answer("الرقم لم يعد متاحاً.", alert=True)
        await show_u_ctry(event)
        return

    prices = [LabeledPrice(label=f"شراء الرقم {phone}", amount=amount)]
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: bot.send_invoice(
            chat_id=event.sender_id,
            title=f"شراء الرقم {phone}",
            description=f"دفع {amount} نجوم لإتمام شراء الرقم {phone}.",
            provider_token=pay_token,
            currency="XTR",
            prices=prices,
            start_parameter=f"buy_number_{phone.replace('+', '')}",
            invoice_payload=f"buy_number:{phone}:{amount}"
        )
    )
    await event.answer("جارٍ إعداد عملية الدفع بالنجوم...", alert=True)

async def hndl_u_get_ref(event, uid):
    bot_info = await client.get_me()
    bot_user = bot_info.username
    ref_link = f"https://t.me/{bot_user}?start=ref_{uid}"
    await event.edit(
        f"**رابط الإحالة الخاص بك:**\n`{ref_link}`\n\n"
        f"شارك هذا الرابط مع أصدقائك. ستحصل على `{syyad_conf.get('referralPoints', 0)}` نقطة لكل مستخدم جديد يسجل عبر رابطك.",
        parse_mode='markdown',
        buttons=[[Button.inline("العودة", data="user_charge_points_menu")]]
    )

async def hndl_u_chrg_star(event, idx):
    if 0 <= idx < len(syyad_conf['chargeRates']):
        rate = syyad_conf['chargeRates'][idx]
        prices = [LabeledPrice(label=f"شحن {rate['points']} نقطة", amount=rate['stars'])]
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: bot.send_invoice(
                chat_id=event.sender_id,
                title=f"شحن نقاط",
                description=f"شحن {rate['points']} نقطة مقابل {rate['stars']} نجوم.",
                provider_token=pay_token,
                currency="XTR",
                prices=prices,
                start_parameter=f"charge_stars_{rate['points']}",
                invoice_payload=f"charge_stars:{rate['points']}:{rate['stars']}"
            )
        )
        await event.answer("جارٍ إعداد عملية الدفع بالنجوم...", alert=True)
    else:
        await event.answer("تسعيرة الشحن غير موجودة.", alert=True)
        await show_u_chrg(event)

async def hndl_u_gift(event, uid):
    user_bal = get_syyad_bal(uid)
    curr_time = time.time()
    last_claim = user_bal.get('lastDailyGiftClaim')
    gift_pts = syyad_conf.get('dailyGiftPoints', 0)

    if gift_pts == 0:
        await event.answer("الهدية اليومية غير متاحة حالياً.", alert=True)
        return

    if last_claim and (curr_time - last_claim) < 86400:
        next_claim = last_claim + 86400
        rem = int(next_claim - curr_time)
        mins, secs = divmod(rem, 60)
        hours, mins = divmod(mins, 60)
        await event.answer(f"لقد حصلت على هديتك اليومية بالفعل. يمكنك المطالبة بالهدية التالية بعد: {hours:02d} ساعة و {mins:02d} دقيقة.", alert=True)
    else:
        user_bal['points'] += gift_pts
        user_bal['lastDailyGiftClaim'] = curr_time
        save_all()
        await event.answer(f"🎉 تهانينا! لقد حصلت على `{gift_pts}` نقطة كهدية يومية!", alert=True)
        await show_u_main(event)

@client.on(events.NewMessage(pattern='/start(?: ref_(\d+))?'))
async def hndl_start(event):
    uid = str(event.sender_id)
    ref_id = event.pattern_match.group(1)

    is_new = uid not in syyad_users
    get_syyad_bal(uid)
    
    if is_new and ref_id and ref_id != uid:
        if 'referred_by' not in syyad_users.get(uid, {}):
            get_syyad_bal(ref_id)
            syyad_users[uid]['referred_by'] = ref_id
            ref_pts = syyad_conf.get('referralPoints', 0)
            if ref_pts > 0:
                syyad_users[ref_id]['points'] += ref_pts
                save_all()
                await client.send_message(int(ref_id), f"🎉 لقد ربحت `{ref_pts}` نقطة من إحالة مستخدم جديد!")

    if is_adm(event.sender_id):
        await hndl_a_main(event)
    else:
        await show_u_main(event)

@client.on(events.CallbackQuery)
async def hndl_cb(event):
    uid = str(event.sender_id)
    data = event.data.decode()

    if data == 'dummy_sep':
        await event.answer()
        return

    if is_adm(uid):
        if data == 'main_admin_menu': await hndl_a_main(event)
        elif data == 'admin_numbers_section': await hndl_a_nums(event)
        elif data == 'add_new_number': await hndl_a_add(event)
        elif data == 'view_added_numbers': await show_a_nums(event)
        elif data.startswith('view_specific_number:'): await hndl_a_view_num(event, data.split(':', 1)[1])
        elif data.startswith('admin_cancel_booking:'): await hndl_a_end_book(event, data.split(':', 1)[1])
        elif data == 'delete_displayed_numbers': await show_a_del(event)
        elif data.startswith('delete_number_confirm:'): await hndl_a_del_conf(event, data.split(':', 1)[1])
        elif data.startswith('delete_number_execute:'): await hndl_a_del_exec(event, data.split(':', 1)[1])
        elif data == 'admin_admins_section': await hndl_a_adm_sec(event)
        elif data == 'admin_promote_admin': await hndl_a_promo(event)
        elif data == 'admin_demote_admin': await hndl_a_demote(event)
        elif data == 'admin_view_admins': await show_a_list(event)
        elif data == 'admin_sales_section': await hndl_a_sale_sec(event)
        elif data == 'admin_view_sold_numbers': await hndl_a_sold(event)
        elif data == 'admin_view_available_numbers': await hndl_a_avail(event)
        elif data == 'admin_balance_section': await hndl_a_bal_sec(event)
        elif data == 'admin_add_points': await hndl_a_add_pts(event)
        elif data == 'admin_add_stars': await hndl_a_add_star(event)
        elif data == 'admin_settings_section': await hndl_a_set_sec(event)
        elif data == 'admin_set_referral_points': await hndl_a_set_ref(event)
        elif data == 'admin_set_charge_rates': await show_a_rates(event)
        elif data == 'add_charge_rate': await hndl_a_add_rate(event)
        elif data.startswith('delete_charge_rate:'): await hndl_a_del_rate(event, int(data.split(':', 1)[1]))
        elif data == 'admin_set_daily_gift_points': await hndl_a_set_gift(event)
        elif data == 'admin_set_reservation_time': await hndl_a_set_time(event)
        elif data == 'admin_set_publish_channel': await hndl_a_set_chan(event)
        elif data == 'cancel_op': await event.edit("تم الإلغاء.", buttons=[[Button.inline("العودة", data='main_admin_menu')]])
    else:
        if data == 'user_main_menu': await show_u_main(event)
        elif data == 'user_buy_number_menu': await show_u_ctry(event)
        elif data.startswith('show_country_numbers:'): await show_u_nums(event, data.split(':', 1)[1])
        elif data.startswith('view_number_details:'): await hndl_u_view(event, data.split(':', 1)[1], uid)
        elif data.startswith('book_number:'): await hndl_u_book(event, data.split(':', 1)[1])
        elif data.startswith('user_cancel_booking:'): await hndl_u_endb_conf(event, data.split(':', 1)[1], uid)
        elif data.startswith('execute_user_cancel_booking:'): await hndl_u_endb_exec(event, data.split(':', 1)[1], uid)
        elif data.startswith('choose_payment_method:'): await hndl_u_pay_meth(event, *data.split(':', 2)[1:], uid)
        elif data.startswith('pay_with_points:'): await hndl_u_pay_pts(event, *data.split(':', 2)[1:], uid)
        elif data.startswith('pay_with_stars:'): await hndl_u_pay_star(event, data.split(':', 2)[1], int(data.split(':', 2)[2]))
        elif data == 'user_charge_points_menu': await show_u_chrg(event)
        elif data == 'user_get_referral_link': await hndl_u_get_ref(event, uid)
        elif data == 'user_charge_by_stars_menu': await show_u_star(event)
        elif data.startswith('charge_by_stars:'): await hndl_u_chrg_star(event, int(data.split(':', 1)[1]))
        elif data == 'user_daily_gift': await hndl_u_gift(event, uid)

@bot.pre_checkout_query_handler(func=lambda query: True)
def hndl_pre_cq(pre_cq):
    bot.answer_pre_checkout_query(pre_cq.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def hndl_paid(paid_msg):
    uid = str(paid_msg.chat.id)
    syyad_payload = paid_msg.successful_payment.invoice_payload

    if syyad_payload.startswith("book_number:"):
        _, phone, dep_star_str = syyad_payload.split(':')
        dep_star_amount = int(dep_star_str)

        if phone in avail_nums and avail_nums[phone]['status'] == 'available':
            res_timeout = syyad_conf.get('reservationTimeoutMinutes', 60)
            expiry_time = time.time() + (res_timeout * 60)

            avail_nums[phone].update({
                'status': 'booked',
                'booked_by': uid,
                'booking_time': time.time(),
                'expiry_time': expiry_time,
                'deposit_paid_stars': dep_star_amount
            })
            save_all()

            asyncio.run_coroutine_threadsafe(run_timer(phone, uid, expiry_time), client.loop)

            bot.send_message(uid, f"✅ تم حجز الرقم `{phone}` بنجاح!\n"
                                             f"لقد دفعت `{dep_star_amount}` نجمة.\n"
                                             f"الرجاء إتمام عملية الشراء خلال `{res_timeout}` دقيقة بدفع باقي المبلغ.")
            bot.send_message(int(syyad_conf['admin_ids'][0]), f"🔔 تم حجز الرقم `{phone}` بواسطة `{uid}` (دفعة حجز: {dep_star_amount} نجوم). سينتهي الحجز في {datetime.datetime.fromtimestamp(expiry_time).strftime('%Y-%m-%d %H:%M:%S')}.")
        else:
            bot.send_message(uid, "❌ فشل حجز الرقم. الرقم غير متاح أو تم حجزه من قبل.")
            bot.send_message(int(syyad_conf['admin_ids'][0]), f"⚠️ فشلت محاولة حجز الرقم `{phone}` بواسطة `{uid}` (الرقم غير متاح).")

    elif syyad_payload.startswith("buy_number:"):
        _, phone, paid_star_str = syyad_payload.split(':')
        paid_star_amount = int(paid_star_str)

        if phone in avail_nums:
            details = avail_nums[phone]
            success = False
            method = ""

            if details['status'] == 'booked' and str(details['booked_by']) == uid:
                req_amount = details['price_stars'] - details.get('deposit_paid_stars', 0)
                if paid_star_amount >= req_amount:
                    success = True
                    method = f"إتمام حجز ({paid_star_amount} نجوم)"
                    asyncio.run_coroutine_threadsafe(end_resv(phone, notify=False), client.loop)
            elif details['status'] == 'available':
                req_amount = details.get('price_stars', 0)
                if paid_star_amount >= req_amount:
                    success = True
                    method = f"شراء مباشر ({paid_star_amount} نجوم)"

            if success:
                bot.send_message(uid, f"✅ تهانينا! تم شراء الرقم `{phone}` بنجاح.\n"
                                                  "يرجى الآن محاولة تسجيل الدخول بالرقم. سيصلك كود الدخول وكلمة المرور هنا فوراً.")
                avail_nums[phone]['status'] = 'sold'
                avail_nums[phone]['buyer_id'] = uid
                code_reqs[phone] = paid_msg.chat.id
                save_all()
                asyncio.run_coroutine_threadsafe(edit_post(phone), client.loop)
                bot.send_message(int(syyad_conf['admin_ids'][0]), f"🎉 تم شراء الرقم `{phone}` بنجاح من قبل `{uid}` ({method}).")
            else:
                bot.send_message(uid, "❌ خطأ في الدفع. المبلغ المدفوع غير كافٍ أو حالة الرقم خاطئة.")
                bot.send_message(int(syyad_conf['admin_ids'][0]), f"⚠️ خطأ في دفع الرقم `{phone}` بواسطة `{uid}`.")
        else:
            bot.send_message(uid, "❌ فشل الشراء. الرقم لم يعد متاحاً.")
            bot.send_message(int(syyad_conf['admin_ids'][0]), f"⚠️ فشلت محاولة شراء الرقم `{phone}` بواسطة `{uid}` (الرقم غير موجود).")

    elif syyad_payload.startswith("charge_stars:"):
        _, pts_str, star_str = syyad_payload.split(':')
        pts_added = int(pts_str)
        star_paid = int(star_str)

        user_bal = get_syyad_bal(uid)
        user_bal['points'] += pts_added
        save_all()

        bot.send_message(uid, f"✅ تم شحن `{pts_added}` نقطة بنجاح مقابل `{star_paid}` نجمة. رصيدك الحالي: `{user_bal['points']}` نقطة.")
        bot.send_message(int(syyad_conf['admin_ids'][0]), f"🌟 تم شحن `{pts_added}` نقطة للمستخدم `{uid}` مقابل `{star_paid}` نجمة.")
    else:
        bot.send_message(uid, "تم الدفع بنجاح، ولكن لم يتم تحديد الغرض.")

async def run_syyad_app():
    load_all()

    await client.start(bot_token=BOT_TOKEN)
    await run_accs()
    await init_resv()

    poll_thread = threading.Thread(target=run_poll, daemon=True)
    poll_thread.start()

    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(run_syyad_app())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        save_all()
