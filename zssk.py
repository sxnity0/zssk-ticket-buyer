#!/usr/bin/env python3
"""Linux/Python 3.10+. Automatizovaná príprava nulových lístkov ZSSK.

Použitie:
  python3 -m venv .venv
  .venv/bin/pip install playwright
  .venv/bin/python -m playwright install chromium
  .venv/bin/python zssk.py --setup
  .venv/bin/python zssk.py --run

Bez --run vypíše rozpis na kalendárny mesiac od dneška.
Nákup pokračuje cez nulovú platbu až po potvrdenie vystavenia.
Pri nejasnom výsledku sa beh zastaví a vyžaduje overenie objednávky.
Údaje sa ukladajú len do ~/.local/share/zssk-helper, nie do tohto súboru.
"""
import argparse
import calendar
import fcntl
import getpass
import json
import os
import re
import sys
import time as clock
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Bratislava')
ORIGIN, DESTINATION = 'Poprad-Tatry', 'Liptovský Mikuláš'
BASE = Path.home() / '.local/share/zssk-helper'
CONFIG, HISTORY = BASE / 'config.json', BASE / 'history.json'
URL = 'https://predaj.zssk.sk/search'


def save(path, data):
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as f:
        os.chmod(temp, 0o600)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def month_end(day):
    year, month = day.year + (day.month == 12), day.month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


DEFAULT_TIMETABLE = {'0':'14:35','1':'14:35','2':'14:35','3':'13:35','4':'13:35'}


def timetable(config=None):
    return dict((config or {}).get('timetable', DEFAULT_TIMETABLE))


def schedule(now=None, excluded=(), config=None):
    now = datetime.now(TZ) if now is None else now.astimezone(TZ)
    return range_schedule(now.date(), month_end(now.date()) - timedelta(days=1), now, excluded, config)


def range_schedule(start, end, now=None, excluded=(), config=None):
    if end < start or (end - start).days > 365:
        raise ValueError('Vyber rozsah od–do, najviac jeden rok.')
    now = datetime.now(TZ) if now is None else now.astimezone(TZ)
    excluded = set(excluded)
    times = timetable(config)
    day, result = max(start, now.date()), []
    while day <= end:
        departure = times.get(str(day.weekday()))
        if departure and day.isoformat() not in excluded:
            if datetime.combine(day, time.fromisoformat(departure), TZ) > now:
                result.append((day, departure))
        day += timedelta(days=1)
    return result


def route(config=None):
    config = config or {}
    return config.get('origin', ORIGIN), config.get('destination', DESTINATION)


def journey_key(day, departure, config=None):
    origin, destination = route(config)
    return f'{day.isoformat()}|{departure}|{origin}|{destination}' 


def setup():
    print('Údaje zadávaš lokálne. Pri --run budú odoslané iba do predaj.zssk.sk.')
    config = {
        'email': input('E-mail na zaslanie lístkov: ').strip(),
        'firstname': input('Meno podľa preukazu: ').strip(),
        'lastname': input('Priezvisko podľa preukazu: ').strip(),
        'discount_number': getpass.getpass('Číslo zľavy ZSSK (nie automaticky číslo ISIC): ').strip(),
        'age_category': 'Dieťa 16 - 17 r.',
        'exclude_dates': [],
    }
    if not all(config[k] for k in ('email', 'firstname', 'lastname', 'discount_number')):
        raise ValueError('Všetky údaje sú povinné.')
    if '@' not in config['email']:
        raise ValueError('Neplatný e-mail.')
    print('Kategória: 16–17 rokov; po dovŕšení 18 rokov zmeň age_category v konfigurácii.')
    save(CONFIG, config)
    print('Konfigurácia uložená:', CONFIG)


def visible_text(page):
    return page.locator('body').inner_text()


def wait_for(page, predicate, timeout=60):
    end = clock.monotonic() + timeout
    while clock.monotonic() < end:
        text = visible_text(page)
        if re.search(r'verify you are human|checking your browser|captcha|robot', text, re.I):
            raise RuntimeError('Web žiada overenie človeka. Skript ho neobchádza.')
        if 'Zvolená ponuka na vybrané vlakové spojenie je už vypredaná' in text:
            raise SoldOut('Nulová ponuka je vypredaná.')
        if predicate(text):
            return text
        page.wait_for_timeout(400)
    raise RuntimeError('Web nedokončil požadovaný krok do 60 sekúnd.')


