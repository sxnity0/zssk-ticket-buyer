import sys, unittest
from datetime import date,datetime
from unittest.mock import patch
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
import zssk, mobile
C={'firstname':'Test','lastname':'Tester','email':'test@example.com'}
D=date(2026,10,12)
SUMMARY='Súhlasím s obchodnými podmienkami. Súhrn 12.10.2026 14:35 Poprad-Tatry Liptovský Mikuláš Test Tester test@example.com Celková suma 0,00 € nulová platba 2. trieda'
class Empty:
    def count(self):return 0
    def locator(self,*a):return self

class Control:
    def __init__(self): self.clicks=0;self.checks=0
    def count(self):return 1
    def is_checked(self):return bool(self.checks)
    def or_(self,other):return self
    def evaluate(self,js):self.checks=1
    def evaluate_all(self,js):return 0
    def nth(self,index):return self
    def locator(self,*a):return Empty()
    def check(self,**kw):self.checks+=1
    def click(self):self.clicks+=1
    def all(self):return []
class Page:
    def __init__(self):self.radio=Control();self.terms=Control();self.url='https://predaj.zssk.sk/document'
    def get_by_role(self,role,**kw):return self.radio if role=='radio' else self.terms
    def locator(self,selector):return self.terms if 'checkbox' in selector else self.radio
class Tests(unittest.TestCase):
    def test_summary(self):zssk.assert_summary(SUMMARY,D,'14:35',C)
    def test_reject(self):
        for old,new in [('12.10.2026','06.10.2026'),('14:35','05:35'),('0,00 €','1,00 €'),('Poprad-Tatry','Bratislava'),('Tester','Other'),('2. trieda','1. trieda'),('nulová platba','platobná karta')]:
            with self.subTest(old=old),self.assertRaises(RuntimeError):zssk.assert_summary(SUMMARY.replace(old,new),D,'14:35',C)
    def test_confirmation(self):
        self.assertEqual(zssk.issued_order('Objednávka úspešne dokončená. Číslo objednávky: 12345678'),'12345678')
        self.assertEqual(zssk.issued_order('Payment successful. Order number: AB123456'),'AB123456')
        self.assertIsNone(zssk.issued_order('Overview. Order number: AB123456'))
        self.assertIsNone(zssk.issued_order('Payment successful.'))
        self.assertEqual(zssk.issued_order('Číslo objednávky: 12345678',True),'12345678')
    def flow(self,summary=SUMMARY,stop=False,timeout=False,dry=False):
        p=Page();clicks=[];texts=iter(['Výber platby Bez úhrady',summary,'Objednávka úspešne dokončená. Číslo objednávky: 12345678'])
        def wait(page,predicate,**kwargs):
            text=next(texts)
            page.url='https://predaj.zssk.sk/payment' if text.startswith('Výber platby') else 'https://predaj.zssk.sk/document'
            if timeout and 'úspešne' in text:raise RuntimeError('Timeout')
            self.assertTrue(predicate(text));return text
        def control(page,name):
            c=Control();c.click=lambda:clicks.append(name);return c
        with patch.object(zssk,'wait_for',wait),patch.object(zssk,'visible_text',return_value=summary),patch.object(zssk,'checkout_control',control):
            try:return zssk.finish_purchase(p,D,'14:35',C,lambda:stop,dry_run=dry),clicks
            finally:self.clicks=clicks;self.page=p
    def test_complete_flow(self):
        order,clicks=self.flow();self.assertEqual(order,'12345678');self.assertEqual(len(clicks),3);self.assertEqual(self.page.terms.checks,1)
    def test_paid_does_not_submit(self):
        with self.assertRaises(RuntimeError):self.flow(SUMMARY.replace('0,00','3,50'))
        self.assertEqual(len(self.clicks),2)
    def test_stop_does_not_click(self):
        with self.assertRaises(zssk.CheckoutStopped):self.flow(stop=True)
        self.assertEqual(self.clicks,[])
    def test_timeout_no_retry(self):
        with self.assertRaises(RuntimeError):self.flow(timeout=True)
        self.assertEqual(len(self.clicks),3)
    def test_slovak_labels(self):
        zssk.assert_summary(SUMMARY.replace('nulová platba','Bez úhrady'),D,'14:35',C)
    def test_document(self):
        text='Želáme Vám šťastnú cestu. Vaša platba prebehla v poriadku. Uložiť lístok'
        self.assertTrue(zssk.document_confirmed(text,'https://predaj.zssk.sk/document',True))
        self.assertFalse(zssk.document_confirmed(text,'https://predaj.zssk.sk/summary',True))
        self.assertFalse(zssk.document_confirmed(text,'https://predaj.zssk.sk/document',False))
        self.assertFalse(zssk.document_confirmed('Výber platby','https://predaj.zssk.sk/document',True))
    def test_hidden_checkbox_without_role(self):
        p=Page()
        with patch.object(zssk,'visible_text',return_value='Súhlasím s obchodnými podmienkami'),patch.object(p,'get_by_role',side_effect=AssertionError('Hidden input must use native locator')):
            zssk.accept_terms(p)
            self.assertTrue(p.terms.is_checked())
            zssk.accept_terms(p)
            self.assertTrue(p.terms.is_checked())
    def test_terms_stop(self):
        p=Page()
        with patch.object(zssk,'visible_text',return_value='Súhlasím s obchodnými podmienkami'),self.assertRaises(zssk.CheckoutStopped):
            zssk.accept_terms(p,lambda:True)
        self.assertFalse(p.terms.is_checked())
    def test_dry_run_never_submits(self):
        order,clicks=self.flow(dry=True)
        self.assertIsNone(order)
        self.assertEqual(len(clicks),2)
        self.assertFalse(any('Platba' in name for name in clicks))
    def test_wait_for_real_form(self):
        p=Page();p.url='https://predaj.zssk.sk/personal'
        self.assertFalse(zssk.payment_form_ready(p,'Osobné údaje Výber platby Súhrn'))
        p.url='https://predaj.zssk.sk/payment'
        self.assertFalse(zssk.payment_form_ready(p,'Výber platby'))
        self.assertTrue(zssk.payment_form_ready(p,'Výber platby Bez úhrady'))
    def test_week(self):
        self.assertEqual(mobile.month_test_trip(datetime(2026,10,5,23,44,tzinfo=zssk.TZ))[0],(D,'14:35'))
if __name__ == '__main__':
    unittest.main()
