import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import zssk
import mobile


class ConfigurationTests(unittest.TestCase):
    def test_custom_schedule(self):
        config = {'timetable': {'0': '08:10', '3': '16:20', '5': '09:00'}}
        trips = zssk.range_schedule(date(2026, 11, 2), date(2026, 11, 8),
                                    datetime(2026, 10, 6, tzinfo=zssk.TZ), config=config)
        self.assertEqual(trips, [(date(2026, 11, 2), '08:10'),
                                (date(2026, 11, 5), '16:20'), (date(2026, 11, 7), '09:00')])

    def test_route_history(self):
        day = date(2026, 11, 2)
        self.assertNotEqual(zssk.journey_key(day, '14:35'),
                            zssk.journey_key(day, '14:35', {'origin': 'Žilina', 'destination': 'Košice'}))

    def test_public_theme_and_saved_configuration(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(zssk, 'CONFIG', Path(directory) / 'config.json'), \
                patch.object(zssk, 'HISTORY', Path(directory) / 'history.json'):
            client = mobile.app.test_client()
            base = 'http://127.0.0.1:8765'
            for path in ('/static/theme.js', '/static/theme.css'):
                response = client.get(path, base_url=base)
                self.assertEqual(response.status_code, 200)
                response.close()
            login = client.get('/login', base_url=base)
            self.assertIn('/static/theme.js', login.text)
            self.assertEqual(client.get('/api/state', base_url=base).status_code, 401)
            with client.session_transaction(base_url=base) as session:
                session['authenticated'] = True
                session['csrf'] = 'test'
            mobile.state['running'] = False
            def post(path, data):
                return client.post('/api/' + path, json=data, base_url=base,
                                   headers={'X-CSRF-Token': 'test'})
            self.assertEqual(post('timetable', {'timetable': {'1': '17:15'}}).status_code, 200)
            self.assertEqual(post('route', {'origin': 'Žilina', 'destination': 'Košice'}).status_code, 200)
            self.assertEqual(post('config', {'firstname': 'Test', 'lastname': 'Tester',
                             'email': 'test@example.com', 'discount_number': '123'}).status_code, 200)
            state = client.get('/api/state', base_url=base).json
            self.assertEqual(state['timetable'], {'1': '17:15'})
            self.assertEqual(state['route']['origin'], 'Žilina')
            self.assertEqual(post('timetable', {'timetable': {'1': '25:15'}}).status_code, 400)