class SoldOut(RuntimeError):
    pass


def zero_price(page):
    text = page.get_by_role('heading', name=re.compile('Celková suma')).inner_text()
    normalized = re.sub(r'\s+', '', text).removeprefix('Celkovásuma')
    match = re.fullmatch(r'(\d+[.,]\d{2})€', normalized)
    if match is None or Decimal(match.group(1).replace(',', '.')) != 0:
        raise RuntimeError('Celková suma nie je jednoznačne 0,00 €. Zastavené.')


def station(page, selector, value):
    field = page.locator(selector)
    field.fill(value[:-1])
    field.press_sequentially(value[-1])
    page.get_by_role('option', name=value, exact=True).click(timeout=30000)
    if field.input_value().strip() != value:
        raise RuntimeError('Stanica nebola správne zvolená.')


def select_date(page, day):
    page.get_by_role('button', name='Depart Date', exact=True).click()
    milliseconds = int(datetime.combine(day, time(), timezone.utc).timestamp() * 1000)
    target = page.locator(f'td.day[data-date="{milliseconds}"]:visible')
    for _ in range(24):
        if target.count() == 1:
            break
        calendar_table = page.locator('table:visible').filter(has_text='Dnes')
        forward = calendar_table.locator('th.next')
        if forward.count() != 1:
            raise RuntimeError('Kalendár ZSSK neumožňuje vybrať požadovaný dátum.')
        forward.click()
        page.wait_for_timeout(100)
    else:
        raise RuntimeError('Požadovaný dátum nie je dostupný v kalendári ZSSK.')
    target.click()
    actual = page.locator('#departDate').input_value()
    parts = [int(x) for x in re.findall(r'\d+', actual)]
    if parts != [day.day, day.month, day.year]:
        raise RuntimeError(f'Vybraný nesprávny dátum: {actual}')


def prepare(page, day, departure, config):
    origin, destination = route(config)
    page.goto(URL, wait_until='domcontentloaded')
    page.locator('#fromInput').wait_for(state='visible')
    station(page, '#fromInput', origin)
    station(page, '#toInput', destination)
    select_date(page, day)
    page.locator('#departTime').fill(departure)
    page.locator('#departTime').press('Tab')
    page.get_by_role('button', name='Vyhľadať spojenie', exact=True).click()
    display_date = day.strftime('%d.%m.%Y')
    wait_for(page, lambda t: display_date in t and page.locator('.connection-group').count() > 0)
    rows = page.locator('.connection-group').filter(
        has=page.get_by_role('rowheader', name=departure, exact=True))
    # Iba priamy vlak so správnou dvojicou staníc a prvým časom odchodu.
    matches = []
    for group in rows.all():
        tables = group.locator('.connectionItem .table-timetable')
        if tables.count() != 1:
            continue
        headers = tables.locator('th').all_text_contents()
        stops = tables.locator('.trainStop').all_text_contents()
        if (headers and headers[0].strip() == departure and
                [s.strip() for s in stops] == [origin, destination]):
            matches.append(group)
    if len(matches) != 1:
        raise RuntimeError('Presný priamy spoj neexistuje alebo výsledok nie je jednoznačný.')
    group = matches[0]
    group.locator('.searchConnectionCart').click()
    group.get_by_role('link', name=re.compile('Kúpiť lístok')).click()
    wait_for(page, lambda t: 'Voľba cestujúcich (1 osoba)' in t)
    selected_age = page.get_by_text(config['age_category'], exact=True).and_(page.locator(':visible'))
    if not selected_age.is_visible():
        page.get_by_text('Dospelý 26 - 61 r.', exact=True).and_(page.locator(':visible')).click()
        selected_age.click()
    selected_discount = page.get_by_text('Žiak/študent 100%ZzC', exact=True).and_(page.locator(':visible'))
    if not selected_discount.is_visible():
        page.get_by_text('Bez dodatočnej zľavy', exact=True).and_(page.locator(':visible')).click()
        selected_discount.click()
    claim = page.get_by_role('checkbox', name=re.compile('Nárok na 100 % zľavu'))
    claim.wait_for(state='visible')
    if not claim.is_checked():
        raise RuntimeError('Nárok na 100 % zľavu nie je označený.')
    page.get_by_role('link', name='Pokračovať', exact=True).click()
    wait_for(page, lambda t: 'Voľba cestovného lístka (1 osoba)' in t and 'Celková suma' in t)
    if display_date not in visible_text(page) or departure not in visible_text(page):
        raise RuntimeError('Ponuka neobsahuje požadovaný dátum a čas.')
    zero_price(page)
    page.get_by_role('link', name='Pokračovať', exact=True).click()
    wait_for(page, lambda t: page.get_by_role('heading', name='Obsah košíka', exact=True).is_visible())
    zero_price(page)
    # Nový izolovaný kontext pre každý deň: jedna cesta, jeden cestujúci.
    if page.get_by_role('button', name=re.compile('odstrániť')).count() != 1:
        raise RuntimeError('Košík obsahuje neočakávaný počet položiek.')
    page.get_by_role('link', name='Pokračovať', exact=True).click()
    wait_for(page, lambda t: page.get_by_role('heading', name='Osobné údaje', exact=True).is_visible())
    fields = [('#email', 'email'), ('input[id$=":firstname"]', 'firstname'),
              ('input[id$=":lastname"]', 'lastname'),
              ('input[id$=":cislo-registracie-p1"]', 'discount_number')]
    for selector, key in fields:
        field = page.locator(selector)
        if field.count() != 1:
            raise RuntimeError('Zmenený formulár osobných údajov.')
        field.fill(config[key])
        field.press('Tab')
        page.wait_for_timeout(600)


