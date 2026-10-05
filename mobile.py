#!/usr/bin/env python3
"""Lokálne dotykové ovládanie a zobrazovanie prehliadača na Androide."""
import fcntl
import json
import os
import secrets
import signal
import socket
import subprocess
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, request, session, render_template
import zssk

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
                  MAX_CONTENT_LENGTH=16384)
LAUNCH_TOKEN = secrets.token_urlsafe(32)
PIN = ''.join(secrets.choice('23456789ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(8))
lock = threading.RLock()
condition = threading.Condition(lock)
state = {'running': False, 'phase': 'idle', 'message': 'Pripravené.',
         'current': '', 'completed': 0, 'total': 0}
command = None
outcomes = {}
test_target = None
stop_requested = False


def load(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(24)
    return session['csrf']


@app.before_request
def protect():
    if request.host != '127.0.0.1:8765':
        abort(403)
    if request.method == 'POST':
        if request.headers.get('Origin') not in (None, 'http://127.0.0.1:8765'):
            abort(403)
        supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf', '')
        if not secrets.compare_digest(supplied, session.get('csrf', '!')):
            abort(403)
    public = request.path in ('/login','/launch','/health') or request.path in ('/static/theme.js','/static/theme.css')
    if not public and not session.get('authenticated'):
        if request.path.startswith('/api/'):
            abort(401)
        return redirect('/login')


@app.after_request
def headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Keep the real Origin on same-origin login form submissions.
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = ''
    if request.method == 'POST':
        if secrets.compare_digest(request.form.get('pin', ''), PIN):
            session.clear()
            session['authenticated'] = True
            csrf_token()
            return redirect('/')
        error = 'Nesprávny PIN.'
    return render_template('login.html', csrf=csrf_token(), error=error)


@app.get('/launch')
def launch():
    if not secrets.compare_digest(request.args.get('token', ''), LAUNCH_TOKEN):
        abort(403)
    session.clear()
    session['authenticated'] = True
    csrf_token()
    return redirect('/')


@app.get('/health')
def health():
    return jsonify(service='zssk-web', ready=True)


@app.get('/api/browser')
def browser_url():
    return jsonify(url='http://127.0.0.1:6080/vnc.html#host=127.0.0.1&port=6080&encrypt=false&path=websockify&autoconnect=true&reconnect=true&reconnect_delay=1500&resize=scale&password=' + PIN)


@app.get('/')
def index():
    config = load(zssk.CONFIG, {})
    return render_template('dashboard.html', csrf=csrf_token(), config=config)


def pending_review(history):
    return [k for k, v in history.items() if v.get('verification') == 'needs_review']


def month_test_trip(now=None, excluded=(), history=None, config=None):
    now = datetime.now(zssk.TZ) if now is None else now.astimezone(zssk.TZ)
    day = now.date() + timedelta(days=7)
    excluded = set(excluded)
    history = history or {}
    times = zssk.timetable(config)
    for _ in range(31):
        departure = times.get(str(day.weekday()))
        if departure and day.isoformat() not in excluded:
            if zssk.journey_key(day, departure, config) not in history:
                return [(day, departure)]
        day += timedelta(days=1)
    return []


def selected_range(config):
    today = datetime.now(zssk.TZ).date()
    start = date.fromisoformat(config.get('date_start', today.isoformat()))
    end = date.fromisoformat(config.get('date_end', (zssk.month_end(today) - timedelta(days=1)).isoformat()))
    return start, end


def selected_schedule(config):
    start, end = selected_range(config)
    return zssk.range_schedule(start, end, excluded=config.get('exclude_dates', []), config=config)


@app.post('/api/range')
def set_range():
    with lock:
        if state['running']:
            return jsonify(error='Počas nákupu sa rozsah nedá meniť.'), 409
        data = request.get_json()
        try:
            start = date.fromisoformat(data['start'])
            end = date.fromisoformat(data['end'])
            zssk.range_schedule(start, end)
        except (ValueError, TypeError, KeyError):
            return jsonify(error='Vyber platné dátumy od–do, najviac jeden rok.'), 400
        config = load(zssk.CONFIG, {})
        config.update(date_start=start.isoformat(), date_end=end.isoformat())
        zssk.save(zssk.CONFIG, config)
        return jsonify(ok=True)


@app.get('/api/state')
def status():
    with lock:
        history = load(zssk.HISTORY, {})
        config = load(zssk.CONFIG, {})
        planned = selected_schedule(config)
        preview = month_test_trip(excluded=config.get('exclude_dates', []), history=history, config=config)
        trips = [{'key': zssk.journey_key(d, t, config), 'date': d.isoformat(), 'time': t,
                  'status': ('overiť' if history.get(zssk.journey_key(d, t, config), {}).get('verification') == 'needs_review'
                             else 'potvrdené' if zssk.journey_key(d, t, config) in history else outcomes.get(zssk.journey_key(d,t,config), 'čaká'))}
                 for d, t in planned]
        start, end = selected_range(config)
        return jsonify(**state, trips=trips, review=pending_review(history),
                       configured=all(config.get(k) for k in ('firstname','lastname','email','discount_number')),
                       timetable=zssk.timetable(config),
                       route={'origin':zssk.route(config)[0], 'destination':zssk.route(config)[1]},
                       selection={'start':start.isoformat(),'end':end.isoformat(),
                                  'today':datetime.now(zssk.TZ).date().isoformat(),
                                  'excluded':config.get('exclude_dates',[])},
                       test_preview=(str(preview[0][0]) + ' ' + preview[0][1]) if preview else '')


@app.post('/api/timetable')
def set_timetable():
    import re
    with lock:
        if state['running']:
            return jsonify(error='Počas nákupu sa dni a časy nedajú meniť.'), 409
        data = request.get_json()
        times = data.get('timetable')
        if (not isinstance(times, dict) or not times or
                any(key not in '0123456' or len(key) != 1 or not isinstance(value, str)
                    or re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value) is None
                    for key, value in times.items())):
            return jsonify(error='Zapni aspoň jeden deň a zadaj platné časy HH:MM.'), 400
        config = load(zssk.CONFIG, {})
        config['timetable'] = times
        zssk.save(zssk.CONFIG, config)
        return jsonify(ok=True)


@app.post('/api/route')
def set_route():
    with lock:
        if state['running']:
            return jsonify(error='Počas nákupu sa trasa nedá meniť.'), 409
        data = request.get_json()
        origin, destination = (str(data.get(key, '')).strip() for key in ('origin','destination'))
        def valid(value):
            return 2 <= len(value) <= 100 and all(c.isalnum() or c in ' -.,()/’' for c in value)
        if not valid(origin) or not valid(destination) or origin.casefold() == destination.casefold():
            return jsonify(error='Vyber dve rôzne stanice a skontroluj ich názvy.'), 400
        config = load(zssk.CONFIG, {})
        config.update(origin=origin, destination=destination)
        zssk.save(zssk.CONFIG, config)
        return jsonify(ok=True)


@app.post('/api/config')
def configure():
    data = request.get_json()
    with lock:
        if state['running']:
            return jsonify(error='Počas behu nemožno meniť údaje.'), 409
        old = load(zssk.CONFIG, {})
        fields = ('email', 'firstname', 'lastname', 'discount_number')
        config = {k: str(data.get(k, '')).strip() for k in fields}
        if not config['discount_number']:
            config['discount_number'] = old.get('discount_number', '')
        if not all(config.values()) or '@' not in config['email']:
            return jsonify(error='Vyplň meno, priezvisko, platný e-mail a číslo zľavy.'), 400
        age = data.get('age_category', 'Dieťa 16 - 17 r.')
        if age not in ('Dieťa 16 - 17 r.', 'Mladý 18 - 25 r.'):
            return jsonify(error='Neplatná veková kategória.'), 400
        excluded = str(data.get('exclude_dates', '')).replace(',', ' ').split()
        try:
            for day in excluded:
                if date.fromisoformat(day).isoformat() != day:
                    raise ValueError()
        except ValueError:
            return jsonify(error='Vylúčené dátumy musia byť vo formáte RRRR-MM-DD.'), 400
        config.update(age_category=age, exclude_dates=excluded)
        for key in ('date_start','date_end','origin','destination','timetable'):
            if key in old:
                config[key] = old[key]
        zssk.save(zssk.CONFIG, config)
        return jsonify(ok=True)


@app.post('/api/start')
def start():
    global command, stop_requested, test_target
    with lock:
        if state['running']:
            return jsonify(error='Nákup už beží.'), 409
        config = load(zssk.CONFIG, {})
        if not all(config.get(k) for k in ('firstname','lastname','email','discount_number')):
            return jsonify(error='Najprv ulož údaje.'), 400
        history = load(zssk.HISTORY, {})
        if pending_review(history):
            return jsonify(error='Najprv vyrieš prerušené nákupy v časti Overenie.'), 409
        data = request.get_json()
        limit = data.get('limit', 0)
        if type(limit) is not int or limit not in (0, 1):
            return jsonify(error='Neplatný rozsah.'), 400
        trips = [(d, t) for d, t in selected_schedule(config)
                 if zssk.journey_key(d, t, config) not in history]
        if limit:
            trips = month_test_trip(excluded=config.get('exclude_dates', []), history=history, config=config)
            test_target = trips[0] if trips else None
        if not trips:
            return jsonify(error='V tomto rozsahu už nie sú čakajúce lístky.'), 400
        command, stop_requested = None, False
        state.update(running=True, phase='preparing', completed=0, total=len(trips), current='',
                     message='Otváram prehliadač ZSSK...')
        threading.Thread(target=worker, args=(config, trips, bool(limit)), daemon=True).start()
        return jsonify(ok=True)


@app.post('/api/action')
def action():
    global command, stop_requested
    data = request.get_json()
    with condition:
        kind = data.get('action')
        if kind == 'stop':
            stop_requested = True
            if state['running']:
                state.update(message='Zastavujem. Aktuálny krok webu môže chvíľu trvať.')
            condition.notify_all()
            return jsonify(ok=True)
        if state['phase'] != 'waiting' or command is not None:
            return jsonify(error='Teraz sa nečaká na potvrdenie lístka.'), 409
        order = str(data.get('order', '')).strip()
        if kind == 'done' and (not order or len(order) > 120):
            return jsonify(error='Zadaj skutočné číslo vystavenej objednávky.'), 400
        if kind not in ('done', 'skip'):
            return jsonify(error='Neplatná akcia.'), 400
        command = (kind, order)
        condition.notify_all()
        return jsonify(ok=True)


@app.post('/api/review')
def review():
    data = request.get_json()
    with lock:
        if state['running']:
            return jsonify(error='Najprv zastav aktuálny beh.'), 409
        history = load(zssk.HISTORY, {})
        key = data.get('key')
        if key not in pending_review(history):
            return jsonify(error='Záznam už nevyžaduje overenie.'), 400
        order = str(data.get('order', '')).strip()
        if data.get('action') == 'done' and len(order) <= 120:
            history[key] = {'order': order or None, 'recorded_at': datetime.now(zssk.TZ).isoformat(),
                            'verification': 'user_confirmed'}
        elif data.get('action') == 'not_bought':
            del history[key]
        else:
            return jsonify(error='Vyber existujúcu objednávku alebo potvrď, že lístok nebol kúpený.'), 400
        zssk.save(zssk.HISTORY, history)
        return jsonify(ok=True)


def record(key, value):
    with lock:
        history = load(zssk.HISTORY, {})
        if value is None:
            history.pop(key, None)
        else:
            history[key] = value
        zssk.save(zssk.HISTORY, history)


def worker(config, trips, dry_run=False):
    global command
    dry_success = False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=['--disable-dev-shm-usage', '--window-size=980,1400', '--window-position=0,0'])
            try:
                for day, departure in trips:
                    with lock:
                        if stop_requested:
                            break
                        state.update(phase='preparing', current=f'{day} {departure}', message='Pripravujem nulový lístok...')
                    if datetime.combine(day, zssk.time.fromisoformat(departure), zssk.TZ) <= datetime.now(zssk.TZ):
                        continue
                    key = zssk.journey_key(day, departure, config)
                    if not dry_run:
                        record(key, {'verification': 'needs_review', 'recorded_at': datetime.now(zssk.TZ).isoformat()})
                    context = browser.new_context(locale='sk-SK', timezone_id='Europe/Bratislava', no_viewport=True)
                    try:
                        page = context.new_page()
                        page.set_default_timeout(60000)
                        page.set_default_navigation_timeout(60000)
                        try:
                            zssk.prepare(page, day, departure, config)
                            def stopped():
                                with lock:
                                    return stop_requested
                            def progress(message):
                                with lock:
                                    state.update(phase='preparing', message=message)
                            order = zssk.finish_purchase(page, day, departure, config, stopped, progress, dry_run=dry_run)
                        except zssk.SoldOut:
                            if not dry_run:
                                record(key, None)
                            with condition:
                                state.update(phase='error', message=f'{day}: web hlási vypredanú nulovú ponuku. Prehliadač ostáva otvorený na kontrolu. Po kontrole stlač Zastaviť.')
                                condition.wait_for(lambda: stop_requested)
                            break
                        except zssk.CheckoutStopped:
                            break
                        except Exception as exc:
                            print("Nákup zastavený:", type(exc).__name__, flush=True)
                            with condition:
                                detail = str(exc) if type(exc) is RuntimeError else type(exc).__name__
                                step = state['message']
                                hint = 'Test nekupuje lístok. Stlač Zastaviť.' if dry_run else 'Stlač Zastaviť a skontroluj ZSSK/e-mail v časti Overenie.'
                                state.update(phase='error', message=f'{step} Zastavené: {detail}. {hint}')
                                condition.wait_for(lambda: stop_requested)
                            break
                        if dry_run:
                            dry_success = True
                            with condition:
                                state.update(phase='tested', completed=1,
                                             message='Test prešiel. Žiadny lístok nebol kúpený. Pozri finálny súhrn cez Zobraziť ZSSK; potom stlač Zastaviť.')
                                condition.wait_for(lambda: stop_requested)
                            break
                        record(key, {'order': order, 'recorded_at': datetime.now(zssk.TZ).isoformat(),
                                     'verification': 'zssk_confirmed',
                                     'confirmation': 'ZSSK potvrdila vystavenie dokladu'})
                        with lock:
                            state['message'] = f'{day} {departure}: lístok vystavený a potvrdený ZSSK.'
                        with lock:
                            state['completed'] += 1
                    finally:
                        context.close()
            finally:
                browser.close()
        with lock:
            state.update(phase='idle', message=('Test prešiel. Žiadny lístok nebol kúpený.' if dry_success else
                         'Beh zastavený.' if stop_requested else 'Rozpis prejdený. Skontroluj potvrdené a čakajúce dátumy.'))
    except Exception as exc:
        print('Chyba prehliadača:', type(exc).__name__, flush=True)
        with lock:
            state.update(phase='error', message='Prehliadač sa nespustil alebo zlyhal. Pozri Termux a over inštaláciu.')
    finally:
        with lock:
            state['running'] = False




def port_ready(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.25):
            return True
    except OSError:
        return False


def main(tui=False):
    os.umask(0o077)
    zssk.BASE.mkdir(parents=True, exist_ok=True, mode=0o700)
    processes = []
    with (zssk.BASE / 'run.lock').open('a') as process_lock:
        try:
            fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('ZSSK už beží. Otvor http://127.0.0.1:8765')
        if port_ready(8765) or port_ready(6080) or port_ready(5900):
            raise SystemExit('Port 8765, 6080 alebo 5900 je obsadený. Ukonči predchádzajúci beh.')
        display = next((n for n in range(99, 120) if not Path(f'/tmp/.X{n}-lock').exists()
                        and not Path(f'/tmp/.X11-unix/X{n}').exists()), None)
        if display is None:
            raise SystemExit('Nie je dostupná obrazovka Xvfb.')
        os.environ['DISPLAY'] = f':{display}'
        passwd = zssk.BASE / 'vnc.pass'
        log = (zssk.BASE / 'display.log').open('w')
        try:
            processes.append(subprocess.Popen(['Xvfb', f':{display}', '-screen', '0', '1000x1500x24', '-nolisten', 'tcp', '-extension', 'MIT-SHM'], stdout=log, stderr=log))
            deadline = time.monotonic() + 15
            while not Path(f'/tmp/.X11-unix/X{display}').exists():
                if processes[0].poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Xvfb sa nespustil. Pozri display.log.')
                time.sleep(0.1)
            subprocess.run(['x11vnc', '-storepasswd', PIN, str(passwd)], check=True, stdout=log, stderr=log)
            passwd.chmod(0o600)
            processes.append(subprocess.Popen(['x11vnc', '-display', f':{display}', '-rfbport', '5900',
                '-listen', '127.0.0.1', '-localhost', '-rfbauth', str(passwd), '-forever', '-shared', '-noxdamage', '-noshm'], stdout=log, stderr=log))
            processes.append(subprocess.Popen(['websockify', '--web=/usr/share/novnc', '127.0.0.1:6080',
                '127.0.0.1:5900'], stdout=log, stderr=log))
            deadline = time.monotonic() + 15
            while not (port_ready(6080) and port_ready(5900)):
                if any(proc.poll() is not None for proc in processes) or time.monotonic() > deadline:
                    raise RuntimeError('Zobrazenie prehliadača sa nespustilo. Pozri display.log.')
                time.sleep(0.2)
            launch_file = Path(__file__).parent / '.launch-url'
            launch_file.write_text('http://127.0.0.1:8765/launch?token=' + LAUNCH_TOKEN, encoding='utf-8')
            launch_file.chmod(0o600)
            pin_file = Path(__file__).parent / '.launch-pin'
            pin_file.write_text(PIN, encoding='utf-8')
            pin_file.chmod(0o600)
            import logging
            logging.getLogger('werkzeug').setLevel(logging.ERROR)
            print('\nOtvor v mobile: http://127.0.0.1:8765', flush=True)
            print('PIN pre ovládanie aj noVNC:', PIN, flush=True)
            print('Termux musí počas nákupu bežať. Ukončenie: Ctrl+C.\n', flush=True)
            def shutdown(*_):
                global stop_requested
                with condition:
                    stop_requested = True
                    condition.notify_all()
                raise KeyboardInterrupt()
            signal.signal(signal.SIGTERM, shutdown)
            if tui:
                from tui import ZsskApp
                ZsskApp().run()
            else:
                app.run(host='127.0.0.1', port=8765, debug=False, use_reloader=False, threaded=True)
        except KeyboardInterrupt:
            pass
        finally:
            with condition:
                global stop_requested
                stop_requested = True
                condition.notify_all()
            for proc in reversed(processes):
                if proc.poll() is None:
                    proc.terminate()
            for proc in reversed(processes):
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            (Path(__file__).parent / '.launch-url').unlink(missing_ok=True)
            (Path(__file__).parent / '.launch-pin').unlink(missing_ok=True)
            passwd.unlink(missing_ok=True)
            log.close()


if __name__ == '__main__':
    main()