class CheckoutStopped(RuntimeError):
    pass


def checkout_text(text):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', text)
                   if not unicodedata.combining(c)).lower()


def checkout_control(page, names):
    pattern = re.compile(names, re.I)
    items = page.get_by_role('link', name=pattern).or_(
        page.get_by_role('button', name=pattern)).and_(page.locator(':visible'))
    if items.count() != 1:
        raise RuntimeError('Tlačidlo ďalšieho kroku nie je jednoznačné.')
    return items


def assert_summary(text, day, departure, config):
    normalized = checkout_text(text)
    if not re.search(rf'(?<!\d)0?{day.day}\.\s*0?{day.month}\.\s*{day.year}(?!\d)', normalized):
        raise RuntimeError('Súhrn nemá požadovaný dátum.')
    if not re.search(rf'(?<!\d){re.escape(departure)}(?!\d)', normalized):
        raise RuntimeError('Súhrn nemá požadovaný odchod.')
    for value in (*route(config), config['firstname'], config['lastname'], config['email']):
        if checkout_text(value) not in normalized:
            raise RuntimeError('Súhrn nemá správnu trasu alebo cestujúceho.')
    if not re.search(r'celkova suma|total sum|total amount', normalized):
        raise RuntimeError('Chýba celková suma objednávky.')
    amounts = re.findall(r'(?<![\d.,])(-?\d+(?:[\s\u00a0]\d{3})*[.,]\d{2})\s*€', text)
    if not amounts or any(Decimal(re.sub(r'\s+', '', a).replace(',', '.')) != 0 for a in amounts):
        raise RuntimeError('Súhrn obsahuje platenú alebo nejasnú sumu.')
    if not re.search(r'nulova platba|zero payment|bez uhrady|bezplatn', normalized):
        raise RuntimeError('Súhrn nepotvrdzuje nulovú platbu.')
    if re.search(r'1\.\s*trieda|first class|1st class', normalized):
        raise RuntimeError('Súhrn obsahuje prvú triedu.')


def issued_order(text, has_ticket=False):
    normalized = checkout_text(text)
    success = re.search(r'(?:objednavk\w*|nakup|platba).*?(?:uspes|dokonc|potvrden)|'
                        r'(?:order|purchase|payment).*?(?:successful|completed|confirmed)|'
                        r'(?:listok|doklad).*?vystaven|ticket.*?issued|dakujeme.*?nakup|thank you.*?purchase', normalized, re.S)
    if not (success or has_ticket):
        return None
    match = re.search(r'(?:cislo\s+(?:objednavky|nakupu)|order\s*(?:number|no\.?|id)|'
                      r'objednavka\s*(?:c\.|cislo))\s*[:#]?\s*([A-Z0-9][A-Z0-9/-]{3,79})(?![\w/-])',
                      normalized, re.I)
    return match.group(1).upper() if match and re.search(r'\d', match.group(1)) else None


def document_confirmed(text, url, has_save):
    from urllib.parse import urlparse
    target = urlparse(url)
    return (target.scheme == 'https' and target.hostname == 'predaj.zssk.sk'
            and target.path.rstrip('/') == '/document' and has_save
            and bool(re.search(r'vasa platba prebehla v poriadku|your payment.*(?:successful|completed)',
                               checkout_text(text))))



def accept_terms(page, stopped=lambda: False):
    text = checkout_text(visible_text(page))
    if not re.search(r'obchodn.*podmien|trade conditions|terms', text):
        raise RuntimeError('Chýba súhlas s obchodnými podmienkami.')
    inputs = page.locator('input[type="checkbox"]')
    index = inputs.evaluate_all("""inputs => {
        const norm = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
        const match = s => /obchodn.*podmien|trade conditions|terms/.test(norm(s));
        const matches = [];
        inputs.forEach((input, index) => {
            if (Array.from(input.labels || []).some(label => match(label.textContent))) {
                matches.push(index); return;
            }
            let parent = input.parentElement;
            for (let level = 0; parent && level < 5; level++, parent = parent.parentElement) {
                const text = parent.textContent || '';
                if (text.length < 600 && match(text) && parent.querySelectorAll('input[type=checkbox]').length === 1) {
                    matches.push(index); return;
                }
            }
        });
        if (matches.length === 1) return matches[0];
        return inputs.length === 1 ? 0 : -1;
    }""")
    if index < 0:
        raise RuntimeError('Nenašiel som jednoznačné políčko obchodných podmienok.')
    terms = inputs.nth(index)
    if stopped():
        raise CheckoutStopped('Beh bol zastavený pred súhlasom.')
    if not terms.is_checked():
        widget = terms.locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " ui-chkbox ")][1]').locator('.ui-chkbox-box')
        if widget.count() == 1 and widget.is_visible():
            widget.click()
        else:
            try:
                terms.check(timeout=2000)
            except Exception:
                if stopped():
                    raise CheckoutStopped('Beh bol zastavený pred súhlasom.')
                if not terms.is_checked():
                    terms.evaluate("""input => {
                        if (input.disabled) throw new Error('Súhlas je zakázaný');
                        if (!input.checked) input.click();
                    }""")
        for _ in range(20):
            if terms.is_checked():
                return
            page.wait_for_timeout(100)
        raise RuntimeError('Políčko obchodných podmienok po kliknutí zostalo prázdne.')


def payment_form_ready(page, text):
    from urllib.parse import urlparse
    return (urlparse(page.url).path.rstrip('/') == '/payment'
            and bool(re.search(r'bez uhrady|nulova platba|zero payment', checkout_text(text)))
            and page.locator('input[type="radio"]').count() > 0
            and page.locator('input[type="checkbox"]').count() > 0)


def finish_purchase(page, day, departure, config, stopped=lambda: False, progress=lambda message: None, dry_run=False):
    def check_stop():
        if stopped():
            raise CheckoutStopped('Beh bol zastavený pred ďalším krokom.')
    def click(names):
        control = checkout_control(page, names)
        check_stop()
        control.click()
    check_stop()
    progress('Overujem osobné údaje...')
    click(r'^\s*(Pokračovať|Continue)\s*$')
    def payment_ready(text):
        if re.search(r'nesuhlasi|neplatn|invalid|does not match|required|povinne', checkout_text(text)):
            raise RuntimeError('ZSSK odmietla osobné údaje. Skontroluj formulár.')
        return payment_form_ready(page, text)
    wait_for(page, payment_ready)
    check_stop()
    progress('Vyberám nulovú platbu a potvrdzujem obchodné podmienky...')
    zero = page.get_by_role('radio', name=re.compile(r'nulov[aá] platba|zero payment|bez [uú]hrady|bezplatn', re.I))
    if zero.count() != 1:
        radios = page.locator('input[type="radio"]')
        text = checkout_text(visible_text(page))
        if radios.count() != 1 or not re.search(r'nulova platba|zero payment|bez uhrady', text):
            raise RuntimeError('Nulová platba nie je jednoznačne dostupná.')
        zero = radios
    check_stop()
    if not zero.is_checked():
        zero.evaluate('(input) => { if (!input.checked && !input.disabled) input.click(); }')
    if not zero.is_checked():
        raise RuntimeError('Nulová platba sa nepodarila zvoliť.')
    accept_terms(page, stopped)
    click(r'^\s*(Pokračovať|Continue)\s*$')
    wait_for(page, lambda t: bool(re.search(r'suhrn|overview', checkout_text(t))) and
             bool(re.search(r'celkova suma|total sum|total amount', checkout_text(t))))
    assert_summary(visible_text(page), day, departure, config)
    if dry_run:
        progress('Test prešiel: súhrn a cenu 0 € som overil. Platbu nepotvrdzujem.')
        return None
    progress('Spoj a cenu 0 € som overil. Vystavujem lístok...')
    # Only one submission: a timeout after this click must never trigger a retry.
    click(r'^\s*(Platba|Zaplatiť|Payment|Pay)\s*$')
    progress('Čakám na potvrdenie vystavenia od ZSSK...')
    result = {}
    def confirmed(text):
        ticket = page.get_by_role('link', name=re.compile(
            r'(?:stiahnuť|download).*(?:líst|doklad|ticket)|(?:líst|doklad|ticket).*(?:pdf|download)', re.I))
        order = issued_order(text, any(item.is_visible() for item in ticket.all()))
        save_ticket = page.get_by_role('link', name=re.compile(r'^\s*(Uložiť lístok|Save ticket)\s*$', re.I)).or_(
            page.get_by_role('button', name=re.compile(r'^\s*(Uložiť lístok|Save ticket)\s*$', re.I)))
        has_save = any(item.is_visible() for item in save_ticket.all())
        if order or document_confirmed(text, page.url, has_save):
            result['order'] = order
            return True
        return False
    wait_for(page, confirmed, timeout=90)
    return result['order']


def run(config, journeys, history, limit):
    from playwright.sync_api import sync_playwright
    if any(item.get('verification') == 'needs_review' for item in history.values()):
        raise RuntimeError('Najprv over prerušenú objednávku na osobnej stránke.')
    pending = [(d, t) for d, t in journeys if journey_key(d, t, config) not in history]
    if limit:
        pending = pending[:limit]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            for day, departure in pending:
                key = journey_key(day, departure, config)
                if datetime.combine(day, time.fromisoformat(departure), TZ) <= datetime.now(TZ):
                    continue
                context = browser.new_context(locale='sk-SK', timezone_id='Europe/Bratislava')
                page = context.new_page()
                page.set_default_timeout(60000)
                page.set_default_navigation_timeout(60000)
                history[key] = {'verification': 'needs_review', 'recorded_at': datetime.now(TZ).isoformat()}
                save(HISTORY, history)
                try:
                    try:
                        prepare(page, day, departure, config)
                    except SoldOut:
                        del history[key]
                        save(HISTORY, history)
                        continue
                    order = finish_purchase(page, day, departure, config, progress=print)
                    history[key] = {'order': order, 'recorded_at': datetime.now(TZ).isoformat(),
                                    'verification': 'zssk_confirmed',
                                    'confirmation': 'ZSSK potvrdila vystavenie dokladu'}
                    save(HISTORY, history)
                    print(f'{day} {departure}: lístok potvrdený ZSSK.')
                except Exception as exc:
                    print('Zastavené:', type(exc).__name__)
                    print('Výsledok over v e-maile alebo na webe. Záznam zostáva na overenie.')
                    input('Enter po kontrole (ukončí beh): ')
                    return 1
                finally:
                    context.close()
        finally:
            browser.close()
    print('Beh dokončený. Potvrdené nákupy sú uložené v histórii.')
    return 0


def main():
    os.umask(0o077)
    BASE.mkdir(parents=True, exist_ok=True, mode=0o700)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--limit', type=int, default=0, help='Na prvý test použi --limit 1')
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('--limit nesmie byť záporný')
    with (BASE / 'run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Skript už beží v inom procese.', file=sys.stderr)
            return 1
        if args.setup:
            setup()
            return 0
        config = json.loads(CONFIG.read_text()) if CONFIG.exists() else {'exclude_dates': []}
        history = json.loads(HISTORY.read_text()) if HISTORY.exists() else {}
        trips = schedule(excluded=config.get('exclude_dates', []), config=config)
        for day, departure in trips:
            status = 'už potvrdené' if journey_key(day, departure, config) in history else 'čaká'
            print(f'{day} {departure}  {ORIGIN} → {DESTINATION}  [{status}]')
        print(f'{len(trips)} pracovných dní; víkendy vynechané, sviatky/prázdniny zahrnuté.')
        if args.run:
            if not CONFIG.exists():
                parser.error('Najprv spusti --setup.')
            return run(config, trips, history, args.limit)
        return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nUkončené. Nekupujem ani nepotvrdzujem ďalší lístok.')
        sys.exit(130)
